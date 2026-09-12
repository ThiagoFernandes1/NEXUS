#!/usr/bin/env python3
"""Ponto de entrada do NEXUS Dashboard.

Uso:
    python run.py            # inicia o servidor
    python run.py --port 8080
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from app.config import settings
from app.server import app

BANNER = r"""
   _  _ ___  _  _ _   _ ___
  | \| | __|| \| | | | / __|    Painel de dados em tempo real
  | .` | _| | .` | |_| \__ \    v1.0.0
  |_|\_|___||_|\_|\___/|___/
"""


def main() -> int:
    p = argparse.ArgumentParser(description="NEXUS Dashboard")
    p.add_argument("--host", default=settings.host)
    p.add_argument("--port", type=int, default=settings.port)
    p.add_argument("--debug", action="store_true", default=settings.debug)
    p.add_argument("--no-browser", action="store_true", help="nao abrir o navegador")
    args = p.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(BANNER)
    print(f"  Servidor  : {url}")
    print(f"  API       : {url}/api/snapshot")
    print(f"  Saude     : {url}/api/health")
    print(f"  Banco     : {settings.database_url}")
    print("\n  Ctrl+C para encerrar.\n")

    if not args.no_browser:
        threading.Timer(1.4, lambda: webbrowser.open(url)).start()

    # threaded=True e essencial: o stream SSE ocupa uma conexao por aba.
    app.run(host=args.host, port=args.port, debug=args.debug,
            threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
