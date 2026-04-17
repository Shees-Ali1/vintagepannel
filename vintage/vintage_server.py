#!/usr/bin/env python3
"""
Serves this folder over HTTP and accepts POST /__save_catalog__ to overwrite
"Vintage Pop & Rock Radio (new).json" in place (used by vintage_editor.html).

Run:  python3 vintage_server.py
Open: http://127.0.0.1:8766/vintage_editor.html
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
JSON_NAME = "Vintage Pop & Rock Radio (new).json"
JSON_PATH = os.path.join(ROOT, JSON_NAME)
SAVE_PATH = "/__save_catalog__"


class CatalogHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != SAVE_PATH:
            self.send_error(404, "Not found")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            self.send_error(400, "Empty body")
            return
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        if not isinstance(data, list):
            self.send_error(400, "Root must be a JSON array")
            return
        try:
            # One-shot safety backup per run: save the first pre-save snapshot.
            if os.path.exists(JSON_PATH):
                bak_dir = os.path.join(ROOT, ".backups")
                os.makedirs(bak_dir, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                bak = os.path.join(bak_dir, f"{JSON_NAME}.{stamp}.bak")
                if not os.path.exists(bak):
                    shutil.copy2(JSON_PATH, bak)
            tmp = JSON_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, JSON_PATH)
        except OSError as e:
            self.send_error(500, str(e))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def main():
    ap = argparse.ArgumentParser(description="Serve vintage catalog editor + instant JSON save")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()
    httpd = HTTPServer((args.host, args.port), CatalogHandler)
    print(f"Serving {ROOT}")
    print(f"  Editor:  http://{args.host}:{args.port}/vintage_editor.html")
    print(f"  Save:    POST {SAVE_PATH} -> {JSON_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
