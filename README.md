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
- `app.py`: IDs das bases em `LOCATIONS` (Salvador, Belém, Fernando de Noronha, Cascavel), `GET /api/forecast?location=<ID>` (faz a request pelo ID), `POST /api/extract` (JSON colado) + serve o frontend
- `static/index.html`: frontend (select das bases + tabela)

## Testes e deploy

```bash
pip install pytest && python -m pytest -q   # mockado, não gasta request da Tomorrow.io
```

Push na `main` → GitHub Actions testa e faz deploy no EC2 (Docker, atrás do Caddy em `/weather/`). Setup: [deploy/README.md](deploy/README.md).
