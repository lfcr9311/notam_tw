import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

from extract import FIELDS, extract_forecast, parse_json
from flights import HORIZON_DAYS, ScheduleError, build_payload
from impact import conditions, impacted
from sources import fetch_tomorrow_timelines

load_dotenv()

BASE = Path(__file__).parent
app = FastAPI(title="NOTAM TW PoC")

SALVADOR = '5fcbbe65608b03000882f151'
BELEM = '5fcbbe65608b03000882f14c'

# bases cadastradas: ID da location na Tomorrow.io -> nome no select + ICAO (cruza com os voos da malha)
LOCATIONS = {
    SALVADOR: {"name": "Salvador", "icao": "SBSV"},
    BELEM: {"name": "Belém", "icao": "SBBE"},
}

# previsão de 360h de cada base fica em memória por FORECAST_CACHE_MIN minutos (padrão 60):
# consultar a base de novo ou cruzar com a malha nesse intervalo não gasta request
CACHE_SECONDS = 60 * int(os.getenv("FORECAST_CACHE_MIN", "60"))
_cache: dict[str, tuple[float, dict]] = {}  # location id -> (instante da consulta, extract_forecast)


def cached(location: str) -> bool:
    hit = _cache.get(location)
    return bool(hit) and time.time() - hit[0] < CACHE_SECONDS


async def get_forecast(location: str) -> tuple[dict, bool]:
    """(previsão extraída, veio do cache). Erros da Tomorrow.io viram HTTPException."""
    if cached(location):
        return _cache[location][1], True
    try:
        raw = await fetch_tomorrow_timelines(location, list(FIELDS.values()))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Tomorrow.io: {e.response.text[:300]}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Falha ao contatar Tomorrow.io: {e}")
    data = extract_forecast(raw)
    for h in data["hourly"]:
        h["tags"] = conditions(h)
    data["location"].update(name=data["location"]["name"] or LOCATIONS[location]["name"],
                            id=location, icao=LOCATIONS[location]["icao"])
    _cache[location] = (time.time(), data)
    return data, False


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    """Usado pelo deploy para conferir se subiu (não chama a Tomorrow.io)."""
    return {"status": "ok"}


@app.get("/api/locations")
def locations():
    return [{"id": loc_id, **loc} for loc_id, loc in LOCATIONS.items()]


@app.get("/api/forecast")
async def forecast(location: str = Query(..., description="ID da location (uma das chaves de LOCATIONS)")):
    """Previsão de 360h da base (1 request do limite, ou nenhum se estiver no cache)."""
    if location not in LOCATIONS:
        raise HTTPException(400, "location deve ser o ID de uma das bases cadastradas")
    data, hit = await get_forecast(location)
    return {**data, "cached": hit}


@app.post("/api/extract")
def extract(text: str = Body(..., media_type="text/plain")):
    """Extrai os campos de um JSON colado (não gasta request)."""
    try:
        raw = parse_json(text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON inválido: {e}")
    return extract_forecast(raw)


MAX_UPLOAD = 20 * 1024 * 1024  # malha .xlsx tem ~0,5 MB


async def _schedule(request: Request, filename: str) -> dict:
    """Le a malha enviada como corpo cru (fetch(url, {body: file})) e monta os registros."""
    data = await request.body()
    if not data:
        raise HTTPException(400, "Arquivo vazio")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Arquivo maior que 20 MB")
    try:
        return build_payload(data, filename or "malha.xlsx", HORIZON_DAYS)
    except ScheduleError as e:
        raise HTTPException(400, str(e))


@app.post("/api/flights/preview")
async def flights_preview(request: Request, x_filename: str = Header("malha.xlsx")):
    """Prévia da malha: voos da janela e bases presentes (não chama a Tomorrow.io)."""
    out = await _schedule(request, x_filename)
    n = len(out["flights"])
    bases = _bases_in(out["flights"])
    return {
        "bases": [_base_summary(loc, out) for loc in LOCATIONS],
        "impact_requests": sum(not cached(b) for b in bases),
        "count": n,
        "window": out["window"],
        "basis": out["basis"],
        "warnings": out["warnings"],
        "flights": [
            {"flight": f["flight"], "dep": f["dep"], "arr": f["arr"], "std": r["fields"]["originalEstimatedDepartureTime"],
             "sta": r["fields"]["originalEstimatedArrivalTime"], "aircraft": f["aircraft"]}
            for f, r in zip(out["flights"], out["records"])  # todos: o front cruza com a previsão
        ],
    }


def _base_summary(loc: str, out: dict) -> dict:
    """Voos distintos da malha com Dep (partindo da base) e Arv (chegando nela)."""
    icao = LOCATIONS[loc]["icao"]
    dep = sorted({f["flight"] for f in out["flights"] if f["dep"] == icao})
    arv = sorted({f["flight"] for f in out["flights"] if f["arr"] == icao})
    return {"name": LOCATIONS[loc]["name"], "icao": icao, "cached": cached(loc), "dep": dep, "arv": arv}


def _bases_in(flights: list[dict]) -> list[str]:
    """IDs das bases cadastradas que aparecem como origem ou destino na malha."""
    icaos = {f["dep"] for f in flights} | {f["arr"] for f in flights}
    return [loc for loc, b in LOCATIONS.items() if b["icao"] in icaos]


@app.post("/api/flights/impact")
async def flights_impact(request: Request, x_filename: str = Header("malha.xlsx")):
    """Voos com chuva/pista molhada na partida ou chegada nas bases cadastradas.
    1 request por base presente na malha (as que estão no cache não gastam)."""
    out = await _schedule(request, x_filename)
    bases = _bases_in(out["flights"])
    results = await asyncio.gather(*(get_forecast(b) for b in bases))
    forecasts = {data["location"]["icao"]: data["hourly"] for data, _ in results}
    return {
        "bases": [{"name": LOCATIONS[b]["name"], "icao": LOCATIONS[b]["icao"], "cached": hit}
                  for b, (_, hit) in zip(bases, results)],
        "requests": sum(not hit for _, hit in results),
        "flights": len(out["flights"]),
        "impacted": impacted(out["flights"], forecasts),
    }
