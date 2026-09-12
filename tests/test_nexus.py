"""Suíte de testes do NEXUS.

As chamadas externas são simuladas (monkeypatch), então a suíte roda offline
e não depende de rede nem de limites de requisição das APIs públicas.
"""
from __future__ import annotations

import time

import pytest

from app import models, services
from app.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App Flask apontando para um banco temporário e isolado."""
    engine_url = f"sqlite:///{tmp_path / 'test.db'}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(engine_url, future=True)
    monkeypatch.setattr(models, "_engine", engine, raising=False)
    monkeypatch.setattr(
        models, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True)
    )
    models.Base.metadata.create_all(engine)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- Cache ------------------------------------------------------------------

def test_cache_roundtrip(client):
    services.cache_put("t:demo", {"a": 1}, ttl=60)
    hit = services.cache_get("t:demo")
    assert hit is not None
    payload, age = hit
    assert payload == {"a": 1}
    assert age < 5


def test_cache_expires(client):
    services.cache_put("t:exp", {"v": 1}, ttl=-1)
    assert services.cache_get("t:exp") is None
    # mas continua acessível como dado obsoleto
    assert services.cache_get("t:exp", allow_stale=True)[0] == {"v": 1}


def test_cached_uses_loader_once(client):
    calls = []

    def loader():
        calls.append(1)
        return {"n": len(calls)}

    a = services.cached("crypto", loader)
    b = services.cached("crypto", loader)
    assert a["cached"] is False and b["cached"] is True
    assert len(calls) == 1, "o segundo acesso deveria vir do cache"


def test_cached_falls_back_to_stale(client):
    services.cache_put("svc:forex", {"old": True}, ttl=-1)

    def broken():
        raise services.ServiceError("api fora do ar")

    out = services.cached("forex", broken)
    assert out["ok"] is True
    assert out["stale"] is True
    assert out["data"] == {"old": True}


def test_cached_reports_error_without_cache(client):
    def broken():
        raise services.ServiceError("sem rede")

    out = services.cached("space", broken)
    assert out["ok"] is False
    assert "sem rede" in out["error"]


# --- Retry ------------------------------------------------------------------

def test_fetch_json_retries(monkeypatch, client):
    attempts = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def flaky(url, params=None):
        attempts.append(url)
        if len(attempts) < 3:
            raise RuntimeError("timeout")
        return FakeResponse()

    monkeypatch.setattr(services._CLIENT, "get", flaky)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    assert services.fetch_json("http://x") == {"ok": True}
    assert len(attempts) == 3


def test_fetch_json_gives_up(monkeypatch, client):
    monkeypatch.setattr(
        services._CLIENT, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    with pytest.raises(services.ServiceError):
        services.fetch_json("http://x")


# --- Banco ------------------------------------------------------------------

def test_metrics_history_order(client):
    for v in (1.0, 2.0, 3.0):
        models.record_metric("s.test", v)
    pts = models.history("s.test")
    assert [p["value"] for p in pts] == [1.0, 2.0, 3.0], "deve vir em ordem cronológica"


def test_events(client):
    models.log_event("INFO", "teste", "olá")
    evs = models.recent_events()
    assert evs[0]["message"] == "olá"


def test_prune_removes_old(client):
    with models.get_session() as s:
        s.add(models.MetricPoint(series="velho", value=1, recorded_at=time.time() - 10**7))
        s.commit()
    assert models.prune() >= 1
    assert models.history("velho") == []


# --- Rotas HTTP -------------------------------------------------------------

def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"NEXUS" in r.data


def test_health(client, monkeypatch):
    monkeypatch.setattr(
        services, "snapshot", lambda names=None: {"meta": {"healthy": 5, "total": 5, "elapsed_ms": 1.0}}
    )
    j = client.get("/api/health").get_json()
    assert j["ok"] is True and j["version"] == "1.0.0"


def test_unknown_service_404(client):
    r = client.get("/api/service/inexistente")
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_weather_requires_coords(client):
    assert client.get("/api/weather").status_code == 400
    assert client.get("/api/weather?lat=abc&lon=1").status_code == 400


def test_geocode_short_query_returns_empty(client):
    j = client.get("/api/geocode?q=a").get_json()
    assert j["data"] == []


def test_history_endpoint(client):
    models.record_metric("crypto.bitcoin", 50000.0)
    j = client.get("/api/history/crypto.bitcoin").get_json()
    assert j["ok"] and len(j["points"]) == 1


# --- Transformação de dados -------------------------------------------------

def test_load_crypto_shape(monkeypatch, client):
    monkeypatch.setattr(
        services,
        "fetch_json",
        lambda url, params=None: {
            "bitcoin": {"usd": 100.0, "brl": 500.0, "usd_24h_change": -2.345},
        },
    )
    out = services.load_crypto()
    coin = out["coins"][0]
    assert coin["symbol"] == "BTC"
    assert coin["change_24h"] == -2.35
    assert coin["trend"] == "down"


def test_load_weather_maps_code(monkeypatch, client):
    monkeypatch.setattr(
        services,
        "fetch_json",
        lambda url, params=None: {
            "current": {"temperature_2m": 20.0, "weather_code": 95, "relative_humidity_2m": 80},
            "daily": {"time": ["2026-01-01"], "temperature_2m_max": [30.0],
                      "temperature_2m_min": [20.0], "weather_code": [0]},
            "hourly": {"time": ["2026-01-01T00:00"], "temperature_2m": [21.0]},
        },
    )
    out = services.load_weather(1.0, 2.0, "Teste")
    assert out["label"] == "Tempestade"
    assert out["city"] == "Teste"
    assert len(out["forecast"]) == 1


def test_snapshot_counts_health(monkeypatch, client):
    monkeypatch.setattr(
        services, "cached", lambda name, loader: {"ok": name != "iss", "data": {}}
    )
    snap = services.snapshot()
    assert snap["meta"]["total"] == 5
    assert snap["meta"]["healthy"] == 4
