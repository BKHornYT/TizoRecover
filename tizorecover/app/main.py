"""Opens the TizoRecover window.

The page is served by :mod:`tizorecover.app.server` and shown in a native
window through pywebview (Edge WebView2 on Windows). Without pywebview the
same page opens in Edge's app mode, or the default browser, and the server
shuts itself down a while after the page stops pinging it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from tizorecover import APP_NAME
from tizorecover.app.server import App, make_server

PING_TIMEOUT = 45


def _edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.isfile(path):
                return path
    return shutil.which("msedge")


def run(browser: bool = False) -> int:
    app = App()
    server = make_server(app)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={app.token}"
    threading.Thread(target=server.serve_forever, name="tizo-http", daemon=True).start()

    if not browser:
        try:
            import webview
        except ImportError:
            webview = None
        if webview is not None:
            window = webview.create_window(APP_NAME, url, width=1320, height=860,
                                           min_size=(960, 620), background_color="#000000",
                                           text_select=True)
            app.window = window
            webview.start(private_mode=True)
            if app.job is not None:
                app.job.close()
            server.shutdown()
            return 0

    edge = _edge() if sys.platform == "win32" else None
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--window-size=1320,860"])
    else:
        webbrowser.open(url)
    print(f"{APP_NAME} is running at {url}  (close the window to quit, or press Ctrl+C)")
    try:
        while time.time() - app.last_ping < PING_TIMEOUT:
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    if app.job is not None:
        app.job.close()
    server.shutdown()
    return 0
