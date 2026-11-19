"""Malha -> Flight Schedule. Sem rede: o envio a Tomorrow.io e sempre mockado."""
import io
from datetime import datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app as app_module
import flights

UTC = timezone.utc
NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)  # terca
HEADER = ["Flt Desg", "Eff Date", "Dis Date", "Freq", "Dept Arp", "Dept Time", "Arvl Arp", "Arrv Time",
          "Subfleet", "Block Time"]
CSV = "\n".join([
    ";".join(HEADER),
    "AD  2002;01/12/2026;31/12/2026;.2.4567;VCP;00:00;MAO;03:40;AD  32X;03:40",
    "AD  4455;01/12/2026;05/12/2026;.23456.;CNF;23:30;CGH;00:55;AD  32N;01:25",
    "AD  9999;01/12/2026;31/12/2026;1234567;VCP;10:00;XXX;11:00;AD  E95;01:00",
])


@pytest.fixture(autouse=True)
def frozen_now_and_no_network(monkeypatch):
    app_module._cache.clear()
    real_build = flights.build_payload
    # testes usam D0-D14 a partir de 01/12 para nao depender da janela D7-D15 (testada a parte)
    monkeypatch.setattr(app_module, "build_payload", lambda d, n: real_build(d, n, 0, 14, NOW))

    async def blocked(*a, **k):
        raise AssertionError("teste tentou chamar a Tomorrow.io")
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", blocked)


def payload(text=CSV, days=2, use_dates=True):
    """use_dates=True: modo que respeita EffDt/DisDt/Freq (o padrao do app avalia pelo horario todo dia)."""
    return flights.build_payload(text.encode(), "malha.csv", 0, days - 1, NOW, use_dates)


def test_expande_periodo_e_frequencia():
    out = payload()
    nums = [(r["fields"]["flightNumber"], r["fields"]["originalEstimatedDepartureTime"]) for r in out["records"]]
    # janela 01/12 (terca) 00:00 -> 03/12 00:00; AZU2002 ".2.4567" nao opera quarta, AZU4455 ".23456." sim
    assert nums == [
        ("AZU2002", "2026-12-01T00:00:00Z"),
        ("AZU4455", "2026-12-01T23:30:00Z"),
        ("AZU4455", "2026-12-02T23:30:00Z"),
    ]
    assert out["basis"] == "UTC"


def test_registro_no_formato_da_tomorrow():
    r = next(r for r in payload()["records"] if r["fields"]["flightNumber"] == "AZU4455")
    assert r["external_id"] == "AZU4455-20261201-SBCF-SBSP"
    assert r["timestamp"] == "2026-12-01T10:00:00Z"
    f = r["fields"]
    assert f["globalUniqueFlightIdentifier"] == r["external_id"]
    assert (f["departureAirportIcao"], f["arrivalAirportIcao"]) == ("SBCF", "SBSP")
    assert f["originalEstimatedArrivalTime"] == "2026-12-02T00:55:00Z"  # chega no dia seguinte
    assert f["airline"] == "AZU" and f["status"] == "scheduled" and f["aircraftType"] == "A20N"
    required = {"globalUniqueFlightIdentifier", "status", "departureAirportIcao", "arrivalAirportIcao",
                "flightNumber", "airline", "updateTime", "originalEstimatedArrivalTime",
                "originalEstimatedDepartureTime"}
    assert required <= f.keys()


def test_subfleet_desconhecido_vai_sem_aircraft_type():
    r = next(r for r in payload()["records"] if r["fields"]["flightNumber"] == "AZU2002")
    assert "aircraftType" not in r["fields"]


def test_aeroporto_desconhecido_vira_aviso():
    out = payload()
    assert not any(r["fields"]["flightNumber"] == "AZU9999" for r in out["records"])
    assert any("XXX" in w for w in out["warnings"])


def test_horario_local_convertido_para_utc():
    # STA - STD (local) != block time -> horarios locais; SBKP = UTC-3
    text = "\n".join([";".join(HEADER)] + [
        f"AD  {n};01/12/2026;31/12/2026;1234567;VCP;10:00;MAO;11:40;AD  32N;03:40" for n in range(1000, 1012)])
    out = payload(text, 1)
    f = out["records"][0]["fields"]
    assert out["basis"] == "local"
    assert f["originalEstimatedDepartureTime"] == "2026-12-01T13:00:00Z"
    assert f["originalEstimatedArrivalTime"] == "2026-12-01T15:40:00Z"  # SBEG = UTC-4


def test_le_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    ws.append(["AD  2002", datetime(2026, 12, 1), datetime(2026, 12, 31), ".2.4567", "VCP", time(0, 0),
               "MAO", time(3, 40), "AD  32N", time(3, 40)])
    buf = io.BytesIO()
    wb.save(buf)
    out = flights.build_payload(buf.getvalue(), "malha.xlsx", 0, 0, NOW, use_dates=True)
    assert [r["external_id"] for r in out["records"]] == ["AZU2002-20261201-SBKP-SBEG"]


def test_coluna_faltando():
    with pytest.raises(flights.ScheduleError, match="Colunas esperadas"):
        payload("Flt Desg;Dept Arp\nAD 1;VCP")


client = TestClient(app_module.app)


def post(path, text=CSV):
    return client.post(path, content=text.encode(), headers={"x-filename": "malha.csv"})


def test_preview_nao_chama_api():
    r = post("/api/flights/preview")
    assert r.status_code == 200
    j = r.json()
    assert j["count"] > 0
    assert next(f for f in j["flights"] if f["flight"] == "AZU2002") == {"flight": "AZU2002", "dep": "SBKP", "arr": "SBEG", "std": "2026-12-01T00:00:00Z",
                               "sta": "2026-12-01T03:40:00Z", "aircraft": None}


def test_preview_arquivo_invalido():
    assert post("/api/flights/preview", "qualquer;coisa\n1;2").status_code == 400


MARKET = """,,,,,,,,,,Market Constraints,,,,,,,,,,,,,,
"Schedule: Official Schedule(v.4622 of 4622), UTC, 30Sep26-31Mar27, User:testuser",,,,,,,,,,,,,,,,,,,,,,,,
Aln,Flt Nr,Dep,Arv,Own,,Eqp,DepTm,ArvTm,Rule,,Dep Lvl,Dep Cd,Arv Lvl,Arv Cd,Rule Type,Eqp Lvl,EqpCd,,BgnTm,EndTm,EffDt,DisDt,Freq,
AD,4787,BEL,CNF,AD,,32N,20:40,23:40,Pro,,arp,BEL,grp,BEL AUX,Dep,sub,AD32N,,19:20,21:25,01Dec2026,01Dec2026,.2.....,
AD,4787,BEL,CNF,AD,,32N,20:40,23:40,Pro,,grp,ALL,arp,CNF,Arv,sub,AD32N,,19:20,21:25,01Dec2026,01Dec2026,.2.....,
AD,4372,VCP,SSA,AD,,295,23:50,02:10,Pro,,grp,SSA AUX,arp,SSA,Arv,sub,AD295,,04:20,10:30,26Nov2026,05Dec2026,.23....,

16Nov2026,,,,,01:17 PM,,,,,,,,,,,,,Page 1,,,,,,
"""


def test_market_constraints():
    out = payload(MARKET, 2)
    assert out["basis"] == "UTC" and out["warnings"] == []
    got = [(r["external_id"], r["fields"]["originalEstimatedArrivalTime"], r["fields"].get("aircraftType"))
           for r in out["records"]]
    assert got == [
        ("AZU4787-20261201-SBBE-SBCF", "2026-12-01T23:40:00Z", "A20N"),   # 2 linhas (Dep e Arv) -> 1 voo
        ("AZU4372-20261201-SBKP-SBSV", "2026-12-02T02:10:00Z", "E295"),   # chega no dia seguinte
        ("AZU4372-20261202-SBKP-SBSV", "2026-12-03T02:10:00Z", "E295"),
    ]


def test_market_constraints_upload():
    r = client.post("/api/flights/preview", content=MARKET.encode(),
                    headers={"x-filename": "Market%20Constraints_16Nov2026_131723.csv"})
    j = r.json()
    # padrao: horario de cada voo em todos os 15 dias -> AZU4787 + AZU4372 x 15 dias, mais o AZU4372 que
    # sai 30/11 23:50 e chega 01/12 02:10 (Arv dentro da janela)
    assert r.status_code == 200 and j["count"] == 31
    bases = {b["icao"]: (b["dep"], b["arv"]) for b in j["bases"]}
    assert bases == {"SBSV": ([], ["AZU4372"]), "SBBE": (["AZU4787"], [])}


def hourly(start, rain_at):
    """360h a partir de `start` (ISO UTC), com {iso da hora: intensidade}."""
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    hours = []
    for k in range(360):
        t = (t0 + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M:%SZ")
        hours.append({"startTime": t, "values": {"rainIntensity": rain_at.get(t, 0), "precipitationProbability": 40,
                                                 "temperature": 25}})
    return {"data": {"timelines": [{"timestep": "1h", "intervals": hours}]}}


def test_impacto_market_constraints(monkeypatch):
    """Horario do voo +-1h em todos os dias da previsao (datas da malha ignoradas).
    BEL: chuva forte 21h do dia 03 -> AZU4787 Dep 20:40 (hora seguinte). Chuva 19h do dia 05 -> 1h antes.
    Chuva 23h do dia 06 -> fora (2h depois). SSA: pista molhada 02h do dia 02 -> AZU4372 Arv 02:10."""
    calls = []

    async def fake_fetch(location, fields):
        calls.append(location)
        if location == app_module.BELEM:
            return hourly("2026-12-01T00:00:00Z", {"2026-12-03T21:00:00Z": 12, "2026-12-05T19:00:00Z": 2.8,
                                                   "2026-12-06T23:00:00Z": 12})
        return hourly("2026-12-01T00:00:00Z", {"2026-12-02T02:00:00Z": 3.5})
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", fake_fetch)

    pre = client.post("/api/flights/preview", content=MARKET.encode(), headers={"x-filename": "mc.csv"}).json()
    assert pre["impact_requests"] == 2

    r = client.post("/api/flights/impact", content=MARKET.encode(), headers={"x-filename": "mc.csv"})
    assert r.status_code == 200
    j = r.json()
    assert sorted(calls) == sorted([app_module.BELEM, app_module.SALVADOR]) and j["requests"] == 2
    got = [(x["flight"], x["airport"], x["leg"], x["other"], x["time"], [t[1] for t in x["tags"]], x["hours"])
           for x in j["impacted"]]
    assert got == [
        ("AZU4372", "SBSV", "Arv", "SBKP", "2026-12-02T02:10:00Z", ["Chuva", "Possibilidade de pista molhada"],
         ["2026-12-02T02:00:00Z"]),
        ("AZU4787", "SBBE", "Dep", "SBCF", "2026-12-03T20:40:00Z", ["Chuva forte", "Possibilidade de pista molhada"],
         ["2026-12-03T21:00:00Z"]),
        ("AZU4787", "SBBE", "Dep", "SBCF", "2026-12-05T20:40:00Z", ["Chuva"], ["2026-12-05T19:00:00Z"]),
    ]

    again = client.post("/api/flights/impact", content=MARKET.encode(), headers={"x-filename": "mc.csv"}).json()
    assert again["requests"] == 0 and len(calls) == 2  # tudo do cache


def test_merge_condicoes_da_janela():
    from impact import _merge
    found = [({}, [["rain", "Chuva"]]), ({}, [["heavy", "Chuva forte"], ["wet", "Possibilidade de pista molhada"]])]
    assert [t[1] for t in _merge(found)] == ["Chuva forte", "Possibilidade de pista molhada"]


def test_janela_d7_a_d15():
    now = datetime(2026, 11, 16, 13, 30, tzinfo=UTC)
    start, end = flights.window(now=now)
    assert start == datetime(2026, 11, 23, tzinfo=UTC)        # D+7 00:00
    assert end == datetime(2026, 12, 1, 13, tzinfo=UTC)       # fim da previsao (agora + 360h) antes do fim de D+15


def test_preview_so_d7_a_d15(monkeypatch):
    monkeypatch.setattr(app_module, "build_payload", flights.build_payload)  # janela real
    r = client.post("/api/flights/preview", content=MARKET.encode(), headers={"x-filename": "mc.csv"}).json()
    start, end = flights.window()
    assert r["window"] == {"from": flights.iso(start), "to": flights.iso(end)}
    assert all(start <= datetime.fromisoformat(f["std"].replace("Z", "+00:00")) < end
               or start <= datetime.fromisoformat(f["sta"].replace("Z", "+00:00")) < end for f in r["flights"])


def test_relatorio_pdf(monkeypatch):
    async def fake_fetch(location, fields):
        if location == app_module.BELEM:
            return hourly("2026-12-01T00:00:00Z", {"2026-12-03T21:00:00Z": 12})
        return hourly("2026-12-01T00:00:00Z", {})
    monkeypatch.setattr(app_module, "fetch_tomorrow_timelines", fake_fetch)
    r = client.post("/api/flights/report.pdf", content=MARKET.encode(),
                    headers={"x-filename": "Market%20Constraints.csv"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert 'filename="voos-impactados-20261201.pdf"' in r.headers["content-disposition"]


def test_chuva_leve():
    from impact import _merge, conditions
    label = lambda i: [t[1] for t in conditions({"rain_intensity": i})]
    assert label(0.05) == []
    assert label(0.4) == ["Chuvisco"]
    assert label(0.5) == ["Chuva leve"]
    assert label(2.59) == ["Chuva leve"]
    assert label(2.6) == ["Chuva"]
    assert label(3.5) == ["Chuva", "Possibilidade de pista molhada"]
    found = [({}, [["light", "Chuva leve"]]), ({}, [["rain", "Chuva"]])]
    assert [t[1] for t in _merge(found)] == ["Chuva"]


def test_chuvisco_nao_impacta_voo():
    from impact import impacted
    t = datetime(2026, 12, 2, 10, 0, tzinfo=timezone.utc)
    f = [{"flight": "AZU1", "dep": "SBBE", "arr": "SBKP", "std": t, "sta": t + timedelta(hours=3)}]
    fc = {"SBBE": [{"time": "2026-12-02T10:00:00Z", "rain_intensity": 0.3, "precipitation_probability": 40}]}
    assert impacted(f, fc) == []
    fc["SBBE"][0]["rain_intensity"] = 0.6
    assert [x["tags"] for x in impacted(f, fc)] == [[["light", "Chuva leve"]]]
