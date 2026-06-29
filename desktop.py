"""
Desktop entry point for the Insurance Policy Extractor.

Runs the existing Flask app (app.py) on a background thread bound to a free
local port, then opens a native OS window (via pywebview) pointed at it.
No Chromium is bundled — pywebview uses the platform webview:
  - Windows : WebView2 (Edge runtime)
  - macOS   : WKWebView
  - Linux   : WebKitGTK

This is the file PyInstaller freezes (see desktop.spec).

Run from source:
    python desktop.py
"""

import socket
import threading
import time
import urllib.request

import webview

from app import app  # the Flask instance defined in app.py


def _free_port() -> int:
    """Ask the OS for an unused localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int) -> None:
    # threaded=True so concurrent /api/extract calls don't block the UI.
    # use_reloader=False is required when running off the main thread.
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


def _wait_until_ready(url: str, timeout: float = 15.0) -> None:
    """Block until the Flask server answers, so the window never shows a blank page."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.15)
    # fall through; window will still open and show the connection error


def main() -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    server = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server.start()

    _wait_until_ready(url)

    webview.create_window(
        "Insurance Policy Extractor",
        url,
        width=1200,
        height=820,
        min_size=(900, 600),
    )
    # Daemon server thread is torn down automatically when the window closes.
    webview.start()


if __name__ == "__main__":
    main()
