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

import argparse
import json
import re
import sys
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

def fetch(url: str, dump_naar: Path | None = None, naam: str = "page") -> str:
    """Haal een pagina op met browser-fingerprint. Geeft HTML-tekst terug."""
    if not _IMPERSONATE:
        print("  ! curl_cffi niet geinstalleerd — Cloudflare blokkeert waarschijnlijk.")
        print("    pip install curl_cffi")
    print(f"  → GET {url}")
    resp = _http.get(url, headers=HEADERS, timeout=30, **_IMPERSONATE)
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


def parse_bedrag(tekst: str) -> int | None:
    """'€ 1,20 mln' → 1200000 · '€ 850 dzd' → 850000 · 'gratis' → 0."""
    if not tekst:
        return None
    t = tekst.lower().replace("\xa0", " ").strip()
    if any(w in t for w in ("gratis", "free", "ablösefrei", "-")) and "€" not in t:
        return 0 if any(w in t for w in ("gratis", "free", "ablösefrei")) else None
    m = re.search(r"([\d.,]+)\s*(mln|mil|m|dzd|k|tsd)?", t)
    if not m:
        return None
    getal = m.group(1).replace(".", "").replace(",", ".")
    try:
        waarde = float(getal)
    except ValueError:
        return None
    eenheid = (m.group(2) or "").strip()
    if eenheid in ("mln", "mil", "m"):
        waarde *= 1_000_000
    elif eenheid in ("dzd", "k", "tsd"):
        waarde *= 1_000
    return int(waarde)


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
        d.gemist("half_time", "div.sb-halbzeit")

    # ── Competitie, speelronde, datum ────────────────────────────────────────
    datum_blok = s.select_one("div.sb-datum") or s.select_one("div.sb-spieldaten")
    tournament, tournament_id, ronde, datum_iso, ts = "", None, None, "", None
    if datum_blok:
        comp_link = datum_blok.find("a", href=_WETTBEWERB_RE)
        if comp_link:
            tournament = comp_link.get_text(strip=True) or comp_link.get("title", "")
            m = _WETTBEWERB_RE.search(comp_link.get("href", ""))
            tournament_id = m.group(1) if m else None
        blok_tekst = datum_blok.get_text(" ", strip=True)
        m = re.search(r"(\d{1,2})\.\s*(?:speeldag|Spieltag|matchday)", blok_tekst, re.I)
        if m:
            ronde = int(m.group(1))
        # Datum: dd-mm-yyyy of dd.mm.yyyy of yyyy-mm-dd
        m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})", blok_tekst)
        if m:
            dag, maand, jaar = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datum_iso = f"{jaar:04d}-{maand:02d}-{dag:02d}"
            ts = int(datetime(jaar, maand, dag, tzinfo=timezone.utc).timestamp())

    d.ok("tournament", tournament) if tournament else d.gemist("tournament", "a[href*=/wettbewerb/]")
    d.ok("tournament_id", tournament_id) if tournament_id else d.gemist("tournament_id")
    d.ok("round", ronde) if ronde else d.gemist("round", "'N. speeldag'")
    d.ok("date", datum_iso) if datum_iso else d.gemist("date", "datumregex in sb-datum")

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

    attendance = None
    m = re.search(r"(?:bezoekers|toeschouwers|zuschauer|attendance)\s*:?\s*([\d.\s]+)",
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
        assist_link = links[1] if len(links) > 1 else None
        goals.append({
            "player": links[0].get_text(strip=True),
            "player_id": speler_id(links[0].get("href")),
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
        if "tweede gele" in t or "gelb-rote" in t or "second yellow" in t:
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
        in_blok = li.select_one("div.sb-aktion-wechsel-ein")
        uit_blok = li.select_one("div.sb-aktion-wechsel-aus")
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
        "tournament": tournament,
        "tournament_id": tournament_id,
        "season": "",
        "season_id": None,
        "round": ronde,
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
    boxen = s.select("div.box")
    gevonden = 0
    for box in boxen:
        kop = box.select_one("h2, .table-header")
        koptekst = kop.get_text(" ", strip=True).lower() if kop else ""
        if not any(w in koptekst for w in
                   ("opstelling", "aufstellung", "line-up", "lineup", "bank", "ersatzbank", "substitutes")):
            continue
        is_bank = any(w in koptekst for w in ("bank", "ersatzbank", "substitutes", "reserve"))
        kant = "home" if gevonden % 2 == 0 else "away"
        for link in box.find_all("a", href=_SPELER_RE):
            naam = link.get_text(strip=True)
            pid = speler_id(link.get("href"))
            if not naam or not pid:
                continue
            if any(p["player_id"] == pid for p in lineup[kant]):
                continue
            lineup[kant].append({
                "player": naam,
                "player_id": pid,
                "starter": not is_bank,
            })
        gevonden += 1

    totaal = len(lineup["home"]) + len(lineup["away"])
    if totaal:
        d.ok("lineup", f"{len(lineup['home'])} thuis / {len(lineup['away'])} uit")
    else:
        d.gemist("lineup", "div.box met opstellingskop")
    return lineup


# ─── Spelerprofiel ───────────────────────────────────────────────────────────

def parse_player(html: str, player_id: int) -> tuple[dict, Diag]:
    """Haalt marktwaarde, transfers en interlandcijfers uit een spelerprofiel."""
    s = soep(html)
    d = Diag()
    tekst = s.get_text(" ", strip=True)

    naam_el = s.select_one("h1.data-header__headline-wrapper") or s.select_one("h1")
    naam = re.sub(r"^#\d+\s*", "", naam_el.get_text(" ", strip=True)) if naam_el else ""
    d.ok("name", naam) if naam else d.gemist("name", "h1.data-header__headline-wrapper")

    mv_el = s.select_one("a.data-header__market-value-wrapper")
    market_value = parse_bedrag(mv_el.get_text(" ", strip=True)) if mv_el else None
    if market_value is not None:
        d.ok("market_value", f"€ {market_value:,}")
    else:
        d.gemist("market_value", "a.data-header__market-value-wrapper")

    # Marktwaardehistorie zit in een Highcharts-JS-blok op de profielpagina.
    historie = []
    for script in s.find_all("script"):
        inhoud = script.string or ""
        if "marketValueDevelopment" in inhoud or "'data':[{'y'" in inhoud.replace('"', "'"):
            for m in re.finditer(r"'y'\s*:\s*(\d+).*?'datum_mw'\s*:\s*'([^']+)'", inhoud):
                historie.append({"value": int(m.group(1)), "date": m.group(2)})
            if historie:
                break
    if historie:
        d.ok("market_value_history", f"{len(historie)} datapunten")
    else:
        d.leeg("market_value_history", "Highcharts-blok niet gevonden (JS-afhankelijk)")

    # Interlands: staat als label/waarde in de data-header.
    caps = goals_nt = None
    for item in s.select("li.data-header__label"):
        label = item.get_text(" ", strip=True).lower()
        waarde_el = item.select_one("span.data-header__content")
        waarde = waarde_el.get_text(strip=True) if waarde_el else ""
        if "interland" in label or "länderspiele" in label or "caps" in label:
            caps = _eerste_getal(waarde)
        elif "doelpunt" in label or "tore" in label or "goals" in label:
            goals_nt = _eerste_getal(waarde)
    if caps is None:
        m = re.search(r"(?:interlands|länderspiele|caps)\s*:?\s*(\d+)", tekst, re.I)
        caps = int(m.group(1)) if m else None
    d.ok("national_team_caps", caps) if caps is not None else d.leeg("national_team_caps")
    d.ok("national_team_goals", goals_nt) if goals_nt is not None else d.leeg("national_team_goals")

    # Transfers staan in de transferhistorie-grid op de profielpagina.
    transfers = []
    for rij in s.select("div.tm-player-transfer-history-grid"):
        if "grid__header" in " ".join(rij.get("class", [])):
            continue
        def cel(suffix):
            el = rij.select_one(f"div.tm-player-transfer-history-grid__{suffix}")
            return el.get_text(" ", strip=True) if el else ""
        fee = cel("fee")
        if not (cel("old-club") or cel("new-club")):
            continue
        transfers.append({
            "season": cel("season"),
            "date": cel("date"),
            "from": cel("old-club"),
            "to": cel("new-club"),
            "fee_raw": fee,
            "fee": parse_bedrag(fee),
        })
    if transfers:
        bedragen = [t["fee"] for t in transfers if t["fee"]]
        d.ok("transfers", f"{len(transfers)} stuks, hoogste € {max(bedragen):,}" if bedragen
             else f"{len(transfers)} stuks, geen bedragen")
    else:
        d.gemist("transfers", "div.tm-player-transfer-history-grid")

    record = {
        "id": player_id,
        "id_source": "transfermarkt",
        "name": naam,
        "market_value": market_value,
        "market_value_history": historie,
        "national_team_caps": caps,
        "national_team_goals": goals_nt,
        "transfers": transfers,
        "max_transfer_fee": max((t["fee"] for t in transfers if t["fee"]), default=None),
    }
    return record, d


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


def main():
    p = argparse.ArgumentParser(
        description="Transfermarkt PoC — laat zien welke velden TM echt levert.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--match", help="spielbericht-ID of volledige URL")
    g.add_argument("--player", help="speler-ID of volledige URL")
    p.add_argument("--html", help="parse een lokaal opgeslagen HTML-bestand (geen netwerk)")
    p.add_argument("--lineup-html", help="lokaal opgeslagen opstellingspagina")
    p.add_argument("--dump", help="map om opgehaalde HTML in te bewaren")
    p.add_argument("--json", help="schrijf het resultaat als JSON naar dit pad")
    p.add_argument("--no-lineup", action="store_true", help="sla de opstellingspagina over")
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

        record, d = parse_match(html, mid, lineup_html)
        d.rapport(f"WEDSTRIJD {mid} — {record['home_team']['name']} "
                  f"{record['home_score']}-{record['away_score']} {record['away_team']['name']}")
        toon_gat()
    else:
        pid = haal_id(args.player, r"/spieler/(\d+)")
        print(f"\n  Transfermarkt PoC — speler {pid}")
        if args.html:
            html = Path(args.html).read_text(encoding="utf-8")
        else:
            html = fetch(f"{BASE}/speler/profil/spieler/{pid}", dump, f"player_{pid}")
        record, d = parse_player(html, pid)
        d.rapport(f"SPELER {pid} — {record['name']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  ✓ JSON geschreven: {args.json}")
    else:
        print(f"\n  (geef --json <pad> om het volledige record weg te schrijven)")


if __name__ == "__main__":
    main()
