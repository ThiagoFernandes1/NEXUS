"""Configuração central da aplicação NEXUS."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass(frozen=True)
class Settings:
    """Configurações carregadas de variáveis de ambiente com defaults sensatos."""

    secret_key: str = os.getenv("NEXUS_SECRET", "nexus-dev-secret-change-me")
    database_url: str = os.getenv("NEXUS_DB", f"sqlite:///{DATA_DIR / 'nexus.db'}")
    host: str = os.getenv("NEXUS_HOST", "127.0.0.1")
    port: int = int(os.getenv("NEXUS_PORT", "5000"))
    debug: bool = os.getenv("NEXUS_DEBUG", "0") == "1"

    # Tempo de vida do cache por serviço (segundos)
    cache_ttl: dict[str, int] = field(
        default_factory=lambda: {
            "crypto": 60,
            "weather": 600,
            "space": 900,
            "forex": 120,
            "iss": 5,
        }
    )

    http_timeout: float = 12.0
    http_retries: int = 3

    # Cidade padrão do painel de clima
    default_city: str = os.getenv("NEXUS_CITY", "São Paulo")
    default_lat: float = float(os.getenv("NEXUS_LAT", "-23.5505"))
    default_lon: float = float(os.getenv("NEXUS_LON", "-46.6333"))

    # Moedas acompanhadas
    coins: tuple[str, ...] = ("bitcoin", "ethereum", "solana", "cardano", "dogecoin")
    fx_pairs: tuple[str, ...] = ("USD-BRL", "EUR-BRL", "GBP-BRL", "BTC-BRL")


settings = Settings()
