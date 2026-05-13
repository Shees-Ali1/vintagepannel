#!/usr/bin/env python3
"""
Serves this folder over HTTP. POST /__save_catalog__/<path>.json writes under project root,
only inside Production/, thefinalone/, final one/, plus root warreng.json.

POST body (backward compatible):
  • A JSON array of tracks — written to the requested file only (legacy).
  • Or {"tracks": [...], "shuffleSync": {...}} — writes tracks to the primary file, then patches
    any sibling shuffle catalog (``… - strict_shuffled.json``, ``…- strict_shuffled.json``,
    ``…_shuffled.json``) in the same folder. Rows match ``matchAlbum`` only when ``albumOnly``
    is true (compilations); otherwise ``matchArtist`` + ``matchAlbum``.

Run:  python3 catalog_server.py
Open: http://127.0.0.1:8765/merging/merged_albums_gallery.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
SAVE_PREFIX = "/__save_catalog__/"


def shuffle_companion_paths(primary: Path) -> list[Path]:
    """Sibling shuffle catalogs to patch when the primary (non-shuffle) file is saved."""
    parent = primary.parent
    stem = primary.stem
    sl = stem.lower()
    if "strict_shuffled" in sl or sl.endswith("_shuffled") or re.search(r"\bshuffle\b", sl):
        return []
    candidates = [
        parent / f"{stem} - strict_shuffled.json",
        parent / f"{stem}- strict_shuffled.json",
        parent / f"{stem}_shuffled.json",
    ]
    out: list[Path] = []
    seen: set[Path] = set()
    for cand in candidates:
        if cand.is_file() and cand.resolve() not in seen:
            seen.add(cand.resolve())
            out.append(cand)
    return out


def apply_shuffle_album_patch(shuffle_path: Path, sync: dict) -> int:
    """Patch list rows where (album) or (artist+album) match sync criteria."""
    mal = str(sync.get("matchAlbum") or "").strip()
    fields = sync.get("setFields")
    if not mal or not isinstance(fields, dict):
        return 0
    album_only = bool(sync.get("albumOnly"))
    ma = str(sync.get("matchArtist") or "").strip()
    allowed = {"album", "year", "thumbnail", "description", "artist"}
    with shuffle_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return 0
    n = 0
    for row in data:
        if not isinstance(row, dict):
            continue
        ral = str(row.get("album") or "").strip()
        if ral != mal:
            continue
        if not album_only:
            ra = str(row.get("artist") or "").strip()
            if ra != ma:
                continue
        for k, v in fields.items():
            if k in allowed:
                row[k] = v
        n += 1
    if n:
        tmp = shuffle_path.with_suffix(shuffle_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(shuffle_path)
    return n


class CatalogHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        p = urlparse(self.path).path.lower()
        if p.endswith((".html", ".htm", ".js", ".json")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith(SAVE_PREFIX):
            self.send_error(404, "Not found")
            return
        rel = unquote(path[len(SAVE_PREFIX) :].lstrip("/"))
        if not rel.endswith(".json") or ".." in rel.split("/") or rel.startswith("/"):
            self.send_error(400, "Invalid catalog path")
            return
        json_path = (ROOT / Path(*rel.split("/"))).resolve()
        real_root = ROOT.resolve()
        try:
            real_json = json_path.resolve()
        except OSError:
            self.send_error(400, "Bad path")
            return
        if not str(real_json).startswith(str(real_root) + os.sep) and real_json != real_root:
            self.send_error(400, "Bad path")
            return
        prod_root = (ROOT / "Production").resolve()
        final_root = (ROOT / "thefinalone").resolve()
        final_one_root = (ROOT / "final one").resolve()
        warren_profile = (ROOT / "warreng.json").resolve()
        ok_prod = str(real_json).startswith(str(prod_root) + os.sep) or real_json == prod_root
        ok_final = str(real_json).startswith(str(final_root) + os.sep) or real_json == final_root
        ok_final_one = str(real_json).startswith(str(final_one_root) + os.sep) or real_json == final_one_root
        ok_warren_profile = real_json == warren_profile
        if not (ok_prod or ok_final or ok_final_one or ok_warren_profile):
            self.send_error(400, "Save only allowed under Production/, thefinalone/, final one/, or warreng.json")
            return
        stem_lower = real_json.stem.lower()
        name_lower = real_json.name.lower()
        if "strict_shuffled" in stem_lower or "strict-shuffled" in stem_lower:
            self.send_error(
                400,
                "Save the non-shuffle catalog from the panel; shuffle companions are updated automatically.",
            )
            return
        if stem_lower.endswith("_shuffled") or (
            "shuffled" in name_lower and "strict_shuffled" not in stem_lower
        ):
            self.send_error(400, "Save the primary catalog; shuffle JSON is updated automatically when you save.")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            self.send_error(400, "Empty body")
            return
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return

        tracks: list | None = None
        shuffle_sync: dict | None = None
        if isinstance(payload, list):
            tracks = payload
        elif isinstance(payload, dict) and isinstance(payload.get("tracks"), list):
            tracks = payload["tracks"]
            ss = payload.get("shuffleSync")
            shuffle_sync = ss if isinstance(ss, dict) else None
        else:
            self.send_error(400, "Root must be a JSON array, or an object with a \"tracks\" array")
            return

        try:
            tmp = json_path.with_suffix(json_path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(tracks, f, indent=2, ensure_ascii=False)
                f.write("\n")
            tmp.replace(json_path)
        except OSError as e:
            self.send_error(500, str(e))
            return

        shuffle_patched = 0
        if shuffle_sync:
            for sib in shuffle_companion_paths(json_path):
                try:
                    shuffle_patched += apply_shuffle_album_patch(sib, shuffle_sync)
                except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
                    self.send_error(500, f"Primary saved but shuffle sync failed ({sib.name}): {e}")
                    return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        out = {"ok": True, "shufflePatched": shuffle_patched}
        self.wfile.write(json.dumps(out).encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Serve multi-catalog editor + instant JSON save")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    httpd = HTTPServer((args.host, args.port), CatalogHandler)
    print(f"Serving {ROOT}")
    print(f"  Panel:   http://{args.host}:{args.port}/warren_g_editor.html")
    print(f"  Gallery: http://{args.host}:{args.port}/merging/merged_albums_gallery.html")
    print(
        f"  Save:    POST {SAVE_PREFIX}<path>.json — array or {{\"tracks\":[...],"
        f' "shuffleSync":{{"matchArtist","matchAlbum","setFields"}}}} (strict_shuffled sibling auto-patch)'
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
