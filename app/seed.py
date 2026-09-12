"""Semeia o histórico com dados reais de mercado, para os gráficos já nascerem cheios.

Uso:  python -m app.seed [dias]
"""
from __future__ import annotations

import sys
import time

from sqlalchemy import delete, select

from .config import settings
from .models import MetricPoint, get_session, init_db, log_event
from .services import fetch_json


def seed_crypto(days: int = 7) -> int:
    """Importa o gráfico de mercado da CoinGecko para cada moeda acompanhada."""
    total = 0
    for coin in settings.coins:
        try:
            raw = fetch_json(
                f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart",
                params={"vs_currency": "usd", "days": days, "interval": "hourly"},
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {coin}: {exc}")
            continue

        series = f"crypto.{coin}"
        points = raw.get("prices", [])
        with get_session() as s:
            # remove o que já houver dessa faixa para não duplicar ao rodar de novo
            oldest = min((p[0] / 1000 for p in points), default=time.time())
            s.execute(
                delete(MetricPoint).where(
                    MetricPoint.series == series, MetricPoint.recorded_at >= oldest
                )
            )
            for ts_ms, price in points:
                s.add(
                    MetricPoint(series=series, value=float(price), recorded_at=ts_ms / 1000)
                )
            s.commit()
        total += len(points)
        print(f"  + {series}: {len(points)} pontos")
        time.sleep(1.2)  # respeita o limite de requisições da API pública
    return total


def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    init_db()
    print(f"Semeando histórico de {days} dias…")
    n = seed_crypto(days)
    log_event("INFO", "seed", f"histórico semeado com {n} pontos")

    with get_session() as s:
        rows = s.execute(
            select(MetricPoint.series, MetricPoint.value).order_by(MetricPoint.id.desc()).limit(1)
        ).first()
    print(f"\nTotal: {n} pontos gravados. Último: {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
