#!/usr/bin/env python3
"""
Transfermarkt PoC — proof of concept parser
===========================================

Doel: laten zien WELKE velden Transfermarkt daadwerkelijk levert, in exact het
schema van data/selected_matches.json, zodat je kunt beoordelen of een migratie
vanaf Sofascore de moeite waard is.

Deze PoC raakt de bestaande pipeline niet aan. Hij schrijft niets naar data/
tenzij je expliciet --json meegeeft.

Gebruik
-------
    # Wedstrijdrapport (spielbericht)
    python3 transfermarkt_poc.py --match 4894734

    # Idem, maar bewaar de HTML zodat je offline kunt itereren
    python3 transfermarkt_poc.py --match 4894734 --dump html_dump/

    # Parse een eerder bewaarde pagina, zonder netwerk
    python3 transfermarkt_poc.py --match 4894734 --html html_dump/match_4894734.html

    # Spelerprofiel: marktwaarde + transfers + interlands
    python3 transfermarkt_poc.py --player 1

    # Schrijf het resultaat weg in selected_matches.json-vorm
    python3 transfermarkt_poc.py --match 4894734 --json /tmp/match.json

Afhankelijkheden: beautifulsoup4 (+ lxml optioneel), curl_cffi (optioneel maar
sterk aanbevolen: Transfermarkt zit achter Cloudflare).
"""

from __future__ import annotations  # PEP 604-annotaties op Python 3.9 (macOS CLT)

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Ontbrekende dependency: pip install beautifulsoup4 lxml")

# curl_cffi imiteert een echte browser-TLS-fingerprint. Zonder dit geeft
# Transfermarkt vrijwel zeker een Cloudflare-challenge terug.
try:
    from curl_cffi import requests as _http
    _IMPERSONATE = {"impersonate": "chrome124"}
except ImportError:
    import requests as _http
    _IMPERSONATE = {}

BASE = "https://www.transfermarkt.nl"

# Eén sessie voor alle verzoeken. Zonder sessie gaat bij elke aanroep de
# cookiejar overboord — ook de vrijgave die Cloudflare net had afgegeven, dus
# elk verzoek begint weer van voren af aan. Bij lange runs (duizenden
# spelersprofielen) leidt dat tot 403's die er niet horen te zijn.
try:
    _sessie = _http.Session()
except Exception:      # oudere requests-versies zonder Session-fabriek
    _sessie = _http

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# ─── Diagnostiek ─────────────────────────────────────────────────────────────

class Diag:
    """Houdt per veld bij of het gevonden is, zodat de PoC zichzelf verantwoordt."""

    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def ok(self, veld, waarde):
        kort = str(waarde)
        if len(kort) > 58:
            kort = kort[:55] + "..."
        self.rows.append((veld, "OK", kort))
        return waarde

    def leeg(self, veld, reden=""):
        # Veld bestaat op TM maar was niet ingevuld voor deze wedstrijd.
        self.rows.append((veld, "LEEG", reden))
        return None

    def gemist(self, veld, reden=""):
        # Selector matchte niet — vrijwel altijd een parserprobleem.
        self.rows.append((veld, "GEMIST", reden))
        return None

    def rapport(self, titel):
        print(f"\n{'=' * 78}")
        print(f"  {titel}")
        print(f"{'=' * 78}")
        print(f"  {'veld':<26} {'status':<8} waarde")
        print(f"  {'-' * 26} {'-' * 8} {'-' * 38}")
        for veld, status, waarde in self.rows:
            merk = {"OK": " ", "LEEG": "·", "GEMIST": "!"}[status]
            print(f" {merk}{veld:<26} {status:<8} {waarde}")
        n_ok = sum(1 for r in self.rows if r[1] == "OK")
        n_leeg = sum(1 for r in self.rows if r[1] == "LEEG")
        n_mis = sum(1 for r in self.rows if r[1] == "GEMIST")
        print(f"  {'-' * 74}")
        print(f"  {n_ok} gevonden · {n_leeg} leeg op TM · {n_mis} gemist door parser")
        if n_mis:
            print("  ! = selector matchte niet. Draai met --dump en stuur de HTML door.")


# ─── HTTP ────────────────────────────────────────────────────────────────────

# Oplopend wachten na een Cloudflare-blokkade. De eerste twee stappen vangen
# een korte opstopping; de laatste is lang genoeg om een venster van een minuut
# uit te zitten. Vier pogingen in totaal.
WACHT_NA_BLOKKADE = (15, 45, 90)

# Statuscodes die vanzelf overgaan. 403/429/503 is Cloudflare die afremt.
# 502 en 504 zijn Transfermarkt zelf die even niet antwoordt; in de volledige
# profielrun kwamen die een stuk of twintig keer langs en die spelers vielen
# meteen af, terwijl een tweede poging ze gewoon had opgeleverd. Een 404 hoort
# hier niet: die herhaalt zich.
TIJDELIJKE_STATUS = (403, 429, 502, 503, 504)

def fetch(url: str, dump_naar: Path | None = None, naam: str = "page") -> str:
    """Haal een pagina op met browser-fingerprint. Geeft HTML-tekst terug."""
    if not _IMPERSONATE:
        print("  ! curl_cffi niet geinstalleerd — Cloudflare blokkeert waarschijnlijk.")
        print("    pip install curl_cffi")
    print(f"  → GET {url}")
    # Een DNS- of verbindingshapering onderweg mag een run van tien minuten niet
    # weggooien. Netwerkfouten krijgen drie kansen met oplopende wachttijd;
    # een HTTP-status blijft meteen fataal, want die herhaalt zich toch.
    resp = None
    for poging in range(len(WACHT_NA_BLOKKADE) + 1):
        try:
            resp = _sessie.get(url, headers=HEADERS, timeout=30, **_IMPERSONATE)
        except Exception as e:
            if poging >= 2:
                raise SystemExit(f"  ✗ netwerkfout na {poging + 1} pogingen: {e}")
            pauze = 2 ** (poging + 1)
            print(f"    ! netwerkfout ({type(e).__name__}), opnieuw over {pauze}s")
            time.sleep(pauze)
            continue
        # Deze statussen gaan over: even wachten helpt, opgeven niet. Andere
        # statussen (404 bijvoorbeeld) herhalen zich wel en zijn meteen fataal.
        if resp.status_code not in TIJDELIJKE_STATUS:
            break
        if poging >= len(WACHT_NA_BLOKKADE):
            break
        pauze = WACHT_NA_BLOKKADE[poging]
        print(f"    ! HTTP {resp.status_code} (tijdelijk), opnieuw over {pauze}s")
        time.sleep(pauze)
    if resp.status_code != 200:
        raise SystemExit(
            f"  ✗ HTTP {resp.status_code} van Transfermarkt.\n"
            f"    403/503 betekent meestal Cloudflare. Probeer curl_cffi, een ander\n"
            f"    IP, of sla de pagina handmatig op en gebruik --html."
        )
    html = resp.text
    if dump_naar:
        dump_naar.mkdir(parents=True, exist_ok=True)
        pad = dump_naar / f"{naam}.html"
        pad.write_text(html, encoding="utf-8")
        print(f"  ✓ HTML bewaard: {pad} ({len(html):,} bytes)")
    return html


def soep(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


# ─── Parse-hulpjes ───────────────────────────────────────────────────────────

_SPELER_RE = re.compile(r"/spieler/(\d+)")
_VEREIN_RE = re.compile(r"/verein/(\d+)")
_WETTBEWERB_RE = re.compile(r"/wettbewerb/([A-Z0-9]+)")


def speler_id(href: str | None) -> int | None:
    m = _SPELER_RE.search(href or "")
    return int(m.group(1)) if m else None


def club_id(href: str | None) -> int | None:
    m = _VEREIN_RE.search(href or "")
    return int(m.group(1)) if m else None


def minuut_uit_sprite(style: str | None) -> int | None:
    """
    Transfermarkt rendert de minuut als CSS-sprite in plaats van tekst.
    De sprite is een raster van 10 cijfers per rij, stapgrootte 36px.
    background-position: 0px 0px      → minuut 1
    background-position: -36px 0px    → minuut 2
    background-position: 0px -36px    → minuut 11
    """
    if not style:
        return None
    m = re.search(r"background-position:\s*(-?\d+)px\s+(-?\d+)px", style)
    if not m:
        return None
    x, y = abs(int(m.group(1))), abs(int(m.group(2)))
    return x // 36 + (y // 36) * 10 + 1


def lees_minuut(node) -> tuple[int | None, int | None]:
    """Geeft (minuut, blessuretijd). Probeert eerst tekst, dan de sprite."""
    if node is None:
        return None, None
    tekst = node.get_text(" ", strip=True)
    m = re.search(r"(\d{1,3})\s*\+\s*(\d{1,2})", tekst)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{1,3})\s*'", tekst) or re.fullmatch(r"\s*(\d{1,3})\s*", tekst)
    if m:
        return int(m.group(1)), None
    span = node.find("span", style=True)
    if span:
        return minuut_uit_sprite(span.get("style")), None
    return None, None


def _eerste_getal(tekst: str) -> int | None:
    m = re.search(r"(\d[\d.\s]*)", tekst.replace("\xa0", " "))
    if not m:
        return None
    try:
        return int(re.sub(r"[.\s]", "", m.group(1)))
    except ValueError:
        return None


_EENHEID = {"mln": 1_000_000, "mio": 1_000_000, "mil": 1_000_000, "m": 1_000_000,
            "dzd": 1_000, "tsd": 1_000, "k": 1_000}


def parse_bedrag(tekst: str) -> int | None:
    """
    '10,00 mln. €' → 10000000 · '€14.00m' → 14000000 · '25 dzd. €' → 25000
    · '1.200.000' → 1200000 · 'gratis' → 0.

    Scheidingstekens zijn dubbelzinnig: in '14.00m' is de punt decimaal, in
    '1.200.000' een duizendtalscheider. De eenheid beslist — staat er mln/dzd
    achter, dan is het getal een decimaal, anders zijn het duizendtallen.
    """
    if not tekst:
        return None
    t = tekst.lower().replace("\xa0", " ").strip()
    if re.search(r"\b(gratis|free|ablösefrei|transfervrij|loan|huur)\b", t):
        return 0
    m = re.search(r"(\d[\d.,]*)\s*(mln|mio|mil|dzd|tsd|m|k)?\b", t)
    if not m:
        return None
    ruw, eenheid = m.group(1), (m.group(2) or "").strip()
    factor = _EENHEID.get(eenheid, 1)
    if factor > 1:
        # Met eenheid: het laatste scheidingsteken is de decimale komma/punt.
        if ruw.count(".") == 1 and "," not in ruw:
            ruw = ruw.replace(".", ",")
        ruw = ruw.replace(".", "").replace(",", ".")
    else:
        # Zonder eenheid zijn alle scheidingstekens duizendtallen.
        ruw = re.sub(r"[.,]", "", ruw)
    try:
        return int(float(ruw) * factor)
    except ValueError:
        return None


# ─── Wedstrijdrapport ────────────────────────────────────────────────────────

def parse_match(html: str, match_id: int, lineup_html: str | None = None) -> tuple[dict, Diag]:
    """Zet een spielbericht-pagina om naar het schema van selected_matches.json."""
    s = soep(html)
    d = Diag()
    paginatekst = s.get_text(" ", strip=True)

    # ── Teams ────────────────────────────────────────────────────────────────
    def team(kant: str) -> dict:
        blok = s.select_one(f"div.sb-team.sb-{kant}")
        link = blok.select_one("a.sb-vereinslink") if blok else None
        if not link:
            # Terugval: eerste vereinslink aan de juiste kant van de pagina.
            links = s.select("a.sb-vereinslink")
            link = links[0] if (kant == "heim" and links) else (links[-1] if links else None)
        if not link:
            return {"name": "", "id": None, "slug": ""}
        href = link.get("href", "")
        return {
            "name": link.get_text(strip=True),
            "id": club_id(href),
            "slug": href.strip("/").split("/")[0] if href else "",
        }

    home_team = team("heim")
    away_team = team("gast")
    d.ok("home_team", home_team["name"]) if home_team["name"] else d.gemist("home_team", "a.sb-vereinslink")
    d.ok("away_team", away_team["name"]) if away_team["name"] else d.gemist("away_team", "a.sb-vereinslink")

    # ── Eindstand + rust ─────────────────────────────────────────────────────
    home_score = away_score = None
    eind = s.select_one("div.sb-endstand")
    if eind:
        m = re.search(r"(\d+)\s*:\s*(\d+)", eind.get_text(" ", strip=True))
        if m:
            home_score, away_score = int(m.group(1)), int(m.group(2))

    # Bij een strafschoppenserie telt Transfermarkt de benutte strafschoppen
    # bij de eindstand op: de bekerfinale Ajax - PSV (1-1, penalty's 2-3) staat
    # er als "3:4 n.s.". Zo'n stand als uitslag opschrijven is fout — de
    # wedstrijd eindigde 1-1 — en het verklaart precies waarom er vijf
    # doelpunten meer in de standen zaten dan op spelersnaam.
    #
    # Het losse blok #sb-elfmeterscheissen is het signaal; de stand in het veld
    # staat als doorlopende tussenstand bij het laatste doelpunt in #sb-tore.
    penalty_shootout = None
    serie = s.select_one("#sb-elfmeterscheissen")
    if serie is not None and home_score is not None:
        veld = (0, 0)   # geen doelpunten betekent 0-0 na verlenging
        for b in s.select("#sb-tore div.sb-aktion-spielstand b"):
            m = re.search(r"(\d+)\s*:\s*(\d+)", b.get_text(strip=True))
            if m:
                veld = (int(m.group(1)), int(m.group(2)))
        strafschoppen = (home_score - veld[0], away_score - veld[1])
        # Een serie volgt per definitie op een gelijkspel, en je kunt er niet
        # minder dan nul benutten. Klopt dat niet, dan is de aanname onjuist en
        # laten we de eindstand liever staan dan hem verkeerd te corrigeren.
        if veld[0] != veld[1] or min(strafschoppen) < 0:
            d.gemist("score", f"strafschoppenserie, maar veldstand {veld[0]}-{veld[1]} "
                              f"bij eindstand {home_score}-{away_score}")
            home_score = None
        else:
            penalty_shootout = {"home": strafschoppen[0], "away": strafschoppen[1]}
            home_score, away_score = veld
            d.ok("score", f"{home_score}-{away_score} "
                          f"(strafschoppen {strafschoppen[0]}-{strafschoppen[1]})")
    elif home_score is not None:
        d.ok("score", f"{home_score}-{away_score}")

    if home_score is None:
        d.gemist("score", "div.sb-endstand")

    half_time = {"home": None, "away": None}
    rust = s.select_one("div.sb-halbzeit")
    if rust:
        m = re.search(r"(\d+)\s*:\s*(\d+)", rust.get_text(" ", strip=True))
        if m:
            half_time = {"home": int(m.group(1)), "away": int(m.group(2))}
            d.ok("half_time", f"{half_time['home']}-{half_time['away']}")
    if half_time["home"] is None:
        # Onderscheid "blok ontbreekt" van "blok stond er maar las anders" —
        # bij verlenging/strafschoppen wijkt de notatie af, en dan wil je in het
        # rapport meteen zien wát er stond in plaats van opnieuw te moeten meten.
        rust_tekst = rust.get_text(" ", strip=True) if rust else ""
        if rust and not re.search(r"\d", rust_tekst):
            # Bij verlenging of strafschoppen staat er alleen een markering
            # ("n.v.", "n.P.") en géén ruststand. De bron heeft hem dan niet;
            # dat is iets anders dan een selector die misgrijpt.
            d.leeg("half_time", f"niet vermeld, blok las {rust_tekst!r}")
        elif rust:
            d.gemist("half_time", f"sb-halbzeit las {rust_tekst!r}")
        else:
            d.gemist("half_time", "div.sb-halbzeit ontbreekt")

    # ── Competitie, speelronde, datum ────────────────────────────────────────
    # sb-datum is een <p> binnen div.sb-spieldaten, dus selecteer op class
    # zonder tagnaam vast te leggen.
    datum_blok = s.select_one(".sb-datum") or s.select_one(".sb-spieldaten")
    blok_tekst = datum_blok.get_text(" ", strip=True) if datum_blok else ""

    # Competitie- en seizoens-ID uit de prestatielinks van de spelers. Die
    # dragen /saison/{jaar}/wettbewerb/{ID} en staan op élke wedstrijdpagina.
    #
    # Dit is bewust niet het datumblok: bij een competitiewedstrijd staat daar
    # een speeldag-link met de competitie erin, maar bij een Europese wedstrijd
    # staat er alleen platte tekst ("Groepsfase") en ontbreekt elke
    # /wettbewerb/-link op de hele pagina.
    tournament_id = season_id = None
    paren = re.findall(r"/saison/(\d{4})/wettbewerb/([A-Z0-9]+)", html)
    if paren:
        from collections import Counter
        jaar, tid = Counter(paren).most_common(1)[0][0]
        season_id, tournament_id = int(jaar), tid
    elif datum_blok:
        for a in datum_blok.find_all("a", href=_WETTBEWERB_RE):
            m = _WETTBEWERB_RE.search(a.get("href", ""))
            if m:
                tournament_id = m.group(1)
                break

    # Competitienaam: de link naar de seizoenspagina draagt de naam als tekst.
    # De navigatielinks bovenaan de pagina hebben dezelfde /wettbewerb/-vorm maar
    # lege tekst, en de zijbalk heeft /marktwerte/ — beide moeten we mijden.
    tournament = ""
    for a in s.find_all("a", href=re.compile(r"/startseite/wettbewerb/[^/]+/saison_id/")):
        naam = a.get_text(strip=True) or a.get("title", "")
        if not naam:
            continue
        m = _WETTBEWERB_RE.search(a.get("href", ""))
        if tournament_id and m and m.group(1) != tournament_id:
            continue
        tournament = naam
        if not tournament_id and m:
            tournament_id = m.group(1)
        m = re.search(r"/saison_id/(\d{4})", a.get("href", ""))
        if m:
            season_id = int(m.group(1))
        break
    if not tournament and tournament_id:
        # Terugval: navigatielink met dezelfde competitie-ID draagt de naam in
        # title of img-alt.
        #
        # Let op: de prestatielinks van spelers hebben DEZELFDE /wettbewerb/-vorm
        # (/joey-veerman/leistungsdatendetails/spieler/123/saison/2022/wettbewerb/CLQ)
        # maar dragen de spelersnaam als title. Zonder deze uitsluiting levert
        # een Europese wedstrijd "Joey Veerman" op als competitienaam — gevuld,
        # dus het rapport zag er goed uit.
        for a in s.find_all("a", href=re.compile(rf"/wettbewerb/{tournament_id}\b")):
            if re.search(r"/(?:spieler|leistungsdaten\w*)/", a.get("href", "")):
                continue
            img = a.find("img")
            naam = a.get("title", "") or (img.get("alt", "") if img else "")
            if naam and not re.match(r"^\d+\.\s", naam):
                tournament = naam
                break

    if not tournament:
        # Laatste terugval: de paginatitel. Bij een Europese wedstrijd staat de
        # competitie nergens als link op de pagina, maar wel hier:
        #   "PSV - SSC Napoli, 21 okt. 2025 - UEFA Champions League
        #    - Wedstrijdverslag | Transfermarkt"
        titel_el = s.find("title")
        if titel_el:
            m = re.search(r"-\s*([^-|]{3,60}?)\s*-\s*[^-|]+\|\s*Transfermarkt\s*$",
                          titel_el.get_text(strip=True))
            if m:
                tournament = m.group(1).strip()

    # Speeldagnummer bij competitiewedstrijden; knock-outduels hebben er geen,
    # die dragen een fasenaam. Dat is geen ontbrekend veld maar een ander soort
    # wedstrijd, dus leggen we de fase apart vast.
    m = re.search(r"(\d{1,2})\.\s*(?:speeldag|Spieltag|matchday)", blok_tekst, re.I)
    ronde = int(m.group(1)) if m else None
    ronde_naam = ""
    if ronde is None:
        # Het datumblok heeft altijd de vorm  FASE | DATUM | TIJD  — bij een
        # competitiewedstrijd is de fase een speeldag-link, bij een bekerduel
        # platte tekst. Een lijst met fasenamen bijhouden is dweilen: Europese
        # duels kennen "3e kwalificatieronde", "Play-offronde", "1e
        # Groepswedstrijd" en tientallen varianten per competitie. Lees hem
        # daarom op positie, en verwerp alleen wat overduidelijk geen fase is.
        eerste = blok_tekst.split("|")[0].strip() if "|" in blok_tekst else ""
        if (eerste
                and len(eerste) <= 60
                and not re.search(r"\d{1,2}[-.]\d{1,2}[-.]\d{2,4}", eerste)
                and not re.fullmatch(r"[\d:.\s]+(uur|Uhr)?", eerste, re.I)):
            ronde_naam = eerste

    # Datum: de "wat gebeurde er vandaag"-link draagt een ISO-datum. Betrouwbaarder
    # dan de zichtbare tekst, die een tweecijferig jaartal gebruikt ("zo, 13-09-26").
    datum_iso, ts = "", None
    datum_link = s.find("a", href=re.compile(r"/datum/(\d{4}-\d{2}-\d{2})"))
    if datum_link:
        datum_iso = re.search(r"/datum/(\d{4}-\d{2}-\d{2})", datum_link["href"]).group(1)
    else:
        m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", blok_tekst)
        if m:
            jaar = int(m.group(3))
            jaar += 2000 if jaar < 100 else 0
            datum_iso = f"{jaar:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if datum_iso:
        uur, minuut = 0, 0
        m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", blok_tekst)
        if m:
            uur, minuut = int(m.group(1)), int(m.group(2))
        jaar, maand, dag = (int(x) for x in datum_iso.split("-"))
        try:  # aftrapmoment is lokale tijd; zoneinfo zit in de stdlib vanaf 3.9
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/Amsterdam")
        except Exception:
            tz = timezone.utc
        ts = int(datetime(jaar, maand, dag, uur, minuut, tzinfo=tz).timestamp())

    # "6. Speeldag" als competitienaam is een stille fout: het veld is gevuld,
    # maar met de speelronde. Markeer dat expliciet als gemist.
    #
    # De controle mag niet op "begint met een cijfer en een punt" staan: dan
    # sneuvelen "2. Bundesliga" en "3. Liga", die wél gewoon de competitie zijn.
    # Alleen een cijfer gevolgd door een speeldag-woord is verdacht.
    if tournament and re.match(r"^\d+\.\s*(speeldag|spieltag|matchday)\b",
                               tournament, re.I):
        d.gemist("tournament", f"kreeg speelronde {tournament!r} i.p.v. competitie")
        tournament = ""
    elif tournament:
        d.ok("tournament", tournament)
    else:
        d.gemist("tournament", "a[href*=/startseite/wettbewerb/.../saison_id/]")
    d.ok("tournament_id", tournament_id) if tournament_id else d.gemist("tournament_id")
    d.ok("season_id", season_id) if season_id else d.leeg("season_id")
    if ronde:
        d.ok("round", ronde)
    elif ronde_naam:
        d.leeg("round", f"knock-out: {ronde_naam}")
    else:
        d.gemist("round", "'N. speeldag' noch een fasenaam")
    d.ok("date", datum_iso) if datum_iso else d.gemist("date", "a[href*=/datum/]")

    # ── Stadion, publiek, scheidsrechter ─────────────────────────────────────
    extra = s.select_one("p.sb-zusatzinfos")
    extra_tekst = extra.get_text(" ", strip=True) if extra else paginatekst

    venue_naam, venue_id = "", None
    if extra:
        stadion_link = extra.find("a", href=re.compile(r"/stadion/"))
        if stadion_link:
            venue_naam = stadion_link.get_text(strip=True)
            m = re.search(r"/verein/(\d+)", stadion_link.get("href", ""))
            venue_id = int(m.group(1)) if m else None
        else:
            # Stadionnaam staat vaak als kale tekst vooraan het blok.
            eerste = extra_tekst.split("|")[0].strip()
            if eerste and not eerste.lower().startswith(("bezoek", "toeschouw", "zuschau", "attend")):
                venue_naam = eerste
    d.ok("venue", venue_naam) if venue_naam else d.gemist("venue", "p.sb-zusatzinfos")

    # Transfermarkt schrijft "34.900 toeschouwers" — getal vóór het label.
    # Sommige taalversies draaien dat om, dus beide vormen proberen.
    attendance = None
    m = re.search(r"([\d.,\s]{3,12})\s*(?:toeschouwers|bezoekers|zuschauer|spectators|attendance)",
                  extra_tekst, re.I)
    if not m:
        m = re.search(r"(?:toeschouwers|bezoekers|zuschauer|attendance)\s*:?\s*([\d.,\s]{3,12})",
                      extra_tekst, re.I)
    if m:
        attendance = _eerste_getal(m.group(1))
    if attendance:
        d.ok("attendance", f"{attendance:,}")
    else:
        d.leeg("attendance", "geen publiekscijfer op pagina")

    referee = {"name": "", "id": None}
    ref_link = (extra.find("a", href=re.compile(r"/schiedsrichter/")) if extra else None)
    if ref_link:
        referee["name"] = ref_link.get_text(strip=True)
        m = re.search(r"/schiedsrichter/(\d+)", ref_link.get("href", ""))
        referee["id"] = int(m.group(1)) if m else None
    else:
        m = re.search(r"(?:scheidsrechter|schiedsrichter|referee)\s*:?\s*([A-Za-zÀ-ÿ'\-\. ]{3,40})",
                      extra_tekst, re.I)
        if m:
            referee["name"] = m.group(1).strip()
    d.ok("referee", referee["name"]) if referee["name"] else d.gemist("referee")

    # ── Doelpunten ───────────────────────────────────────────────────────────
    def kant_van(li) -> str:
        klassen = " ".join(li.get("class", []))
        return "home" if "heim" in klassen else "away"

    goals = []
    for li in s.select("#sb-tore li"):
        kant = kant_van(li)
        actie = li.select_one("div.sb-aktion-aktion") or li
        links = actie.find_all("a", href=_SPELER_RE)
        if not links:
            continue
        minuut, extra_tijd = lees_minuut(li.select_one("div.sb-aktion-uhr"))
        actie_tekst = actie.get_text(" ", strip=True).lower()
        soort = "regular"
        if "penalty" in actie_tekst or "strafschop" in actie_tekst or "elfmeter" in actie_tekst:
            soort = "penalty"
        elif "eigen doelpunt" in actie_tekst or "eigentor" in actie_tekst or "own goal" in actie_tekst:
            soort = "own"
        # De doelpuntenmaker staat als a.wichtig; overige links kunnen portretten
        # van dezelfde speler zijn. Alleen een afwijkend speler-ID is een assist.
        maker = actie.select_one("a.wichtig") or links[0]
        maker_id = speler_id(maker.get("href"))
        assist_link = next(
            (a for a in links if speler_id(a.get("href")) not in (None, maker_id)), None)
        goals.append({
            "player": maker.get_text(strip=True),
            "player_id": maker_id,
            "team": home_team["name"] if kant == "home" else away_team["name"],
            "minute": minuut,
            "added_time": extra_tijd,
            "assist": assist_link.get_text(strip=True) if assist_link else None,
            "assist_id": speler_id(assist_link.get("href")) if assist_link else None,
            "type": soort,
        })
    if goals:
        d.ok("goals", f"{len(goals)} stuks, {sum(1 for g in goals if g['assist'])} met assist")
    elif home_score == 0 and away_score == 0:
        d.leeg("goals", "0-0")
    else:
        d.gemist("goals", "#sb-tore li")

    # ── Kaarten ──────────────────────────────────────────────────────────────
    cards = []
    for li in s.select("#sb-karten li"):
        kant = kant_van(li)
        actie = li.select_one("div.sb-aktion-aktion") or li
        link = actie.find("a", href=_SPELER_RE)
        if not link:
            continue
        minuut, extra_tijd = lees_minuut(li.select_one("div.sb-aktion-uhr"))
        t = actie.get_text(" ", strip=True).lower()
        # "Geel-rode kaart" is de gangbare notatie op transfermarkt.nl; zonder
        # die term valt hij door naar "rode kaart" (want die tekst zit erin).
        # Het aantal rode kaarten klopt dan nog steeds, maar het onderscheid
        # tussen direct rood en tweede geel gaat verloren.
        if ("tweede gele" in t or "geel-rode" in t or "gelb-rote" in t
                or "second yellow" in t):
            soort = "second_yellow"
        elif "rode kaart" in t or "rote karte" in t or "red card" in t:
            soort = "red"
        else:
            soort = "yellow"
        reden = ""
        m = re.search(r",\s*([^,]{3,40})$", actie.get_text(" ", strip=True))
        if m:
            reden = m.group(1).strip()
        cards.append({
            "player": link.get_text(strip=True),
            "player_id": speler_id(link.get("href")),
            "team": home_team["name"] if kant == "home" else away_team["name"],
            "minute": minuut,
            "added_time": extra_tijd,
            "type": soort,
            "reason": reden,
        })
    d.ok("cards", f"{len(cards)} stuks") if cards else d.leeg("cards", "geen kaarten / #sb-karten leeg")

    # ── Wissels ──────────────────────────────────────────────────────────────
    substitutions = []
    for li in s.select("#sb-wechsel li"):
        kant = kant_van(li)
        # sb-aktion-wechsel-ein/-aus zijn <span>, niet <div>: selecteer op class
        # zonder tagnaam. Het <li> bevat daarnaast portretlinks van beide spelers,
        # dus de richting mag alleen uit deze twee elementen komen.
        in_blok = li.select_one(".sb-aktion-wechsel-ein")
        uit_blok = li.select_one(".sb-aktion-wechsel-aus")
        in_link = in_blok.find("a", href=_SPELER_RE) if in_blok else None
        uit_link = uit_blok.find("a", href=_SPELER_RE) if uit_blok else None
        if not (in_link or uit_link):
            continue
        minuut, extra_tijd = lees_minuut(li.select_one("div.sb-aktion-uhr"))
        substitutions.append({
            "player_in": in_link.get_text(strip=True) if in_link else None,
            "player_in_id": speler_id(in_link.get("href")) if in_link else None,
            "player_out": uit_link.get_text(strip=True) if uit_link else None,
            "player_out_id": speler_id(uit_link.get("href")) if uit_link else None,
            "team": home_team["name"] if kant == "home" else away_team["name"],
            "minute": minuut,
            "added_time": extra_tijd,
        })
    d.ok("substitutions", f"{len(substitutions)} stuks") if substitutions \
        else d.gemist("substitutions", "#sb-wechsel li")

    # ── Opstelling (aparte subpagina) ────────────────────────────────────────
    lineup = {"home": [], "away": []}
    if lineup_html:
        lineup = parse_lineup(lineup_html, d)
    else:
        d.leeg("lineup", "subpagina niet opgehaald (--no-lineup)")

    record = {
        "id": match_id,
        "id_source": "transfermarkt",   # houdt namespaces gescheiden
        "date": datum_iso,
        "startTimestamp": ts,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "half_time": half_time,
        "penalty_shootout": penalty_shootout,
        "tournament": tournament,
        "tournament_id": tournament_id,
        # Transfermarkt nummert seizoenen op het startjaar: saison_id 2026 = 2026/27.
        "season": f"{tournament} {season_id}/{str(season_id + 1)[-2:]}".strip()
                  if season_id else "",
        "season_id": season_id,
        "round": ronde,
        "round_name": ronde_naam,
        "venue": {"name": venue_naam, "city": "", "id": venue_id},
        "attendance": attendance,
        "referee": referee,
        "source_team": home_team["name"],
        "goals": goals,
        "cards": cards,
        "substitutions": substitutions,
        "team_stats": {"home": {}, "away": {}},
        "lineup": lineup,
    }
    return record, d


def parse_lineup(html: str, d: Diag) -> dict:
    """Parse /spielbericht/aufstellung/spielbericht/{id} → starters + bank."""
    s = soep(html)
    lineup = {"home": [], "away": []}

    # De pagina toont vier boxen: basisopstelling thuis/uit, daarna bank thuis/uit.
    # De pagina toont de boxen in vaste volgorde: basisopstelling thuis, basis-
    # opstelling uit, reservebank thuis, reservebank uit. Tel per soort apart,
    # zodat de thuis/uit-toewijzing niet afhangt van de totale boxvolgorde.
    tellers = {"start": 0, "bank": 0}
    for box in s.select("div.box"):
        kop = box.select_one("h2, .table-header")
        koptekst = kop.get_text(" ", strip=True).lower() if kop else ""
        if not any(w in koptekst for w in
                   ("opstelling", "aufstellung", "line-up", "lineup",
                    "bank", "ersatzbank", "substitutes")):
            continue
        is_bank = any(w in koptekst for w in ("bank", "ersatzbank", "substitutes", "reserve"))
        soort = "bank" if is_bank else "start"
        if tellers[soort] > 1:      # meer dan twee boxen van een soort: onverwacht
            continue
        kant = "home" if tellers[soort] == 0 else "away"
        tellers[soort] += 1
        # Elke speler staat twee keer in de box (portret + naamlink), dus ontdubbel
        # op speler-ID en houd de link met een leesbare naam aan.
        for link in box.find_all("a", href=_SPELER_RE):
            naam = link.get_text(strip=True)
            pid = speler_id(link.get("href"))
            if not naam or not pid:
                continue
            if any(p["player_id"] == pid for p in lineup[kant]):
                continue
            lineup[kant].append({"player": naam, "player_id": pid, "starter": not is_bank})

    n_thuis, n_uit = len(lineup["home"]), len(lineup["away"])
    s_thuis = sum(1 for p in lineup["home"] if p["starter"])
    s_uit = sum(1 for p in lineup["away"] if p["starter"])
    if not (n_thuis + n_uit):
        d.gemist("lineup", "div.box met opstellingskop")
    elif not (n_thuis and n_uit):
        d.gemist("lineup", f"eenzijdig: {n_thuis} thuis / {n_uit} uit")
    elif s_thuis != 11 or s_uit != 11:
        # Elftal is per definitie 11; wijkt dat af, dan klopt de indeling niet.
        d.gemist("lineup", f"basis {s_thuis}/{s_uit}, verwacht 11/11")
    else:
        d.ok("lineup", f"thuis {s_thuis}+{n_thuis - s_thuis} / uit {s_uit}+{n_uit - s_uit}")
    return lineup


# ─── Spelerprofiel ───────────────────────────────────────────────────────────

def _lokale_tz():
    """Transfermarkt zet tijdstempels op lokale middernacht (CET/CEST)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Amsterdam")
    except Exception:
        return timezone.utc


CEAPI_TRANSFERS = "/ceapi/transferHistory/list/{id}"
CEAPI_MARKTWAARDE = "/ceapi/marketValueDevelopment/graph/{id}"


def haal_json(url: str, dump_naar: Path | None = None, naam: str = "data") -> dict | None:
    """Haalt een ceapi-endpoint op. Geeft None bij een fout i.p.v. te stoppen."""
    print(f"  → GET {url}")
    kop = {**HEADERS, "Accept": "application/json",
           "X-Requested-With": "XMLHttpRequest"}
    resp = None
    for poging in range(len(WACHT_NA_BLOKKADE) + 1):
        try:
            resp = _sessie.get(url, headers=kop, timeout=25, **_IMPERSONATE)
        except Exception as e:
            print(f"  ! {type(e).__name__}: {e}")
            return None
        if resp.status_code not in TIJDELIJKE_STATUS:
            break
        if poging >= len(WACHT_NA_BLOKKADE):
            break
        pauze = WACHT_NA_BLOKKADE[poging]
        print(f"  ! HTTP {resp.status_code} (tijdelijk), opnieuw over {pauze}s")
        time.sleep(pauze)
    if resp.status_code != 200:
        print(f"  ! HTTP {resp.status_code}")
        return None
    try:
        data = resp.json()
    except Exception:
        print("  ! antwoord is geen geldige JSON")
        return None
    if dump_naar:
        dump_naar.mkdir(parents=True, exist_ok=True)
        pad = dump_naar / f"{naam}.json"
        pad.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ JSON bewaard: {pad}")
    return data


def _kies_sleutel(obj: dict, *patronen: str) -> str | None:
    """Zoekt de eerste sleutel die op een patroon past; exacte match gaat voor."""
    for p in patronen:
        for k in obj:
            if re.fullmatch(p, k, re.I):
                return k
    for p in patronen:
        for k in obj:
            if re.search(p, k, re.I):
                return k
    return None


def parse_transfers_ceapi(data: dict, d: Diag) -> list:
    """
    Zet /ceapi/transferHistory/list/{id} om naar transferrecords.

    De buitenste vorm is bekend (transfers[] met from/to als clubobjecten),
    maar de sleutelnamen voor datum, seizoen en som kunnen wijzigen — die
    worden gedetecteerd en in het rapport benoemd.
    """
    rijen = (data or {}).get("transfers") or []
    if not rijen:
        d.leeg("transfers", "lege transfers-lijst")
        return []

    eerste = rijen[0]
    k_datum = _kies_sleutel(eerste, r"date", r"datum")
    k_seizoen = _kies_sleutel(eerste, r"season", r"saison")
    k_som = _kies_sleutel(eerste, r"^fee$", r"transferfee", r"fee", r"ablose")

    def club(entry, kant):
        blok = entry.get(kant)
        if isinstance(blok, dict):
            return blok.get("clubName") or blok.get("name") or ""
        return str(blok or "")

    transfers = []
    for r in rijen:
        som_ruw = r.get(k_som, "") if k_som else ""
        if isinstance(som_ruw, dict):
            som_ruw = som_ruw.get("value") or som_ruw.get("text") or ""
        transfers.append({
            "season": str(r.get(k_seizoen, "") if k_seizoen else ""),
            "date": str(r.get(k_datum, "") if k_datum else ""),
            "from": club(r, "from"),
            "to": club(r, "to"),
            "fee_raw": str(som_ruw),
            "fee": parse_bedrag(str(som_ruw)),
        })

    bedragen = [t["fee"] for t in transfers if t["fee"]]
    gebruikt = f"sleutels: datum={k_datum} seizoen={k_seizoen} som={k_som}"
    if bedragen:
        d.ok("transfers", f"{len(transfers)} stuks, hoogste € {max(bedragen):,}")
    else:
        d.ok("transfers", f"{len(transfers)} stuks, geen bedragen — {gebruikt}")
    return transfers


def parse_marktwaarde_ceapi(data: dict, d: Diag) -> tuple[int | None, list]:
    """
    Zet /ceapi/marketValueDevelopment/graph/{id} om naar (huidige waarde, historie).
    Elk punt heeft x (epoch ms), y (waarde in euro), verein en age.
    """
    punten = (data or {}).get("list") or []
    tz = _lokale_tz()
    historie = []
    for p in punten:
        iso = ""
        if isinstance(p.get("x"), (int, float)):
            # In UTC valt dit op de dag ervoor: x is lokale middernacht.
            iso = datetime.fromtimestamp(p["x"] / 1000, tz).strftime("%Y-%m-%d")
        historie.append({
            "date": iso or str(p.get("datum_mw", "")),
            "value": int(p["y"]) if isinstance(p.get("y"), (int, float)) else
                     parse_bedrag(str(p.get("mw", ""))),
            "club": p.get("verein", ""),
            "age": int(p["age"]) if str(p.get("age", "")).isdigit() else None,
        })
    huidig = parse_bedrag(str((data or {}).get("current", "")))
    if huidig is None and historie:
        huidig = historie[-1]["value"]

    if historie:
        eerste, laatst = historie[0], historie[-1]
        d.ok("market_value_history",
             f"{len(historie)} punten, {eerste['date']} € {eerste['value']:,} "
             f"→ {laatst['date']} € {laatst['value']:,}")
    else:
        d.leeg("market_value_history", "lege lijst in ceapi-antwoord")
    return huidig, historie


_MAANDEN = {"jan": 1, "feb": 2, "mrt": 3, "maa": 3, "apr": 4, "mei": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12}


def _datum_nl(tekst: str) -> str:
    """'23 sep. 1980 (45)' → '1980-09-23'. Geeft '' als er geen datum in staat."""
    m = re.search(r"(\d{1,2})\s*([a-z]{3})[a-z.]*\s*(\d{4})", tekst or "", re.I)
    if not m:
        return ""
    maand = _MAANDEN.get(m.group(2).lower()[:3])
    return f"{int(m.group(3)):04d}-{maand:02d}-{int(m.group(1)):02d}" if maand else ""


def _header_velden(s) -> dict:
    """
    Zet de data-header om naar {label: waarde}. De waarde uit
    span.data-header__content is soms '-' terwijl de tekst hem wel bevat
    ("Interlands/doelp.: 1 / 0"), dus splitsen we op de eerste dubbele punt.
    """
    velden = {}
    for item in s.select("li.data-header__label, span.data-header__label"):
        volledig = item.get_text(" ", strip=True)
        if ":" not in volledig:
            continue
        label, waarde = volledig.split(":", 1)
        label, waarde = label.strip().lower(), waarde.strip()
        if waarde and waarde != "-":
            velden[label] = waarde
    return velden


def parse_player(html: str, player_id: int, transfers_data: dict | None = None,
                 mv_data: dict | None = None) -> tuple[dict, Diag]:
    """
    Haalt profiel, marktwaarde, transfers en interlandcijfers op.

    Transfers en marktwaardehistorie staan niet in de HTML — ook niet op de
    subpagina's — maar worden door de frontend geladen via ceapi-endpoints.
    Geef die JSON mee; de profiel-HTML levert de rest.
    """
    s = soep(html)
    d = Diag()

    naam_el = s.select_one("h1.data-header__headline-wrapper") or s.select_one("h1")
    naam = re.sub(r"^#\d+\s*", "", naam_el.get_text(" ", strip=True)) if naam_el else ""
    d.ok("name", naam) if naam else d.gemist("name", "h1.data-header__headline-wrapper")

    velden = _header_velden(s)

    def zoek_label(*sleutels):
        for k, v in velden.items():
            if any(sl in k for sl in sleutels):
                return v
        return ""

    # ── Biografie (vult date_of_birth / nationality / position / height_cm) ──
    geboren = _datum_nl(zoek_label("geb.", "geboren", "birth"))
    d.ok("date_of_birth", geboren) if geboren else d.leeg("date_of_birth")
    nationaliteit = zoek_label("nationaliteit", "nationality", "staatsbürger")
    d.ok("nationality", nationaliteit) if nationaliteit else d.leeg("nationality")
    positie = zoek_label("positie", "position")
    d.ok("position", positie) if positie else d.leeg("position")
    lengte_ruw = zoek_label("lengte", "größe", "height")
    m = re.search(r"(\d)[,.](\d{2})", lengte_ruw or "")
    lengte = int(m.group(1)) * 100 + int(m.group(2)) if m else None
    d.ok("height_cm", lengte) if lengte else d.leeg("height_cm", lengte_ruw or "")

    # ── Interlands: staat als "Interlands/doelp.: 1 / 0" in één veld ─────────
    caps = goals_nt = None
    interland = zoek_label("interland", "länderspiele", "caps")
    if interland:
        m = re.search(r"(\d+)\s*/\s*(\d+)", interland)
        if m:
            caps, goals_nt = int(m.group(1)), int(m.group(2))
        else:
            caps = _eerste_getal(interland)
    d.ok("national_team_caps", caps) if caps is not None else d.leeg("national_team_caps")
    d.ok("national_team_goals", goals_nt) if goals_nt is not None \
        else d.leeg("national_team_goals")

    # ── Marktwaarde: huidige waarde + historie uit het ceapi-endpoint ────────
    historie = []
    market_value = None
    if mv_data is not None:
        market_value, historie = parse_marktwaarde_ceapi(mv_data, d)
    else:
        d.leeg("market_value_history", "ceapi niet opgehaald")

    if market_value is None:
        # Terugval op de profielpagina: die toont de huidige waarde wel.
        el = s.select_one("a.data-header__market-value-wrapper")
        if el and el.get_text(strip=True):
            market_value = parse_bedrag(el.get_text(" ", strip=True))
    if market_value is not None:
        d.ok("market_value", f"€ {market_value:,}")
    elif zoek_label("einde carrière", "karriereende"):
        d.leeg("market_value", "speler is gestopt — TM toont geen waarde")
    else:
        d.gemist("market_value", "niet in ceapi en niet op het profiel")

    # ── Transfers uit het ceapi-endpoint ─────────────────────────────────────
    if transfers_data is not None:
        transfers = parse_transfers_ceapi(transfers_data, d)
    else:
        transfers = []
        d.leeg("transfers", "ceapi niet opgehaald")

    record = {
        "id": player_id,
        "id_source": "transfermarkt",
        "name": naam,
        "date_of_birth": geboren,
        "nationality": nationaliteit,
        "position": positie,
        "height_cm": lengte,
        "market_value": market_value,
        "market_value_history": historie,
        "national_team_caps": caps,
        "national_team_goals": goals_nt,
        "transfers": transfers,
        "max_transfer_fee": max((t["fee"] for t in transfers if t["fee"]), default=None),
    }
    return record, d


# ─── Inspectiemodus ──────────────────────────────────────────────────────────

def _knip(tekst: str, n: int = 900) -> str:
    tekst = re.sub(r"\s+", " ", tekst or "").strip()
    return tekst if len(tekst) <= n else tekst[:n] + " …[afgekapt]"


def inspect(html: str, lineup_html: str | None = None):
    """
    Print de HTML-fragmenten rond de velden die de parser mist, zodat de
    selectors bijgesteld kunnen worden zonder de hele pagina te delen.
    """
    s = soep(html)

    def kop(titel):
        print(f"\n{'─' * 78}\n▼ {titel}\n{'─' * 78}")

    kop("0. Paginatitel en kruimelpad (mogelijke bron voor de competitie)")
    titel = s.find("title")
    print(f"  <title>: {_knip(titel.get_text(strip=True) if titel else '(geen)', 140)}")
    for sel in ("div.breadcrumb", ".breadcrumb", "nav.breadcrumb", "h1"):
        el = s.select_one(sel)
        if el:
            print(f"  {sel}: {_knip(el.get_text(' | ', strip=True), 140)}")

    kop("1. sb-datum (bron voor date / tournament / round)")
    blok = s.select_one("div.sb-datum") or s.select_one("div.sb-spieldaten")
    print(_knip(str(blok)) if blok else "  !! niet gevonden")

    kop("2. Datum-kandidaten: links met /datum/ of /aktuell/")
    treffers = [a.get("href") for a in s.find_all("a", href=re.compile(r"/datum/"))][:5]
    print("  " + ("\n  ".join(treffers) if treffers else "!! geen /datum/-links"))

    kop("3. Competitie-kandidaten: alle /wettbewerb/-links (tekst | title)")
    for a in s.find_all("a", href=_WETTBEWERB_RE)[:8]:
        img = a.find("img")
        print(f"  href={a.get('href','')[:58]}")
        print(f"     tekst={a.get_text(strip=True)!r} title={a.get('title','')!r} "
              f"img_alt={img.get('alt','') if img else '-'!r}")

    kop("4. sb-zusatzinfos (bron voor venue / attendance / referee)")
    extra = s.select_one("p.sb-zusatzinfos")
    if extra:
        print(f"  TEKST: {_knip(extra.get_text(' ', strip=True), 400)}")
        print(f"  HTML : {_knip(str(extra), 700)}")
    else:
        print("  !! p.sb-zusatzinfos niet gevonden")

    kop("5. Aanwezige sb-* id's op de pagina")
    ids = sorted({el.get("id") for el in s.find_all(id=True)
                  if str(el.get("id")).startswith("sb-")})
    print("  " + (", ".join(ids) if ids else "!! geen sb-* id's"))

    kop("6. Wissels: #sb-wechsel structuur")
    wechsel = s.select_one("#sb-wechsel")
    if not wechsel:
        kand = s.find_all(class_=re.compile(r"wechsel", re.I))[:3]
        print(f"  !! #sb-wechsel ontbreekt. Elementen met 'wechsel' in class: {len(kand)}")
        for el in kand:
            print(f"     <{el.name} class={el.get('class')}>")
    else:
        lis = wechsel.find_all("li")
        print(f"  #sb-wechsel gevonden, {len(lis)} <li>. Directe kinderen: "
              f"{[k.name for k in wechsel.find_all(recursive=False)][:6]}")
        doel = lis[0] if lis else wechsel
        print(f"  EERSTE ITEM: {_knip(str(doel), 900)}")

    kop("7. Doelpunten: #sb-tore eerste item (werkt al — ter vergelijking)")
    tore = s.select_one("#sb-tore li")
    print(_knip(str(tore), 600) if tore else "  !! niet gevonden")

    if lineup_html:
        kop("8. Opstellingspagina: alle box-koppen")
        ls = soep(lineup_html)
        for i, box in enumerate(ls.select("div.box")[:12]):
            k = box.select_one("h2, .table-header")
            n_spelers = len(box.find_all("a", href=_SPELER_RE))
            print(f"  [{i}] kop={_knip(k.get_text(' ', strip=True), 60)!r} "
                  f"spelerlinks={n_spelers}")
        kop("9. Opstelling: eerste formatie-/tabelcontainer")
        c = ls.select_one("div.responsive-table") or ls.select_one("div.aufstellung-vereinsseite")
        print(_knip(str(c), 700) if c else "  !! geen bekende opstellingscontainer")


def inspect_player(html: str, transfers_html: str | None = None,
                   mv_html: str | None = None):
    """Zelfde principe als inspect(), maar voor de velden op een spelerprofiel."""
    s = soep(html)

    def kop(titel):
        print(f"\n{'─' * 78}\n▼ {titel}\n{'─' * 78}")

    kop("1. Kop van de pagina (naam)")
    for sel in ("h1.data-header__headline-wrapper", "h1", ".data-header__headline-container"):
        el = s.select_one(sel)
        if el:
            print(f"  {sel} -> {_knip(el.get_text(' ', strip=True), 120)!r}")

    kop("2. Marktwaarde-kandidaten")
    for el in s.select("[class*='market-value'], [class*='marktwert'], [class*='market_value']")[:6]:
        print(f"  <{el.name} class={el.get('class')}>")
        print(f"     {_knip(el.get_text(' ', strip=True), 120)!r}")

    kop("3. data-header: alle label/waarde-paren")
    for li in s.select("li.data-header__label, span.data-header__label")[:14]:
        waarde = li.select_one("span.data-header__content")
        print(f"  {_knip(li.get_text(' ', strip=True), 70)!r}"
              f"  -> content={_knip(waarde.get_text(' ', strip=True), 40) if waarde else '-'!r}")

    kop("4. Transferhistorie: containers met 'transfer' in class")
    klassen = {}
    for el in s.find_all(class_=re.compile(r"transfer", re.I)):
        for c in el.get("class", []):
            if "transfer" in c.lower():
                klassen[c] = klassen.get(c, 0) + 1
    for c, n in sorted(klassen.items(), key=lambda x: -x[1])[:12]:
        print(f"  {n:>3}x  .{c}")
    if not klassen:
        print("  !! geen enkele class met 'transfer'")

    kop("5. Eerste transferrij, ruw")
    rij = s.select_one("div.tm-player-transfer-history-grid:not(.tm-player-transfer-history-grid--heading)")
    if not rij:
        kand = s.find_all(class_=re.compile(r"transfer.*(grid|row|item)", re.I))
        rij = kand[1] if len(kand) > 1 else (kand[0] if kand else None)
    print(_knip(str(rij), 900) if rij else "  !! geen transferrij gevonden")

    kop("6. Interlandcijfers: tekst rond 'interland'")
    tekst = s.get_text(" ", strip=True)
    for m in list(re.finditer(r"interland|länderspiele|caps|nationale? ploeg", tekst, re.I))[:4]:
        print(f"  …{_knip(tekst[max(0, m.start() - 60):m.start() + 90], 160)}…")

    kop("7. Scripts met marktwaardegrafiek (profielpagina)")
    for sc in s.find_all("script"):
        inhoud = sc.string or ""
        if re.search(r"marketValueDevelopment|highcharts|datum_mw", inhoud, re.I):
            print(f"  script ({len(inhoud)} tekens): {_knip(inhoud, 500)}")
            break
    else:
        print("  !! geen grafiekscript (staat op de /marktwertverlauf/-subpagina)")

    # ── Subpagina's: hier staan transfers en marktwaarde echt ────────────────
    if transfers_html:
        ts = soep(transfers_html)
        kop("8. SUBPAGINA transfers: classes met 'transfer'")
        klassen = {}
        for el in ts.find_all(class_=re.compile(r"transfer", re.I)):
            for c in el.get("class", []):
                if "transfer" in c.lower():
                    klassen[c] = klassen.get(c, 0) + 1
        for c, n in sorted(klassen.items(), key=lambda x: -x[1])[:14]:
            print(f"  {n:>3}x  .{c}")
        if not klassen:
            print("  !! geen classes met 'transfer' — mogelijk een tabel")
            for t in ts.select("table.items")[:1]:
                print(f"  table.items gevonden, {len(t.select('tr'))} rijen")

        kop("9. SUBPAGINA transfers: eerste datarij ruw")
        rijen = ts.select("div.grid.tm-player-transfer-history-grid") \
            or ts.select("table.items tr")
        doel = next((r for r in rijen
                     if "heading" not in " ".join(r.get("class", []))
                     and r.get_text(strip=True)), None)
        print(_knip(str(doel), 900) if doel else "  !! geen datarij gevonden")
    else:
        kop("8-9. SUBPAGINA transfers — niet opgehaald")

    if mv_html:
        ms = soep(mv_html)
        kop("10. SUBPAGINA marktwaarde: huidige waarde")
        for sel in (".tm-player-market-value-development__current-value",
                    ".data-header__market-value-wrapper",
                    "[class*='current-value']"):
            el = ms.select_one(sel)
            if el:
                print(f"  {sel} -> {_knip(el.get_text(' ', strip=True), 80)!r}")

        kop("11. SUBPAGINA marktwaarde: grafiekdata in script")
        for sc in ms.find_all("script"):
            inhoud = sc.string or ""
            if re.search(r"datum_mw|marketValue|highcharts", inhoud, re.I):
                treffer = re.search(r".{0,120}datum_mw.{0,200}", inhoud)
                print(f"  script ({len(inhoud)} tekens)")
                print(f"  fragment: {_knip(treffer.group(0) if treffer else inhoud, 400)}")
                break
        else:
            print("  !! geen grafiekdata — historie is dan niet scrapebaar uit HTML")
    else:
        kop("10-11. SUBPAGINA marktwaarde — niet opgehaald")


def probe_player(pid: int, dump_naar: Path | None = None):
    """
    Transfers en marktwaardehistorie staan niet in de server-HTML; de frontend
    laadt ze na. Deze probe test de kandidaat-endpoints en rapporteert per stuk
    de statuscode, het content-type en een fragment van de inhoud, zodat de
    juiste bron vastgesteld wordt zonder te gokken.
    """
    kandidaten = [
        ("transfers (ceapi JSON)",     f"{BASE}/ceapi/transferHistory/list/{pid}"),
        ("marktwaarde (ceapi JSON)",   f"{BASE}/ceapi/marketValueDevelopment/graph/{pid}"),
        ("marktwaarde (ceapi alt)",    f"{BASE}/ceapi/marketValueDevelopment/graph/player/{pid}"),
        ("transfers (per seizoen)",    f"{BASE}/speler/transfersnachsaison/spieler/{pid}"),
        ("prestaties (leistungsdaten)", f"{BASE}/speler/leistungsdaten/spieler/{pid}"),
    ]
    print(f"\n{'=' * 78}\n  ENDPOINT-PROBE voor speler {pid}\n{'=' * 78}")
    for naam, url in kandidaten:
        print(f"\n▼ {naam}\n  {url}")
        try:
            resp = _http.get(url, headers={**HEADERS, "Accept": "application/json, text/html, */*",
                                           "X-Requested-With": "XMLHttpRequest"},
                             timeout=25, **_IMPERSONATE)
        except Exception as e:
            print(f"  ✗ verzoek mislukt: {type(e).__name__}: {e}")
            continue
        ct = resp.headers.get("Content-Type", "?")
        body = resp.text or ""
        print(f"  status={resp.status_code}  type={ct}  lengte={len(body):,}")
        if resp.status_code != 200:
            continue
        if dump_naar:
            dump_naar.mkdir(parents=True, exist_ok=True)
            veilig = re.sub(r"[^a-z0-9]+", "_", naam.lower()).strip("_")
            ext = "json" if "json" in ct else "html"
            pad = dump_naar / f"probe_{pid}_{veilig}.{ext}"
            pad.write_text(body, encoding="utf-8")
            print(f"  ✓ bewaard: {pad}")
        if "json" in ct:
            try:
                data = json.loads(body)
                print(f"  JSON-sleutels: {list(data)[:12] if isinstance(data, dict) else f'lijst[{len(data)}]'}")
                print(f"  fragment: {_knip(json.dumps(data, ensure_ascii=False), 700)}")
            except Exception:
                print(f"  fragment (geen geldige JSON): {_knip(body, 400)}")
        else:
            ps = soep(body)
            klassen = {}
            for el in ps.find_all(class_=re.compile(r"transfer|market", re.I)):
                for c in el.get("class", []):
                    if re.search(r"transfer|market", c, re.I):
                        klassen[c] = klassen.get(c, 0) + 1
            print(f"  relevante classes: {sorted(klassen, key=lambda k: -klassen[k])[:8] or 'geen'}")
            print(f"  tabellen: {len(ps.select('table.items'))}x table.items")


# ─── Wat Transfermarkt structureel NIET heeft ────────────────────────────────

ONTBREEKT_OP_TM = [
    ("avg_rating",          "1855 spelers (62%)", "10 render-plekken + RatingBadge"),
    ("xg_total / xg",       "522 spelers (17%)",  "6 plekken + record highest_xg_match"),
    ("total_shots",         "1011 spelers (34%)", "PlayerDetail"),
    ("shots_on_target",     "1011 spelers (34%)", "PlayerDetail"),
    ("pass_accuracy_pct",   "—",                  "PlayerDetail"),
    ("key_passes",          "—",                  "alleen in data"),
    ("tackles",             "—",                  "PlayerDetail"),
    ("interceptions",       "—",                  "PlayerDetail"),
    ("duels_won / lost",    "—",                  "PlayerDetail"),
    ("fouls_committed",     "—",                  "alleen in data"),
    ("team_stats",          "180 wedstrijden",    "balbezit e.d."),
    ("shotmap",             "—",                  "niet in dashboard"),
]


def toon_gat():
    print(f"\n{'=' * 78}")
    print("  STRUCTUREEL GAT — deze velden bestaan niet op Transfermarkt")
    print(f"{'=' * 78}")
    print(f"  {'veld':<22} {'dekking nu':<20} gebruikt in")
    print(f"  {'-' * 22} {'-' * 20} {'-' * 30}")
    for veld, dekking, waar in ONTBREEKT_OP_TM:
        print(f"  {veld:<22} {dekking:<20} {waar}")
    print()
    print("  Goals, assists, kaarten, wissels, opstelling en minuten blijven wel")
    print("  overeind. minutes_played leidt sofascore_tracker.py:1115-1180 al af uit")
    print("  opstelling + wissels — die route werkt ongewijzigd voor TM-data.")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def haal_id(waarde: str, patroon: str) -> int:
    """Accepteert zowel een kaal ID als een volledige Transfermarkt-URL."""
    if waarde.isdigit():
        return int(waarde)
    m = re.search(patroon, waarde)
    if m:
        return int(m.group(1))
    raise SystemExit(f"  ✗ Kon geen ID halen uit: {waarde}")


# ─── Zelftest ────────────────────────────────────────────────────────────────

def _proefpagina(endstand, halbzeit, tore_standen, met_serie):
    """Bouwt een wedstrijdpagina na, met de opmaak zoals gemeten op TM."""
    tore = "".join(
        f'<li class="sb-aktion-heim"><div class="sb-aktion">'
        f'<div class="sb-aktion-uhr"><span class="sb-sprite-uhr-klein" '
        f'style="background-position: -36px -144px;"> </span></div>'
        f'<div class="sb-aktion-spielstand"><b>{st}</b></div>'
        f'<div class="sb-aktion-aktion">'
        f'<a class="wichtig" href="/x/leistungsdatendetails/spieler/{i + 1}">Speler{i + 1}</a>'
        f'</div></div></li>'
        for i, st in enumerate(tore_standen))
    serie = ('<div id="sb-elfmeterscheissen"><ul><li>penalty</li></ul></div>'
             if met_serie else "")
    return (
        '<html><head><title>Ajax - PSV, 30 apr. 2023 - KNVB Beker'
        ' - Wedstrijdverslag | Transfermarkt</title></head><body>'
        '<div class="sb-spieldaten"><p class="sb-datum hide-for-small"> Finale | '
        '<a href="/aktuell/waspassiertheute/aktuell/new/datum/2023-04-30">zo, 30-04-23 </a>'
        ' | 18:00 uur </p><div class="ergebnis-wrap"><div class="sb-ergebnis">'
        f'<div class="sb-endstand"> {endstand}<div class="sb-halbzeit">{halbzeit}</div>'
        '</div></div></div><p class="sb-zusatzinfos"><span class="hide-for-small">'
        '<a href="/stadion/stadion/verein/234/saison_id/2022">De Kuip</a> | '
        '<strong>40.650 toeschouwers</strong></span><strong>Scheidsrechter:</strong>'
        '<a href="/x/profil/schiedsrichter/1" title="D. Higler">D. Higler</a></p></div>'
        f'<div id="sb-tore"><ul>{tore}</ul></div>{serie}</body></html>')


def zelftest() -> int:
    """Rekent de wedstrijdparser na op uitgewerkte gevallen.

    Een gevuld veld is geen bewijs van een correct veld — dat is in dit project
    vijf keer gebleken. Deze gevallen hebben elk één juist antwoord.
    """
    fout = 0

    def check(oms, gekregen, verwacht):
        nonlocal fout
        goed = gekregen == verwacht
        fout += not goed
        extra = "" if goed else f"   (verwacht {verwacht}, kreeg {gekregen})"
        print(("  ok  " if goed else "  FOUT"), oms + extra)

    print("── strafschoppenserie ──")

    # De gemeten bekerfinale: TM schrijft "3:4 n.s." voor een wedstrijd die
    # 1-1 eindigde en met 2-3 strafschoppen werd beslist.
    r, _ = parse_match(_proefpagina("3:4", "n.s.", ["1:0", "1:1"], True), 4056454)
    check("bekerfinale: uitslag is de veldstand",
          (r["home_score"], r["away_score"]), (1, 1))
    check("strafschoppen apart vastgelegd",
          r["penalty_shootout"], {"home": 2, "away": 3})

    r, _ = parse_match(_proefpagina("4:5", "n.s.", [], True), 1)
    check("serie na 0-0: uitslag 0-0", (r["home_score"], r["away_score"]), (0, 0))
    check("serie na 0-0: strafschoppen 4-5",
          r["penalty_shootout"], {"home": 4, "away": 5})

    r, _ = parse_match(
        _proefpagina("4:1", "(2:1)", ["1:0", "2:0", "2:1", "3:1", "4:1"], False), 2)
    check("gewone wedstrijd: uitslag ongemoeid",
          (r["home_score"], r["away_score"]), (4, 1))
    check("gewone wedstrijd: geen strafschoppenveld", r["penalty_shootout"], None)

    r, _ = parse_match(
        _proefpagina("3:2", "n.v.", ["1:0", "1:1", "1:2", "2:2", "3:2"], False), 3)
    check("verlenging zonder serie: uitslag ongemoeid",
          (r["home_score"], r["away_score"]), (3, 2))

    # Een serie volgt op een gelijkspel. Klopt dat niet, dan is de aanname
    # onjuist en moet de parser dat melden in plaats van door te rekenen.
    _, diag = parse_match(_proefpagina("3:4", "n.s.", ["1:0", "2:0"], True), 4)
    check("ongerijmde serie wordt gemeld, niet gecorrigeerd",
          {rij[0]: rij[1] for rij in diag.rows}.get("score"), "GEMIST")

    print("\n── ruststand ──")
    r, diag = parse_match(_proefpagina("3:4", "n.s.", ["1:0", "1:1"], True), 5)
    check("'n.s.' is geen ruststand maar de afwezigheid ervan",
          {rij[0]: rij[1] for rij in diag.rows}.get("half_time"), "LEEG")
    r, diag = parse_match(
        _proefpagina("4:1", "(2:1)", ["1:0", "2:0", "2:1", "3:1", "4:1"], False), 6)
    check("gewone ruststand wordt gelezen",
          (r["half_time"]["home"], r["half_time"]["away"]), (2, 1))

    print(f"\n  {'alles goed' if not fout else str(fout) + ' FOUT'}")
    return fout


def main():
    p = argparse.ArgumentParser(
        description="Transfermarkt PoC — laat zien welke velden TM echt levert.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--match", help="spielbericht-ID of volledige URL")
    g.add_argument("--player", help="speler-ID of volledige URL")
    p.add_argument("--html", help="parse een lokaal opgeslagen HTML-bestand (geen netwerk)")
    p.add_argument("--lineup-html", help="lokaal opgeslagen opstellingspagina")
    p.add_argument("--transfers-json", help="lokaal opgeslagen ceapi-transfers JSON")
    p.add_argument("--mv-json", help="lokaal opgeslagen ceapi-marktwaarde JSON")
    p.add_argument("--dump", help="map om opgehaalde HTML in te bewaren")
    p.add_argument("--json", help="schrijf het resultaat als JSON naar dit pad")
    p.add_argument("--no-lineup", action="store_true", help="sla de opstellingspagina over")
    p.add_argument("--inspect", action="store_true",
                   help="print HTML-fragmenten rond gemiste velden i.p.v. te parsen")
    p.add_argument("--probe", action="store_true",
                   help="test welke endpoints transfers/marktwaarde leveren (alleen --player)")
    p.add_argument("--zelftest", action="store_true",
                   help="reken de wedstrijdparser na op uitgewerkte gevallen")
    if "--zelftest" in sys.argv:
        raise SystemExit(1 if zelftest() else 0)
    args = p.parse_args()

    dump = Path(args.dump) if args.dump else None

    if args.match:
        mid = haal_id(args.match, r"/spielbericht/(\d+)")
        print(f"\n  Transfermarkt PoC — wedstrijd {mid}")
        if args.html:
            html = Path(args.html).read_text(encoding="utf-8")
            print(f"  ← lokaal bestand: {args.html}")
        else:
            html = fetch(f"{BASE}/spielbericht/index/spielbericht/{mid}", dump, f"match_{mid}")

        lineup_html = None
        if args.lineup_html:
            lineup_html = Path(args.lineup_html).read_text(encoding="utf-8")
        elif not args.no_lineup and not args.html:
            try:
                lineup_html = fetch(
                    f"{BASE}/spielbericht/aufstellung/spielbericht/{mid}",
                    dump, f"lineup_{mid}")
            except SystemExit as e:
                print(f"  ! opstelling overgeslagen: {e}")

        if args.inspect:
            inspect(html, lineup_html)
            return

        record, d = parse_match(html, mid, lineup_html)
        d.rapport(f"WEDSTRIJD {mid} — {record['home_team']['name']} "
                  f"{record['home_score']}-{record['away_score']} {record['away_team']['name']}")
        toon_gat()
    else:
        pid = haal_id(args.player, r"/spieler/(\d+)")
        print(f"\n  Transfermarkt PoC — speler {pid}")

        if args.probe:
            probe_player(pid, dump)
            return

        if args.html:
            html = Path(args.html).read_text(encoding="utf-8")
            print(f"  ← lokaal bestand: {args.html}")
        else:
            # Een meegegeven URL bevat de echte slug; die is betrouwbaarder dan
            # zelf een URL samenstellen met een verzonnen slug.
            url = args.player if args.player.startswith("http") \
                else f"{BASE}/speler/profil/spieler/{pid}"
            html = fetch(url, dump, f"player_{pid}")

        # Transfers en marktwaarde komen uit de ceapi-endpoints, niet uit HTML.
        transfers_data = mv_data = None
        if args.transfers_json:
            transfers_data = json.loads(Path(args.transfers_json).read_text(encoding="utf-8"))
        if args.mv_json:
            mv_data = json.loads(Path(args.mv_json).read_text(encoding="utf-8"))
        if not args.html:
            if transfers_data is None:
                transfers_data = haal_json(BASE + CEAPI_TRANSFERS.format(id=pid),
                                           dump, f"player_{pid}_transfers")
            if mv_data is None:
                mv_data = haal_json(BASE + CEAPI_MARKTWAARDE.format(id=pid),
                                    dump, f"player_{pid}_mv")

        if args.inspect:
            inspect_player(html)
            return

        record, d = parse_player(html, pid, transfers_data, mv_data)
        d.rapport(f"SPELER {pid} — {record['name']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  ✓ JSON geschreven: {args.json}")
    else:
        print(f"\n  (geef --json <pad> om het volledige record weg te schrijven)")


if __name__ == "__main__":
    main()
