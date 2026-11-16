"""Testes sem rede: a Tomorrow.io nunca e chamada (limite de requests); usa mock."""
import json

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

TIMELINES = {
    "data": {
        "timelines": [{
            "timestep": "1h",
            "intervals": [
                {"startTime": "2026-11-13T12:00:00Z",
                 "values": {"temperature": 28.1, "rainIntensity": 0.4, "precipitationProbability": 35}},
            ],
        }]
    }
}
EXPECTED_HOUR = {"time": "2026-11-13T12:00:00Z", "temperature": 28.1,
                 "rain_intensity": 0.4, "precipitation_probability": 35}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    app_module._cache.clear()
    def blocked(*a, **k):
        raise AssertionError("teste tentou chamar a Tomorrow.io")
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", blocked)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_index():
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_locations():
    ids = {loc["id"] for loc in client.get("/api/locations").json()}
    assert ids == set(app_module.LOCATIONS)


def test_extract_pasted_json():
    r = client.post("/api/extract", content=json.dumps(TIMELINES), headers={"content-type": "text/plain"})
    assert r.status_code == 200
    assert r.json()["hourly"] == [EXPECTED_HOUR]


def test_forecast_unknown_location():
    assert client.get("/api/forecast", params={"location": "xyz"}).status_code == 400


def test_forecast_mocked(monkeypatch):
    async def fake_fetch(location, fields):
        assert location == app_module.SALVADOR
        return TIMELINES
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", fake_fetch)
    data = client.get("/api/forecast", params={"location": app_module.SALVADOR}).json()
    assert data["location"]["name"] == "Salvador"
    assert data["hourly"] == [{**EXPECTED_HOUR, "tags": []}]


def test_locations_tem_icao():
    locs = {loc["name"]: loc["icao"] for loc in client.get("/api/locations").json()}
    assert locs == {"Salvador": "SBSV", "Belém": "SBBE"}


def test_forecast_devolve_icao(monkeypatch):
    async def fake_fetch(location, fields):
        return TIMELINES
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", fake_fetch)
    data = client.get("/api/forecast", params={"location": app_module.BELEM}).json()
    assert data["location"]["icao"] == "SBBE"


def test_forecast_usa_cache(monkeypatch):
    calls = []

    async def fake_fetch(location, fields):
        calls.append(location)
        return TIMELINES
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", fake_fetch)
    first = client.get("/api/forecast", params={"location": app_module.SALVADOR}).json()
    second = client.get("/api/forecast", params={"location": app_module.SALVADOR}).json()
    assert calls == [app_module.SALVADOR]
    assert (first["cached"], second["cached"]) == (False, True)
