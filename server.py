#!/usr/bin/env python3
"""
Match Tracker Server — vervangt 'python3 -m http.server'
- Serveert dashboard.html en statische bestanden
- Proxiet Sofascore API calls (omzeilt CORS)
- Slaat wedstrijdselecties op in data/selected_matches.json
"""

import json
import os
import sys
import time
import random
import subprocess
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs

# Zorg dat werkdirectory altijd de map van dit script is (ook bij scheduled tasks)
os.chdir(Path(__file__).parent)

_sync_status = {"running": False, "last": None, "error": None}

def daily_scheduler():
    """Draai elke dag om 00:00 automatisch een sync."""
    import datetime
    while True:
        now = datetime.datetime.now()
        # Bereken seconden tot volgende middernacht
        midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait_secs = (midnight - now).total_seconds()
        time.sleep(wait_secs)
        print("  [scheduler] Dagelijkse sync gestart (00:00)")
        run_sync()

threading.Thread(target=daily_scheduler, daemon=True).start()

def run_sync():
    """Draai download + export op de achtergrond."""
    if _sync_status["running"]:
        return
    _sync_status["running"] = True
    _sync_status["error"] = None
    try:
        python = sys.executable
        # Stap 1: download wedstrijddata
        subprocess.run([python, "sofascore_tracker.py", "--download"], timeout=86400, check=False)
        # Stap 2: exporteer
        subprocess.run([python, "sofascore_tracker.py", "--export"], timeout=60, check=False)
        _sync_status["last"] = time.strftime("%d-%m %H:%M:%S")
    except Exception as e:
        _sync_status["error"] = str(e)
    finally:
        _sync_status["running"] = False

PORT = 4000
DATA_DIR = Path("data")
COOKIES_FILE = Path("sofascore_cookies.txt")
BASE_SF = "https://www.sofascore.com/api/v1"

from curl_cffi import requests as cf_requests

_session = cf_requests.Session(impersonate="chrome124")

def load_cookies():
    if COOKIES_FILE.exists():
        return COOKIES_FILE.read_text(encoding="utf-8").strip()
    return None

def sf_get(url):
    cookies_str = load_cookies()
    cookie_dict = {}
    if cookies_str:
        for part in cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookie_dict[k.strip()] = v.strip()
    return _session.get(url, cookies=cookie_dict, timeout=20)


# Alleen deze hosts mogen door de beeldproxy. Zonder die grens is /img/ext een
# open proxy: iedereen die het dashboard kan bereiken zou er willekeurige URL's
# mee kunnen ophalen vanaf deze machine.
BEELDHOSTS = {"api.sofascore.app", "tmssl.akamaized.net"}
BEELDDOMEIN = ".transfermarkt.technology"


def toegestane_afbeelding(url: str) -> str | None:
    """Geeft de URL terug als hij van een toegestane beeldhost komt, anders None."""
    if not url:
        return None
    u = urlparse(url)
    if u.scheme != "https":
        return None
    host = (u.hostname or "").lower()
    return url if (host in BEELDHOSTS or host.endswith(BEELDDOMEIN)) else None

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        path = args[0] if args else ''
        if not any(x in path for x in ['.js', '.css', '.png', '.ico', '.woff']):
            print(f"  {args[1] if len(args)>1 else ''} {path}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_cors()
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        path = urlparse(self.path).path

        if path == "/api/cookies/save":
            cookies_str = body.get("cookies", "").strip()
            if cookies_str:
                COOKIES_FILE.write_text(cookies_str, encoding="utf-8")
                print(f"  ✓ Cookies opgeslagen in {COOKIES_FILE}")
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "error": "Lege cookies"})

        elif path == "/api/matches/save":
            DATA_DIR.mkdir(exist_ok=True)
            f = DATA_DIR / "selected_matches.json"
            existing = json.loads(f.read_text("utf-8")) if f.exists() else []
            existing_ids = {m["id"] for m in existing if isinstance(m, dict)}
            added = 0
            for match in (body if isinstance(body, list) else []):
                if match.get("id") not in existing_ids:
                    existing.append(match)
                    existing_ids.add(match["id"])
                    added += 1
            f.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")
            print(f"  + {added} wedstrijden opgeslagen (totaal: {len(existing)})")
            # Snelle export op de achtergrond (geen volledige download)
            threading.Thread(target=lambda: subprocess.run(
                [sys.executable, "sofascore_tracker.py", "--export"], timeout=60, check=False
            ), daemon=True).start()
            self.send_json({"added": added, "total": len(existing)})

        elif path == "/api/sync":
            if not _sync_status["running"]:
                threading.Thread(target=run_sync, daemon=True).start()
            self.send_json({"started": True, "already_running": _sync_status["running"]})

        elif path == "/api/sync-status":
            self.send_json(_sync_status)

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ─── Image proxy (player/team foto's via server — werkt op mobiel) ──
        if path.startswith("/img/"):
            parts = path.split("/")  # ['', 'img', 'player'|'team'|'ext', '<id>']
            img_url = None
            if len(parts) >= 4 and parts[2] in ("player", "team"):
                img_url = f"https://api.sofascore.app/api/v1/{parts[2]}/{parts[3]}/image"
            elif parts[2:3] == ["ext"]:
                # Transfermarkt zet de foto-URL in de pagina zelf; die komt hier
                # binnen zodat het plaatje net als de rest via deze server gaat
                # en niet rechtstreeks uit de browser — dat laatste werkte op
                # mobiel niet, en daarvoor staat deze proxy er.
                img_url = toegestane_afbeelding(parse_qs(parsed.query).get("u", [""])[0])
            if img_url:
                try:
                    # Sofascore wil de cookies; een plaatje van Transfermarkt
                    # heeft daar niets mee te maken en krijgt ze dus ook niet.
                    resp = (sf_get(img_url) if "sofascore" in img_url
                            else _session.get(img_url, timeout=20))
                    ct = resp.headers.get("Content-Type", "image/png")
                    body = resp.content
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", len(body))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_cors()
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    self.send_response(404)
                    self.end_headers()
            else:
                self.send_response(400)
                self.end_headers()

        # ─── Sofascore proxy ───────────────────────────────────────────────
        elif path.startswith("/sofascore/"):
            sf_path = path[len("/sofascore"):]
            url = BASE_SF + sf_path
            try:
                time.sleep(random.uniform(0.3, 0.8))
                resp = sf_get(url)
                if resp.status_code == 403:
                    self.send_json({"error": "Sofascore 403 — probeer later opnieuw.", "code": 403}, 200)
                    return
                self.send_json(resp.json())
            except Exception as e:
                self.send_json({"error": str(e)}, 200)

        elif path == "/api/cookies":
            # POST endpoint: sla cookies op
            pass

        elif path == "/api/cookie-status":
            has = COOKIES_FILE.exists()
            self.send_json({"has_cookies": has, "file": str(COOKIES_FILE)})

        # ─── Lokale data API ───────────────────────────────────────────────
        elif path == "/api/matches":
            f = DATA_DIR / "selected_matches.json"
            self.send_json(json.loads(f.read_text("utf-8")) if f.exists() else [])

        elif path == "/api/dashboard":
            f = DATA_DIR / "dashboard_data.json"
            self.send_json(json.loads(f.read_text("utf-8")) if f.exists() else None)

        elif path == "/api/sync-status":
            self.send_json(_sync_status)

        elif path == "/api/progress":
            f = DATA_DIR / "sync_progress.json"
            self.send_json(json.loads(f.read_text("utf-8")) if f.exists() else None)

        # ─── Statische bestanden ───────────────────────────────────────────
        else:
            if path == "/" or path == "":
                path = "/dashboard.html"
            file_path = Path("." + unquote(path))
            if file_path.exists() and file_path.is_file():
                ext = file_path.suffix.lower()
                ct = {".html":"text/html;charset=utf-8", ".js":"text/javascript",
                      ".css":"text/css", ".json":"application/json",
                      ".png":"image/png", ".ico":"image/x-icon",
                      ".svg":"image/svg+xml"}.get(ext, "application/octet-stream")
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"\n  ⚽ Match Tracker Server")
    print(f"  ─────────────────────────────────")
    print(f"  Open: http://localhost:{PORT}")
    print(f"  Ctrl+C om te stoppen\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server gestopt.")
