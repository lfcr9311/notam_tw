import json
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from extract import FIELDS, extract_forecast, parse_json
from sources import fetch_tomorrow_timelines

load_dotenv()

BASE = Path(__file__).parent
app = FastAPI(title="NOTAM TW PoC")

SALVADOR = '5fcbbe65608b03000882f151'
BELEM = '5fcbbe65608b03000882f14c'
NORONHA = '5fcbbcc19229c70007cd50e9'
CASCAVEL = '5fcbbc5d0d9a470007a0dd67'

# ID da location na Tomorrow.io -> nome exibido no select
LOCATIONS = {
    SALVADOR: "Salvador",
    BELEM: "Belém",
    NORONHA: "Fernando de Noronha",
    CASCAVEL: "Cascavel",
}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    """Usado pelo deploy para conferir se subiu (não chama a Tomorrow.io)."""
    return {"status": "ok"}


@app.get("/api/locations")
def locations():
    return [{"id": loc_id, "name": name} for loc_id, name in LOCATIONS.items()]


@app.get("/api/forecast")
async def forecast(location: str = Query(..., description="ID da location (uma das chaves de LOCATIONS)")):
    """Faz a request na Tomorrow.io pelo ID da location (gasta 1 request do limite)."""
    if location not in LOCATIONS:
        raise HTTPException(400, "location deve ser o ID de uma das bases cadastradas")
    try:
        raw = await fetch_tomorrow_timelines(location, list(FIELDS.values()))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Tomorrow.io: {e.response.text[:300]}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Falha ao contatar Tomorrow.io: {e}")
    data = extract_forecast(raw)
    data["location"]["name"] = data["location"]["name"] or LOCATIONS[location]
    data["location"]["id"] = location
    return data


@app.post("/api/extract")
def extract(text: str = Body(..., media_type="text/plain")):
    """Extrai os campos de um JSON colado (não gasta request)."""
    try:
        raw = parse_json(text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON inválido: {e}")
    return extract_forecast(raw)
