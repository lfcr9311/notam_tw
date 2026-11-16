"""PDF das condicoes previstas nas bases e dos voos afetados (horarios em UTC)."""
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.fonts import FontFace

UTC = timezone.utc
ACCENT = (10, 78, 162)
HEAD_BG = (238, 241, 245)
RAIN_BG = (233, 241, 252)


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC)


def _day(iso: str) -> str:
    return _dt(iso).strftime("%d/%m/%Y")


def _hour(iso: str) -> str:
    return _dt(iso).strftime("%H:%M")


def _tags(tags: list[list[str]]) -> str:
    return " + ".join(t[1] for t in tags)


def _pct(v) -> str:
    return "-" if v is None else f"{round(v)} %"


class _Doc(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", size=8)
        self.set_text_color(123, 133, 148)
        self.cell(0, 6, f"NOTAM TW · página {self.page_no()}/{{nb}}", align="R")


def build_pdf(*, impacted: list[dict], bases: list[dict], window: dict, filename: str,
              generated: datetime | None = None) -> bytes:
    """impacted: impact.impacted(); bases: [{name, icao, hourly}] (hourly com "tags");
    window: {"from", "to"} ISO UTC."""
    generated = generated or datetime.now(UTC)
    start, end = _dt(window["from"]), _dt(window["to"])
    pdf = _Doc(orientation="L", format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(15, 23, 32)
    pdf.cell(0, 9, "Voos impactados por chuva", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    pdf.set_text_color(74, 85, 99)
    for line in (
        f"Período: {start:%d/%m/%Y %H:%M} a {end:%d/%m/%Y %H:%M} UTC (D+7 a D+15) · "
        f"bases: {', '.join(f'{b['name']} ({b['icao']})' for b in bases)}",
        f"Malha: {filename} · gerado em {generated:%d/%m/%Y %H:%M} UTC · horários em UTC",
        "Critério: horário do voo (Dep = partida, Arv = chegada na base), 1h antes ou 1h depois, com chuva "
        "(>= 2,6 mm/h), chuva forte (>= 10 mm/h) ou possibilidade de pista molhada (> 3 mm/h).",
    ):
        pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    def title(text: str):
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(*ACCENT)
        pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(15, 23, 32)

    def table(headers: list[str], rows: list[list[str]], widths: tuple, shade: list[bool] | None = None):
        pdf.set_font("helvetica", size=8.5)
        heading = FontFace(emphasis="BOLD", color=(74, 85, 99), fill_color=HEAD_BG)
        with pdf.table(col_widths=widths, headings_style=heading, line_height=5.5,
                       borders_layout="HORIZONTAL_LINES", text_align="LEFT") as t:
            t.row(headers)
            for i, r in enumerate(rows):
                style = FontFace(fill_color=RAIN_BG) if shade and shade[i] else None
                t.row(r, style=style)

    # 1. voos afetados
    title(f"Voos afetados ({len(impacted)})")
    if impacted:
        table(["Data", "Horário", "Voo", "Base", "Dep / Arv", "Condições", "Chuva às", "Prob."],
              [[_day(x["time"]), _hour(x["time"]), x["flight"], x["airport"],
                f"{x['leg']} {'->' if x['leg'] == 'Dep' else '<-'} {x['other']}", _tags(x["tags"]),
                ", ".join(_hour(h) for h in x["hours"]), _pct(x["precipitation_probability"])]
               for x in impacted],
              (22, 16, 20, 16, 30, 82, 30, 16),
              [(x["rain_intensity"] or 0) >= 2.6 for x in impacted])
    else:
        pdf.set_font("helvetica", size=9)
        pdf.cell(0, 6, "Nenhum voo parte ou chega nas bases em horário com chuva ou pista molhada.",
                 new_x="LMARGIN", new_y="NEXT")

    # 2. condicoes previstas em cada base no periodo
    for b in bases:
        hours = [h for h in b["hourly"] if h["tags"] and start <= _dt(h["time"]) < end]
        title(f"Condições previstas · {b['name']} ({b['icao']})")
        if not hours:
            pdf.set_font("helvetica", size=9)
            pdf.cell(0, 6, "Nenhum horário com chuva ou pista molhada no período.", new_x="LMARGIN", new_y="NEXT")
            continue
        table(["Data", "Horário", "Condições", "Prob. precipitação"],
              [[_day(h["time"]), _hour(h["time"]), _tags(h["tags"]), _pct(h["precipitation_probability"])]
               for h in hours],
              (30, 22, 120, 40),
              [(h.get("rain_intensity") or 0) >= 2.6 for h in hours])

    return bytes(pdf.output())
