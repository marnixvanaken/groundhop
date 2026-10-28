#!/usr/bin/env python3
"""
GroundHop starten op Windows. GroundHop.bat roept dit aan; op de Mac doet
GroundHop.command hetzelfde.

Haalt de nieuwste versie op, installeert wat ontbreekt, start de server en
opent de app in je browser. Laat het venster open zolang je GroundHop
gebruikt; sluit het om te stoppen.

Dit staat in Python en niet in het .bat-bestand zelf: cmd leest een .bat regel
voor regel terwijl hij draait, en git pull kan dat bestand onder zijn handen
veranderen. Python leest een script in één keer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

MAP = Path(__file__).resolve().parent
ADRES = "http://localhost:4000"


def draait_al() -> bool:
    """Antwoordt er al iets op de poort? Net als curl in GroundHop.command telt
    elk antwoord, ook een foutcode."""
    zonder_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        zonder_proxy.open(ADRES + "/api/bron", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def vingerafdruk() -> str:
    return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()


def bijwerken() -> bool:
    """Haalt de nieuwste versie op. Geeft True als dit script zelf veranderde."""
    if not shutil.which("git"):
        print("  ! Git ontbreekt; ik start de versie die er staat.")
        print("    Installeer Git for Windows (git-scm.com) om bij te werken.")
        return False
    import publiceer  # alleen voor de lijst bestanden; standaardbibliotheek

    voor = vingerafdruk()
    # publiceer.py zet data rechtstreeks op GitHub. Een bestand dat daar zo voor
    # het eerst verschijnt, staat hier nog als nieuw, en dan weigert git pull
    # ("would be overwritten"). Even opzij, en daarna de eigen versie terug:
    # die van deze laptop is de nieuwste.
    opzij = []
    for f in publiceer.BESTANDEN:
        pad = MAP / f
        if pad.exists() and git("ls-files", "--error-unmatch", f).returncode != 0:
            pad.replace(pad.with_name(pad.name + ".lokaal"))
            opzij.append(pad)
    try:
        # --autostash zet je eigen, nog niet gepubliceerde data even opzij en
        # daarna terug.
        r = git("pull", "--ff-only", "--autostash", "-q")
    finally:
        for pad in opzij:
            pad.with_name(pad.name + ".lokaal").replace(pad)
    if r.returncode != 0:
        print("  ! Bijwerken lukte niet; ik start de versie die er staat.")
        for regel in (r.stderr or r.stdout).strip().splitlines():
            print(f"    {regel}")
        return False
    print("  ✓ Nieuwste versie")
    return vingerafdruk() != voor


def installeren():
    try:
        import bs4, curl_cffi, lxml, rich  # noqa: F401
        return
    except ImportError:
        pass
    print("  … onderdelen installeren (eenmalig)")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q",
                        "-r", "requirements.txt"])
    if r.returncode != 0:
        print("  ! Installeren lukte niet (zie hierboven).")


def wakker_houden():
    """Zolang de server draait, valt Windows niet in slaap: anders slaat hij de
    nachtelijke ronde en het ophalen van de marktwaarde over. Het deksel dicht
    doet hem nog wel slapen. Geldt tot dit proces stopt."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main() -> int:
    os.chdir(MAP)
    print()
    print("  ⚽ GroundHop")
    print("  ─────────────────────────────")

    if draait_al():
        print("  ✓ Draait al — de app gaat open.")
        webbrowser.open(ADRES)
        return 0

    # Verandert dit script zelf mee, dan start het opnieuw: de stappen hieronder
    # zijn al ingelezen, en de nieuwe zouden anders pas bij de volgende start
    # gebeuren.
    if "--bijgewerkt" not in sys.argv and bijwerken():
        print("  ↻ het startbestand is bijgewerkt — opnieuw starten")
        return subprocess.run([sys.executable, __file__, "--bijgewerkt"]).returncode

    installeren()

    # Clubnummers voor de albums opzoeken (alleen als er een ontbreekt), en wat
    # daardoor veranderde meteen live zetten.
    subprocess.run([sys.executable, "collecties_vul.py"])
    subprocess.run([sys.executable, "publiceer.py", "--als-gekoppeld"])

    if subprocess.run([sys.executable, "app/build_app_data.py"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print("  ✓ App-data bijgewerkt")

    threading.Timer(2, webbrowser.open, [ADRES]).start()
    print("  ✓ Server start — laat dit venster open, sluit het om te stoppen.")
    print()
    wakker_houden()
    try:
        return subprocess.run([sys.executable, "server.py"]).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
