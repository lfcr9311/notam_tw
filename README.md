# NOTAM TW · PoC

Extrai temperatura, intensidade de chuva e probabilidade de precipitação
da previsão horária da Tomorrow.io (`POST /v4/timelines`, passo de 1h, de `now` até `nowPlus360h`).
A API tem limite de requests: cada clique em **Consultar API** gasta uma.

## Rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # coloque sua TOMORROW_API_KEY
uvicorn app:app --reload        # abra http://localhost:8000
```

Para não gastar request, cole um JSON já salvo na página ou rode:

```bash
python extract.py resposta.json
```

Aceita a resposta de `/v4/timelines` (`data.timelines[].intervals`) ou de `/v4/weather/forecast`, só a lista de horas, ou um trecho copiado dela (`{...}, {...},`).

## Estrutura

- `sources.py`: a request à Tomorrow.io (`/v4/timelines`, campos = valores de `FIELDS`)
- `extract.py`: parse do JSON e seleção dos campos (`FIELDS`)
- `app.py`: IDs das bases em `LOCATIONS` (Salvador, Belém), cache da previsão, `GET /api/forecast?location=<ID>` (faz a request pelo ID), `POST /api/extract` (JSON colado) + serve o frontend
- `flights.py`: malha (Market Constraints / SSIM) → voos datados em UTC
- `impact.py`: critérios de chuva/pista molhada e junção voos × previsão
- `static/index.html`: frontend (select das bases + tabela, upload da malha)

## Voos impactados por chuva

Bases cadastradas (`LOCATIONS` em `app.py`): **Salvador (SBSV)** e **Belém (SBBE)**.

1. A seção **Voos impactados por chuva** recebe a malha enviada pelo usuário: CSV do **Market Constraints**
   (padrão; título/preâmbulo antes do cabeçalho, horários em UTC, voo repetido nas linhas de partida e chegada
   vira um só) ou `.xlsx` SSIM. A prévia não chama a API.
2. **Verificar chuva** pega a previsão de 360h de cada base que aparece na malha (1 request por base) e cruza
   em memória: voo impactado = partida ou chegada na base dentro de uma hora com chuva (≥ 2,6 mm/h),
   chuva forte (≥ 10) ou possibilidade de pista molhada (> 3) — critérios em `impact.py`.
3. A previsão de cada base fica em memória por `FORECAST_CACHE_MIN` minutos (padrão 60), compartilhada com
   **Consultar API**: repetir a verificação ou consultar a base de novo nesse intervalo não gasta request.

- IATA → ICAO: `data/airports.csv`; `AD` + `4787` → `AZU4787`
- Offline: `python flights.py malha.csv --days 15 -o voos.json`

## Testes e deploy

```bash
pip install pytest && python -m pytest -q   # mockado, não gasta request da Tomorrow.io
```

Push na `main` → GitHub Actions testa e faz deploy no EC2 (Docker, atrás do Caddy em `/weather/`). Setup: [deploy/README.md](deploy/README.md).
