"""Serve the parse viewer from the repo root so JSON + visual paths resolve.

Usage:
  python scripts/serve_viewer.py
  # then open http://127.0.0.1:8765/web/
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _pick_port(host: str, preferred: int, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        if _port_free(host, port):
            return port
    raise OSError(f"No free port in {preferred}–{preferred + attempts - 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve QuestBank parse viewer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    port = args.port
    if not _port_free(args.host, port):
        print(f"Port {port} is already in use — trying the next free port.")
        print(f"If a viewer is already running, open http://{args.host}:{port}/web/")
        port = _pick_port(args.host, port + 1)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with ReusableTCPServer((args.host, port), handler) as httpd:
        url = f"http://{args.host}:{port}/web/"
        print(f"Serving {ROOT}")
        print(f"Open {url}")
        if not args.no_open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
