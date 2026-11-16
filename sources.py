"""Chamada à Tomorrow.io. Devolve o JSON bruto; a extração fica em extract.py.

Atenção: a API tem limite de requests — cada consulta no frontend gasta uma.
"""
import os

import httpx

TOMORROW_TIMELINES_URL = "https://api.tomorrow.io/v4/timelines"
TIMESTEP = "1h"
END_TIME = "nowPlus360h"  # 15 dias de previsão horária


async def fetch_tomorrow_timelines(location: str, fields: list[str]) -> dict:
    """location = ID de uma location cadastrada na Tomorrow.io (ou "lat,lon")."""
    api_key = os.getenv("TOMORROW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TOMORROW_API_KEY não configurada no .env")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOMORROW_TIMELINES_URL,
            params={"apikey": api_key},
            json={
                "location": location,
                "fields": fields,
                "units": "metric",
                "timesteps": [TIMESTEP],
                "startTime": "now",
                "endTime": END_TIME,
            },
            headers={"accept": "application/json", "accept-encoding": "deflate, gzip, br"},
        )
    resp.raise_for_status()
    return resp.json()

