

import json
import sys

FIELDS = {
    "temperature": "temperature",
    "rain_intensity": "rainIntensity",
    "precipitation_probability": "precipitationProbability",
}


def parse_json(text: str):
    """Faz o parse do texto; se for trecho solto de lista, envolve em [ ]."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads("[" + text.rstrip(",").strip() + "]")


def extract_forecast(raw) -> dict:
    if isinstance(raw, list):
        loc, hourly = {}, raw
    elif isinstance(raw.get("data"), dict) and "timelines" in raw["data"]:  # POST /v4/timelines
        timelines = raw["data"]["timelines"]
        tl = next((t for t in timelines if t.get("timestep") == "1h"), timelines[0] if timelines else {})
        loc, hourly = {}, tl.get("intervals", [])
    elif "timelines" in raw:  # GET /v4/weather/forecast
        loc, hourly = raw.get("location", {}), raw["timelines"].get("hourly", [])
    else:  # um único item {"time": ..., "values": {...}}
        loc, hourly = {}, [raw]

    return {
        "location": {"name": loc.get("name"), "lat": loc.get("lat"), "lon": loc.get("lon")},
        "hourly": [
            {"time": h.get("time") or h.get("startTime"), **{k: h.get("values", {}).get(src) for k, src in FIELDS.items()}}
            for h in hourly
        ],
    }


if __name__ == "__main__":
    text = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    print(json.dumps(extract_forecast(parse_json(text)), indent=2, ensure_ascii=False))
