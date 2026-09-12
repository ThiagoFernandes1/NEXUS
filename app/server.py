"""Aplicação Flask: API REST + streaming SSE em tempo real."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from . import services
from .config import settings
from .models import history, init_db, log_event, prune, recent_events

BOOT_TIME = time.time()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["JSON_SORT_KEYS"] = False
    init_db()
    log_event("INFO", "core", "NEXUS iniciado")

    # --- Páginas ----------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html", city=settings.default_city)

    # --- API REST ---------------------------------------------------------

    @app.get("/api/snapshot")
    def api_snapshot():
        only = request.args.get("only")
        names = only.split(",") if only else None
        return jsonify(services.snapshot(names))

    @app.get("/api/service/<name>")
    def api_service(name: str):
        loader = services.SERVICES.get(name)
        if loader is None:
            return jsonify({"ok": False, "error": f"serviço desconhecido: {name}"}), 404
        return jsonify(services.cached(name, loader))

    @app.get("/api/weather")
    def api_weather():
        """Clima para coordenadas arbitrárias (usado pela busca de cidade)."""
        try:
            lat = float(request.args["lat"])
            lon = float(request.args["lon"])
        except (KeyError, ValueError):
            return jsonify({"ok": False, "error": "lat e lon são obrigatórios"}), 400
        city = request.args.get("city")
        try:
            data = services.load_weather(lat, lon, city)
            return jsonify({"ok": True, "data": data})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)[:300]}), 502

    @app.get("/api/geocode")
    def api_geocode():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"ok": True, "data": []})
        try:
            return jsonify({"ok": True, "data": services.geocode(q)})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)[:300]}), 502

    @app.get("/api/history/<path:series>")
    def api_history(series: str):
        limit = min(int(request.args.get("limit", 120)), 1000)
        return jsonify({"ok": True, "series": series, "points": history(series, limit)})

    @app.get("/api/events")
    def api_events():
        return jsonify({"ok": True, "events": recent_events(50)})

    @app.get("/api/health")
    def api_health():
        snap = services.snapshot()
        meta = snap["meta"]
        return jsonify(
            {
                "ok": meta["healthy"] == meta["total"],
                "uptime_seconds": round(time.time() - BOOT_TIME, 1),
                "services_healthy": meta["healthy"],
                "services_total": meta["total"],
                "latency_ms": meta["elapsed_ms"],
                "version": "1.0.0",
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )

    @app.post("/api/maintenance/prune")
    def api_prune():
        removed = prune()
        log_event("INFO", "core", f"limpeza removeu {removed} registros")
        return jsonify({"ok": True, "removed": removed})

    # --- Streaming SSE ----------------------------------------------------

    @app.get("/api/stream")
    def api_stream():
        """Envia atualizações contínuas ao navegador via Server-Sent Events."""

        @stream_with_context
        def generate():
            tick = 0
            yield "retry: 3000\n\n"
            while True:
                tick += 1
                # ISS a cada ciclo (5s); demais serviços a cada 6 ciclos (30s)
                names = ["iss"] if tick % 6 else None
                payload = services.snapshot(names)
                payload["tick"] = tick
                yield f"event: update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                time.sleep(5)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"ok": False, "error": "rota não encontrada"}), 404

    @app.errorhandler(500)
    def server_error(exc):
        log_event("ERROR", "http", str(exc)[:300])
        return jsonify({"ok": False, "error": "erro interno"}), 500

    return app


app = create_app()
