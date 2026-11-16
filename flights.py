"""Malha (.csv ou .xlsx) -> voos datados -> registros do Flight Schedule da Tomorrow.io.

Formatos aceitos (uma linha por periodo de operacao; o cabecalho e procurado nas primeiras linhas):
  - Market Constraints (padrao): titulo e "Schedule: ..., UTC, ..." antes do cabecalho, rodape "Page 1"
        Aln | Flt Nr | Dep | Arv | ... | Eqp | DepTm | ArvTm | ... | EffDt | DisDt | Freq
    o mesmo voo pode vir em mais de uma linha (restricao de partida e de chegada): fica um so
  - Exportacao SSIM: Flt Desg | Eff Date | Dis Date | Freq | Dept Arp | Dept Time | Arvl Arp | Arrv Time | Subfleet | Block Time
Freq: 1=seg ... 7=dom ("1234567", ".2.4567"). Aeroportos em IATA (ou ICAO).
Horarios: UTC ou local; vem do preambulo ("UTC"/"Local") ou do Block Time (STA - STD = block -> UTC).

Uso offline (nao chama a API, so mostra o que seria enviado):
    python flights.py malha.xlsx [--days 15] [-o voos.json]
"""
import csv
import io
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
# janela analisada: de D+FIRST_DAY (00:00 UTC) ate o fim de D+LAST_DAY, limitada ao alcance da previsao
FIRST_DAY, LAST_DAY = 7, 15
FORECAST_HOURS = 360
# False: cada voo da malha e avaliado pelo HORARIO em todos os dias da janela (EffDt/DisDt/Freq ignorados);
# True: so nos dias em que opera pelo periodo e frequencia da malha
USE_SCHEDULE_DATES = False
AIRLINE_ICAO = "AZU"
AIRLINES_ICAO = {"AD": "AZU"}  # coluna Aln (IATA) -> ICAO; as que nao estao aqui ficam como vieram
# Subfleet da malha -> tipo ICAO; os que nao estao aqui vao sem aircraftType (campo opcional)
AIRCRAFT_ICAO = {
    "295": "E295", "E95": "E195", "AT9": "AT76",
    "32A": "A320", "32N": "A20N", "32Q": "A21N",
    "332": "A332", "339": "A339",
}
AIRPORTS_FILE = Path(__file__).parent / "data" / "airports.csv"

# nomes aceitos no cabecalho (normalizados: minusculo, so letras/numeros/_)
COLUMNS = {
    "airline": ["aln", "airline", "cia"],
    "flight": ["flt_nr", "flt_desg", "flight", "voo"],
    "start": ["effdt", "eff_date", "start", "inicio"],
    "end": ["disdt", "dis_date", "end", "fim"],
    "freq": ["freq", "frequency", "frequencia"],
    "origin": ["dep", "dept_arp", "origin", "origem"],
    "std": ["deptm", "dept_time", "std"],
    "destination": ["arv", "arvl_arp", "destination", "destino"],
    "sta": ["arvtm", "arrv_time", "sta"],
    "aircraft": ["eqp", "subfleet", "aircraft", "aeronave"],
    "block": ["block_time", "block"],
}


class ScheduleError(ValueError):
    pass


# ---------- leitura do arquivo ----------

def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y") if v.time() == time(0) else v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, timedelta):
        m = int(v.total_seconds() // 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_rows(data: bytes, filename: str) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:  # zip/xml invalido
            raise ScheduleError(f"Nao consegui abrir o .xlsx: {e}")
        rows = [[_cell(c) for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
        wb.close()
        return rows
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    lines = text.splitlines()
    if not lines:
        return []
    delim = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    return [list(r) for r in csv.reader(lines, delimiter=delim)]


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


REQUIRED = ("flight", "start", "end", "origin", "std", "destination", "sta")


def map_columns(header: list[str]) -> dict[str, int]:
    keys = [_key(h) for h in header]
    cols = {f: keys.index(a) for f, aliases in COLUMNS.items() for a in reversed(aliases) if a in keys}
    missing = [f for f in REQUIRED if f not in cols]
    if missing:
        raise ScheduleError(f"Colunas obrigatorias ausentes: {', '.join(missing)}. Cabecalho lido: {header}")
    return cols


def find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Primeira linha (entre as 15 primeiras) que tem todas as colunas obrigatorias."""
    for i, row in enumerate(rows[:15]):
        try:
            return i, map_columns(row)
        except ScheduleError:
            pass
    return 0, map_columns(rows[0])  # erro com o cabecalho da 1a linha


def basis_from_preamble(preamble: list[list[str]]) -> bool | None:
    """'Schedule: ..., UTC, ...' -> True; ', Local' -> False; nada -> None."""
    text = " ".join(c for r in preamble for c in r).upper()
    if re.search(r"\bUTC\b|\bGMT\b", text):
        return True
    if re.search(r"\bLOCAL\b|\bLT\b", text):
        return False
    return None


# ---------- valores ----------

def parse_date(v: str) -> date:
    v = re.sub(r"[ T]\d{2}:\d{2}(:\d{2})?$", "", v.strip())
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d%b%y", "%d%b%Y"):
        try:
            return datetime.strptime(v.upper() if "%b" in fmt else v, fmt).date()
        except ValueError:
            pass
    raise ScheduleError(f"data invalida '{v}'")


def parse_time(v: str) -> tuple[time, int]:
    """HH:MM / HHMM, com sufixo opcional +1 -> (hora, dias a mais)."""
    v = v.strip()
    extra = 0
    m = re.search(r"\+\s*(\d)$", v)
    if m:
        extra, v = int(m.group(1)), v[: m.start()].strip()
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})(?::\d{2})?", v)
    if not m:
        raise ScheduleError(f"horario invalido '{v}'")
    h, mi = int(m.group(1)), int(m.group(2))
    return (time(0, 0), extra + 1) if (h, mi) == (24, 0) else (time(h, mi), extra)


def parse_freq(v: str) -> set[int]:
    """'1234567' / '.2.4567' -> weekday() (0 = segunda). Vazio = todos os dias."""
    v = v.strip()
    if not v:
        return set(range(7))
    if len(v) == 7 and not v.isdigit():
        return {i for i, ch in enumerate(v) if ch.isdigit() and ch != "0"}
    days = {int(ch) - 1 for ch in v if ch in "1234567"}
    if not days:
        raise ScheduleError(f"frequencia invalida '{v}'")
    return days


def load_airports(path: Path = AIRPORTS_FILE) -> dict[str, dict]:
    """IATA e ICAO -> {icao, tz}."""
    table = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ap = {"icao": r["icao"].strip().upper(), "tz": r.get("tz") or "America/Sao_Paulo"}
            table[r["iata"].strip().upper()] = ap
            table[ap["icao"]] = ap
    return table


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def detect_utc(body: list[list[str]], cols: dict[str, int]) -> bool:
    """STA - STD == block time na maioria das linhas -> horarios em UTC. Sem block time: UTC."""
    if "block" not in cols:
        return True
    hits = total = 0
    for row in body[:500]:
        try:
            std, sta, blk = (parse_time(row[cols[k]])[0] for k in ("std", "sta", "block"))
        except (ScheduleError, IndexError):
            continue
        total += 1
        hits += (_minutes(sta) - _minutes(std)) % 1440 == _minutes(blk)
    return total < 10 or hits / total >= 0.8


# ---------- malha -> voos ----------

def load_flights(rows: list[list[str]], start: datetime, end: datetime, airports: dict | None = None,
                 use_dates: bool = USE_SCHEDULE_DATES):
    """Voos com partida ou chegada (UTC) em [start, end). Devolve (voos, avisos, base de horario).
    use_dates=False: o horario de cada voo e repetido em todos os dias da janela."""
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        raise ScheduleError("Malha vazia.")
    h, cols = find_header(rows)
    body = rows[h + 1:]
    airports = airports or load_airports()
    utc = basis_from_preamble(rows[:h])
    if utc is None:
        utc = detect_utc(body, cols)

    def get(row, f):
        i = cols.get(f)
        return row[i].strip() if i is not None and i < len(row) else ""

    flights, errors, unknown, seen = [], [], set(), set()
    for lineno, row in enumerate(body, start=h + 2):
        if not get(row, "flight") or not get(row, "origin"):
            continue  # rodape ("16Nov2026 ... Page 1") e linhas sem voo
        try:
            d0, d1 = parse_date(get(row, "start")), parse_date(get(row, "end"))
            freq = parse_freq(get(row, "freq"))
            std, std_extra = parse_time(get(row, "std"))
            sta, sta_extra = parse_time(get(row, "sta"))
        except ScheduleError as e:
            errors.append(f"linha {lineno}: {e}")
            continue
        dep, arr = airports.get(get(row, "origin").upper()), airports.get(get(row, "destination").upper())
        if not dep or not arr:
            unknown |= {c for c, ap in ((get(row, "origin"), dep), (get(row, "destination"), arr)) if not ap}
            continue
        # dias que podem cair na janela (com 1 dia de folga por causa do fuso)
        first, last = start.date() - timedelta(days=1), end.date() + timedelta(days=1)
        if use_dates:
            first, last = max(d0, first), min(d1, last)
        for n in range((last - first).days + 1):
            d = first + timedelta(days=n)
            if use_dates and d.weekday() not in freq:
                continue
            std_dt = datetime.combine(d + timedelta(days=std_extra), std)
            sta_dt = datetime.combine(d + timedelta(days=sta_extra), sta)
            if utc:
                std_dt, sta_dt = std_dt.replace(tzinfo=UTC), sta_dt.replace(tzinfo=UTC)
            else:
                std_dt = std_dt.replace(tzinfo=ZoneInfo(dep["tz"])).astimezone(UTC)
                sta_dt = sta_dt.replace(tzinfo=ZoneInfo(arr["tz"])).astimezone(UTC)
            if sta_dt <= std_dt and not sta_extra:
                sta_dt += timedelta(days=1)  # chega no dia seguinte
            if not (start <= std_dt < end or start <= sta_dt < end):
                continue  # entra se a partida ou a chegada cai na janela (Dep e Arv sao analisados)
            number = re.sub(r"\s+", "", get(row, "flight"))
            aln = get(row, "airline").upper()
            if aln and number.isdigit():
                number = aln + number  # Aln "AD" + Flt Nr "4787"
            m = re.match(r"([A-Z0-9]{2})(?=\d+$)", number)
            if m and m.group(1) in AIRLINES_ICAO:
                number = AIRLINES_ICAO[m.group(1)] + number[2:]  # AD2002 -> AZU2002
            sub = re.sub(r"^AD\s*", "", get(row, "aircraft"))
            key = (number, d, dep["icao"], arr["icao"], std_dt, sta_dt)
            if key in seen:
                continue  # mesmo voo e horario em outra linha (restricao de partida e de chegada)
            seen.add(key)
            flights.append({
                "flight": number, "date": d, "dep": dep["icao"], "arr": arr["icao"],
                "std": std_dt, "sta": sta_dt, "aircraft": AIRCRAFT_ICAO.get(sub),
            })
    warnings = errors[:20]
    if len(errors) > 20:
        warnings.append(f"... e mais {len(errors) - 20} linhas com erro")
    if unknown:
        warnings.append(f"Aeroportos fora de data/airports.csv (voos ignorados): {', '.join(sorted(unknown))}")
    flights.sort(key=lambda f: (f["std"], f["flight"]))
    return flights, warnings, "UTC" if utc else "local"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_tomorrow(f: dict, now: datetime) -> dict:
    """Um voo no formato do POST /v4/connect/flight/schedule."""
    ext_id = f"{f['flight']}-{f['date']:%Y%m%d}-{f['dep']}-{f['arr']}"
    fields = {
        "globalUniqueFlightIdentifier": ext_id,
        "flightNumber": f["flight"],
        "airline": AIRLINE_ICAO,
        "departureAirportIcao": f["dep"],
        "arrivalAirportIcao": f["arr"],
        "originalEstimatedDepartureTime": iso(f["std"]),
        "originalEstimatedArrivalTime": iso(f["sta"]),
        "status": "scheduled",
        "updateTime": iso(now),
    }
    if f["aircraft"]:
        fields["aircraftType"] = f["aircraft"]
    return {"title": f"Voo {f['flight']}", "external_id": ext_id, "timestamp": iso(now), "fields": fields}


def window(first_day: int = FIRST_DAY, last_day: int = LAST_DAY,
           now: datetime | None = None) -> tuple[datetime, datetime]:
    """De D+first_day 00:00 UTC ate o fim de D+last_day, sem passar do fim da previsao (agora + 360h)."""
    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    forecast_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=FORECAST_HOURS)
    return today + timedelta(days=first_day), min(today + timedelta(days=last_day + 1), forecast_end)


def build_payload(data: bytes, filename: str, first_day: int = FIRST_DAY, last_day: int = LAST_DAY,
                  now: datetime | None = None, use_dates: bool = USE_SCHEDULE_DATES) -> dict:
    now = now or datetime.now(UTC)
    start, end = window(first_day, last_day, now)
    flights, warnings, basis = load_flights(read_rows(data, filename), start, end, use_dates=use_dates)
    return {
        "records": [to_tomorrow(f, now) for f in flights],
        "flights": flights,
        "warnings": warnings,
        "basis": basis,
        "window": {"from": iso(start), "to": iso(end)},
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Converte a malha no payload do Flight Schedule (nao envia nada).")
    p.add_argument("malha")
    p.add_argument("--from-day", type=int, default=FIRST_DAY, help="primeiro dia (D+N), padrao 7")
    p.add_argument("--to-day", type=int, default=LAST_DAY, help="ultimo dia (D+N), padrao 15")
    p.add_argument("-o", "--output", help="grava os registros em JSON")
    a = p.parse_args()
    out = build_payload(Path(a.malha).read_bytes(), a.malha, a.from_day, a.to_day)
    print(f"{len(out['records'])} voos entre {out['window']['from']} e {out['window']['to']} (horarios em {out['basis']})",
          file=sys.stderr)
    for w in out["warnings"]:
        print("aviso:", w, file=sys.stderr)
    text = json.dumps(out["records"], indent=2, ensure_ascii=False)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
    else:
        print(text)
