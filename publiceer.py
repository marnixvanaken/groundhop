#!/usr/bin/env python3
"""
Zet data/dashboard_data.json (en de clubnummers van de albums) live: rechtstreeks op GitHub, zonder git.

Vercel bouwt de site opnieuw bij elke commit op main. Pushen vanaf de laptop
liep vast op inloggen, en uploaden via de website is een handeling die je
vergeet. Deze module doet het met de GitHub-API en een sleutel (een
fine-grained personal access token) die je één keer koppelt in de app.

De sleutel staat in ~/.groundhop/github_token, buiten de projectmap: server.py
serveert elk bestand uit die map aan je hele netwerk, en daar hoort een sleutel
niet tussen.

Het bestand gaat als blob, tree, commit en ref naar main (de Git Data API): dat
werkt ook voor grote bestanden, waar de eenvoudige contents-API bij 1 MB ophoudt.
Staat hetzelfde bestand er al, dan gebeurt er niets.

Gebruik
-------
    python3 publiceer.py            # zet het nu live
    python3 publiceer.py --als-gekoppeld   # idem, stil als er geen sleutel is
    python3 publiceer.py --status   # gekoppeld? welke repo?
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

MAP = Path.home() / ".groundhop"
SLEUTEL = MAP / "github_token"
# Wat de laptop maakt en de live site nodig heeft. Alleen wat veranderd is gaat
# mee, en alles samen in één commit.
BESTANDEN = ["data/dashboard_data.json", "data/collecties_ids.json", "data/collecties_seizoen.json"]
TAK = "main"
API = "https://api.github.com"


def repo() -> str:
    """owner/naam uit de git-remote, zodat een fork gewoon werkt."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "marnixvanaken/groundhop"


def sleutel() -> str | None:
    if os.environ.get("GROUNDHOP_GITHUB_TOKEN"):
        return os.environ["GROUNDHOP_GITHUB_TOKEN"].strip()
    try:
        return SLEUTEL.read_text("utf-8").strip() or None
    except OSError:
        return None


def gekoppeld() -> bool:
    return bool(sleutel())


class Fout(Exception):
    pass


def _vraag(methode: str, pad: str, token: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + pad, method=methode,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "groundhop"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        tekst = e.read().decode("utf-8", "replace")[:300]
        if e.code == 401:
            raise Fout("GitHub kent deze sleutel niet (meer). Koppel opnieuw in Meer.")
        if e.code in (403, 404):
            raise Fout("Deze sleutel mag niet schrijven in "
                       f"{repo()}. Geef hem bij 'Contents' het recht 'Read and write'.")
        raise Fout(f"GitHub antwoordde {e.code}: {tekst}")
    except urllib.error.URLError as e:
        raise Fout(f"GitHub is niet bereikbaar: {e.reason}")


def koppel(token: str) -> str:
    """Toetst de sleutel en bewaart hem. Geeft de repo terug."""
    token = token.strip()
    if not token:
        raise Fout("Geen sleutel ingevuld.")
    _vraag("GET", f"/repos/{repo()}", token)
    MAP.mkdir(mode=0o700, exist_ok=True)
    SLEUTEL.write_text(token, "utf-8")
    SLEUTEL.chmod(0o600)
    return repo()


def ontkoppel():
    try:
        SLEUTEL.unlink()
    except FileNotFoundError:
        pass


def blob_sha(inhoud: bytes) -> str:
    """Het id dat git zelf aan deze inhoud geeft; gelijk id is gelijke inhoud."""
    return hashlib.sha1(b"blob %d\0" % len(inhoud) + inhoud).hexdigest()


def publiceer(paden: list[str] | None = None) -> dict:
    """Zet de bestanden op main. Geeft {'status': 'live'|'al live', 'commit', 'bestanden'}."""
    token = sleutel()
    if not token:
        raise Fout("Nog niet gekoppeld met GitHub.")
    r = repo()

    nieuw = []
    for pad in paden or BESTANDEN:
        if not Path(pad).exists():
            continue
        inhoud = Path(pad).read_bytes()
        try:
            op_github = _vraag("GET", f"/repos/{r}/contents/{pad}?ref={TAK}", token).get("sha")
        except Fout:
            op_github = None
        if op_github != blob_sha(inhoud):
            nieuw.append((pad, inhoud))
    if not nieuw:
        return {"status": "al live", "commit": None, "bestanden": []}

    boomdelen = []
    for pad, inhoud in nieuw:
        blob = _vraag("POST", f"/repos/{r}/git/blobs", token,
                      {"content": base64.b64encode(inhoud).decode(), "encoding": "base64"})["sha"]
        boomdelen.append({"path": pad, "mode": "100644", "type": "blob", "sha": blob})
    # Twee pogingen: schuift main ertussen door, dan opnieuw vanaf de nieuwe kop.
    for poging in range(2):
        kop = _vraag("GET", f"/repos/{r}/git/ref/heads/{TAK}", token)["object"]["sha"]
        basis = _vraag("GET", f"/repos/{r}/git/commits/{kop}", token)["tree"]["sha"]
        boom = _vraag("POST", f"/repos/{r}/git/trees", token,
                      {"base_tree": basis, "tree": boomdelen})["sha"]
        commit = _vraag("POST", f"/repos/{r}/git/commits", token, {
            "message": f"Data bijgewerkt vanaf laptop ({datetime.now():%d-%m-%Y %H:%M})",
            "tree": boom, "parents": [kop]})["sha"]
        try:
            _vraag("PATCH", f"/repos/{r}/git/refs/heads/{TAK}", token, {"sha": commit})
            return {"status": "live", "commit": commit, "bestanden": [p for p, _ in nieuw]}
        except Fout:
            if poging:
                raise
    raise Fout("Live zetten is niet gelukt.")


def main():
    # Bij het starten: stil overslaan als er (nog) geen koppeling is.
    if "--als-gekoppeld" in sys.argv and not gekoppeld():
        return
    if "--status" in sys.argv:
        print(f"  repo: {repo()} — {'gekoppeld' if gekoppeld() else 'niet gekoppeld'}")
        return
    try:
        uit = publiceer()
    except Fout as e:
        raise SystemExit(f"  ✗ {e}")
    print(f"  ✓ {uit['status']}" + (f" ({uit['commit'][:7]})" if uit["commit"] else ""))


if __name__ == "__main__":
    main()
