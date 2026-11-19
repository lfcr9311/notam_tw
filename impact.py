"""Condicoes por hora da previsao e juncao (em memoria) dos voos da malha com elas.

Voo impactado = Dep (partida) numa base com chuva (leve, moderada ou forte)/pista molhada na hora do STD, na hora anterior ou na
seguinte; ou Arv (chegada) numa base com condicao na hora do STA, na anterior ou na seguinte.
"""
from datetime import datetime

HOUR = 3600

# criterios em mm/h de intensidade de precipitacao
DRIZZLE, LIGHT_RAIN, RAIN, HEAVY_RAIN, WET_RUNWAY = 0.1, 0.5, 2.6, 10, 3


def conditions(hour: dict) -> list[list[str]]:
    """[[classe css, rotulo], ...] da hora; vazio = sem condicao."""
    i = hour.get("rain_intensity") or 0
    tags = []
    if i >= HEAVY_RAIN:
        tags.append(["heavy", "Chuva forte"])
    elif i >= RAIN:
        tags.append(["rain", "Chuva"])
    elif i >= LIGHT_RAIN:
        tags.append(["light", "Chuva leve"])
    elif i >= DRIZZLE:
        tags.append(["drizzle", "Chuvisco"])  # so informativo: nao impacta voo
    if i > WET_RUNWAY:
        tags.append(["wet", "Possibilidade de pista molhada"])
    return tags


def relevant(tags: list[list[str]]) -> list[list[str]]:
    """Condicoes que impactam voo (tudo menos chuvisco)."""
    return [t for t in tags if t[0] != "drizzle"]


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


MARGIN_H = 1  # horas antes e depois do horario do voo


def _merge(found: list[tuple[dict, list]]) -> list[list[str]]:
    """Junta as condicoes das horas da janela: chuva forte > chuva > chuva leve; pista molhada se houver em alguma."""
    labels = {t[1]: t for _, tags in found for t in tags}
    out = []
    if "Chuva forte" in labels:
        out.append(labels["Chuva forte"])
    elif "Chuva" in labels:
        out.append(labels["Chuva"])
    elif "Chuva leve" in labels:
        out.append(labels["Chuva leve"])
    if "Possibilidade de pista molhada" in labels:
        out.append(labels["Possibilidade de pista molhada"])
    return out


def impacted(flights: list[dict], forecasts: dict[str, list[dict]]) -> list[dict]:
    """flights: voos de flights.load_flights (std/sta datetime UTC, dep/arr ICAO).
    forecasts: ICAO da base -> horas da previsao (extract_forecast()["hourly"])."""
    slots = {
        icao: {int(_epoch(h["time"]) // HOUR): (h, tags) for h in hourly if (tags := relevant(conditions(h)))}
        for icao, hourly in forecasts.items()
    }
    out = []
    for f in flights:
        # Dep = partida da base (horario de partida); Arv = chegada na base (horario de chegada)
        for leg, here, other, when in (("Dep", f["dep"], f["arr"], f["std"]),
                                       ("Arv", f["arr"], f["dep"], f["sta"])):
            base = slots.get(here)
            if base is None:
                continue
            k = int(when.timestamp() // HOUR)
            found = [base[k + d] for d in range(-MARGIN_H, MARGIN_H + 1) if k + d in base]
            if not found:
                continue
            out.append({
                "flight": f["flight"], "airport": here, "leg": leg, "other": other,
                "time": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "tags": _merge(found),
                "hours": [h["time"] for h, _ in found],  # horas com condicao dentro da janela
                "rain_intensity": max(h.get("rain_intensity") or 0 for h, _ in found),
                "precipitation_probability": max(h.get("precipitation_probability") or 0 for h, _ in found),
            })
    out.sort(key=lambda x: (x["time"], x["flight"]))
    return out
