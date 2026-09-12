"""Conectores de API externos com cache persistente, retry e degradação suave."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from .config import settings
from .models import CacheEntry, get_session, log_event, record_metric

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="nexus-api")

_CLIENT = httpx.Client(
    timeout=settings.http_timeout,
    follow_redirects=True,
    headers={"User-Agent": "NexusDashboard/1.0 (+https://localhost)"},
)


class ServiceError(RuntimeError):
    """Falha irrecuperável ao consultar um serviço externo."""


# --- Cache ------------------------------------------------------------------

def cache_get(key: str, *, allow_stale: bool = False) -> tuple[Any, float] | None:
    """Retorna (payload, idade_em_segundos) ou None."""
    with get_session() as s:
        entry = s.get(CacheEntry, key)
        if entry is None:
            return None
        if entry.is_fresh or allow_stale:
            return entry.decode(), entry.age_seconds
    return None


def cache_put(key: str, payload: Any, ttl: int) -> None:
    now = time.time()
    blob = json.dumps(payload, ensure_ascii=False)
    with get_session() as s:
        entry = s.get(CacheEntry, key)
        if entry is None:
            entry = CacheEntry(key=key, payload=blob, expires_at=now + ttl, fetched_at=now)
            s.add(entry)
        else:
            entry.payload, entry.expires_at, entry.fetched_at = blob, now + ttl, now
        s.commit()


def fetch_json(url: str, *, params: dict | None = None) -> Any:
    """GET com retry e backoff exponencial."""
    last: Exception | None = None
    for attempt in range(settings.http_retries):
        try:
            r = _CLIENT.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - capturamos tudo para poder repetir
            last = exc
            if attempt < settings.http_retries - 1:
                time.sleep(0.4 * (2 ** attempt))
    raise ServiceError(f"{url}: {type(last).__name__}: {last}") from last


def cached(name: str, loader: Callable[[], Any]) -> dict[str, Any]:
    """Executa `loader` respeitando o cache; em falha, devolve dado obsoleto se houver."""
    ttl = settings.cache_ttl.get(name, 120)
    hit = cache_get(f"svc:{name}")
    if hit is not None:
        payload, age = hit
        return {"ok": True, "cached": True, "age": round(age, 1), "data": payload}

    try:
        data = loader()
        cache_put(f"svc:{name}", data, ttl)
        return {"ok": True, "cached": False, "age": 0.0, "data": data}
    except Exception as exc:  # noqa: BLE001
        log_event("ERROR", name, str(exc)[:300])
        stale = cache_get(f"svc:{name}", allow_stale=True)
        if stale is not None:
            payload, age = stale
            return {
                "ok": True,
                "cached": True,
                "stale": True,
                "age": round(age, 1),
                "data": payload,
                "warning": "dados obsoletos: serviço indisponível",
            }
        return {"ok": False, "error": str(exc)[:300], "data": None}


# --- Conectores -------------------------------------------------------------

WEATHER_CODES = {
    0: ("Céu limpo", "☀️"), 1: ("Predominantemente limpo", "🌤️"),
    2: ("Parcialmente nublado", "⛅"), 3: ("Encoberto", "☁️"),
    45: ("Nevoeiro", "🌫️"), 48: ("Nevoeiro com geada", "🌫️"),
    51: ("Garoa leve", "🌦️"), 53: ("Garoa", "🌦️"), 55: ("Garoa intensa", "🌧️"),
    61: ("Chuva fraca", "🌦️"), 63: ("Chuva", "🌧️"), 65: ("Chuva forte", "⛈️"),
    71: ("Neve fraca", "🌨️"), 73: ("Neve", "🌨️"), 75: ("Neve forte", "❄️"),
    80: ("Pancadas leves", "🌦️"), 81: ("Pancadas", "🌧️"), 82: ("Pancadas fortes", "⛈️"),
    95: ("Tempestade", "⛈️"), 96: ("Tempestade com granizo", "⛈️"),
    99: ("Tempestade severa", "⛈️"),
}

COIN_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "cardano": "ADA", "dogecoin": "DOGE",
}


def load_crypto() -> dict[str, Any]:
    ids = ",".join(settings.coins)
    raw = fetch_json(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": ids,
            "vs_currencies": "usd,brl",
            "include_24hr_change": "true",
            "include_market_cap": "true",
        },
    )
    coins = []
    for cid in settings.coins:
        d = raw.get(cid)
        if not d:
            continue
        change = d.get("usd_24h_change", 0.0) or 0.0
        coins.append(
            {
                "id": cid,
                "name": cid.capitalize(),
                "symbol": COIN_SYMBOLS.get(cid, cid[:4].upper()),
                "usd": d.get("usd", 0.0),
                "brl": d.get("brl", 0.0),
                "change_24h": round(change, 2),
                "market_cap": d.get("usd_market_cap", 0.0),
                "trend": "up" if change >= 0 else "down",
            }
        )
        record_metric(f"crypto.{cid}", d.get("usd", 0.0))
    return {"coins": coins, "updated": datetime.now(timezone.utc).isoformat()}


def load_weather(lat: float | None = None, lon: float | None = None,
                 city: str | None = None) -> dict[str, Any]:
    lat = settings.default_lat if lat is None else lat
    lon = settings.default_lon if lon is None else lon
    raw = fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "weather_code,wind_speed_10m,surface_pressure",
            "hourly": "temperature_2m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "forecast_days": 5,
            "timezone": "auto",
        },
    )
    cur = raw.get("current", {})
    code = int(cur.get("weather_code", 0))
    label, icon = WEATHER_CODES.get(code, ("Desconhecido", "🌡️"))
    record_metric("weather.temp", cur.get("temperature_2m", 0.0))

    daily = raw.get("daily", {})
    forecast = []
    for i, day in enumerate(daily.get("time", [])[:5]):
        dcode = int(daily.get("weather_code", [0])[i])
        dlabel, dicon = WEATHER_CODES.get(dcode, ("—", "🌡️"))
        forecast.append(
            {
                "date": day,
                "max": daily.get("temperature_2m_max", [])[i],
                "min": daily.get("temperature_2m_min", [])[i],
                "label": dlabel,
                "icon": dicon,
            }
        )

    hourly = raw.get("hourly", {})
    series = list(zip(hourly.get("time", [])[:24], hourly.get("temperature_2m", [])[:24]))

    return {
        "city": city or settings.default_city,
        "lat": lat,
        "lon": lon,
        "temperature": cur.get("temperature_2m"),
        "feels_like": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "pressure": cur.get("surface_pressure"),
        "label": label,
        "icon": icon,
        "forecast": forecast,
        "hourly": [{"t": t, "v": v} for t, v in series],
    }


def geocode(query: str) -> list[dict[str, Any]]:
    raw = fetch_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": query, "count": 5, "language": "pt", "format": "json"},
    )
    return [
        {
            "name": r["name"],
            "country": r.get("country", ""),
            "admin": r.get("admin1", ""),
            "lat": r["latitude"],
            "lon": r["longitude"],
        }
        for r in raw.get("results", [])
    ]


def load_space() -> dict[str, Any]:
    raw = fetch_json(
        "https://api.spaceflightnewsapi.net/v4/articles/",
        params={"limit": 8, "ordering": "-published_at"},
    )
    articles = [
        {
            "title": a["title"],
            "summary": (a.get("summary") or "")[:220],
            "url": a["url"],
            "image": a.get("image_url"),
            "site": a.get("news_site", "—"),
            "published": a.get("published_at"),
        }
        for a in raw.get("results", [])
    ]
    return {"articles": articles, "total": raw.get("count", 0)}


def load_forex() -> dict[str, Any]:
    pairs = ",".join(settings.fx_pairs)
    raw = fetch_json(f"https://economia.awesomeapi.com.br/json/last/{pairs}")
    rates = []
    for key, d in raw.items():
        pct = float(d.get("pctChange", 0) or 0)
        bid = float(d.get("bid", 0) or 0)
        rates.append(
            {
                "pair": f"{d['code']}/{d['codein']}",
                "name": d.get("name", key),
                "bid": bid,
                "high": float(d.get("high", 0) or 0),
                "low": float(d.get("low", 0) or 0),
                "pct_change": round(pct, 2),
                "trend": "up" if pct >= 0 else "down",
            }
        )
        record_metric(f"fx.{key}", bid)
    return {"rates": rates}


def load_iss() -> dict[str, Any]:
    raw = fetch_json("http://api.open-notify.org/iss-now.json")
    pos = raw["iss_position"]
    lat, lon = float(pos["latitude"]), float(pos["longitude"])
    record_metric("iss.lat", lat)
    return {"lat": lat, "lon": lon, "timestamp": raw["timestamp"]}


SERVICES: dict[str, Callable[[], Any]] = {
    "crypto": load_crypto,
    "weather": load_weather,
    "space": load_space,
    "forex": load_forex,
    "iss": load_iss,
}


def snapshot(names: list[str] | None = None) -> dict[str, Any]:
    """Busca vários serviços em paralelo e devolve um retrato consolidado."""
    names = names or list(SERVICES)
    started = time.perf_counter()
    futures = {n: _POOL.submit(cached, n, SERVICES[n]) for n in names if n in SERVICES}
    out = {n: f.result() for n, f in futures.items()}
    healthy = sum(1 for v in out.values() if v.get("ok"))
    return {
        "services": out,
        "meta": {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "healthy": healthy,
            "total": len(out),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
