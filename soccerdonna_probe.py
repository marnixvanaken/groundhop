#!/usr/bin/env python3
"""
Soccerdonna verkennen — heeft die site dezelfde vorm als Transfermarkt?
======================================================================

Vier vrouwenwedstrijden vielen buiten de migratie: Transfermarkt levert ze niet
via de snelzoekfunctie. Soccerdonna dekt vrouwenvoetbal en hoort tot dezelfde
familie sites, dus de vraag is of de parser die we al hebben daar ook werkt.

Deze module beantwoordt die vraag en doet verder niets. Hij schrijft niet in
data/, hij koppelt niets, hij voegt geen wedstrijd toe. Hij meet alleen, want
een parser bouwen op een aanname over de HTML is precies hoe je een stille fout
maakt — en de `sb-*`-klassen waar `parse_match` op steunt zijn Transfermarkts
eigen CSS-namen, geen webstandaard.

Geef hem een URL uit je browser; de padvormen van Soccerdonna raden zou dezelfde
fout zijn als de markup raden.

Gebruik
-------
    python3 soccerdonna_probe.py https://www.soccerdonna.de/...
    python3 soccerdonna_probe.py --html bewaard.html
    python3 soccerdonna_probe.py URL --dump      # bewaar de HTML erbij
    python3 soccerdonna_probe.py --zelftest
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from transfermarkt_poc import soep

DUMP = Path("html_dump")

# De klassen waar transfermarkt_poc.parse_match op steunt. Ontbreken ze, dan is
# de parser daar niet bruikbaar — hoe erg de pagina er ook hetzelfde uitziet.
SB_MARKERS = [
    "sb-team", "sb-heim", "sb-gast", "sb-vereinslink", "sb-endstand",
    "sb-halbzeit", "sb-datum", "sb-spieldaten", "sb-zusatzinfos",
    "sb-tore", "sb-wechsel", "sb-karten", "sb-aktion", "sb-aktion-uhr",
    "sb-aktion-aktion", "sb-aktion-spielstand", "sb-aktion-wechsel-ein",
    "sb-aktion-wechsel-aus", "sb-elfmeterscheissen",
]

# De ID-families uit de URL's. Dit zegt of de identiteitssleutels hetzelfde
# heten, los van de opmaak.
URL_FAMILIES = {
    "speler": re.compile(r"/spieler/(\d+)"),
    "club": re.compile(r"/verein/(\d+)"),
    "wedstrijd": re.compile(r"/spielbericht/(\d+)"),
    "competitie": re.compile(r"/wettbewerb/([A-Za-z0-9]+)"),
}


def tel_markers(html: str) -> dict[str, int]:
    """Hoe vaak komt elke Transfermarkt-klasse voor?

    Op de tekst tellen en niet via een CSS-selector, want een klasse kan in een
    attribuut staan dat BeautifulSoup anders leest dan de browser. Ruw tellen
    geeft hier het eerlijkste beeld: nul is nul.
    """
    return {m: len(re.findall(rf'\b{re.escape(m)}\b', html)) for m in SB_MARKERS}


def tel_families(html: str) -> dict[str, int]:
    """Hoeveel verschillende ID's per URL-familie staan er op deze pagina?"""
    return {naam: len(set(p.findall(html))) for naam, p in URL_FAMILIES.items()}


def oordeel(markers: dict[str, int]) -> tuple[str, str]:
    """Wat betekent deze meting voor de bestaande parser?"""
    gevonden = sum(1 for n in markers.values() if n)
    totaal = len(markers)
    if gevonden == 0:
        return ("✗", "Geen enkele Transfermarkt-klasse. De parser is hier niet "
                     "bruikbaar; dit vraagt een eigen parser.")
    if gevonden < totaal // 2:
        return ("▼", f"Maar {gevonden} van de {totaal} klassen. De pagina lijkt "
                     f"erop maar is anders opgebouwd; grotendeels nieuw werk.")
    if gevonden < totaal:
        return ("·", f"{gevonden} van de {totaal} klassen. De parser komt een "
                     f"eind, maar de ontbrekende velden moeten apart.")
    return ("✓", "Alle klassen aanwezig. De parser is waarschijnlijk vrijwel "
                 "ongewijzigd bruikbaar.")


def rapporteer(html: str, herkomst: str) -> int:
    """Print wat deze pagina is en of onze parser er iets mee kan."""
    s = soep(html)
    titel = (s.title.get_text(strip=True) if s.title else "(geen titel)")
    print(f"\n{'=' * 78}\n  {herkomst}\n{'=' * 78}")
    print(f"  titel:   {titel}")
    print(f"  omvang:  {len(html):,} tekens")

    families = tel_families(html)
    print(f"\n  ── ID-families in de URL's ──")
    for naam, n in families.items():
        print(f"    {naam:<12} {n:>4} verschillende ID's"
              f"{'' if n else '   (niet gevonden)'}")

    markers = tel_markers(html)
    aanwezig = {m: n for m, n in markers.items() if n}
    print(f"\n  ── Transfermarkt-klassen waar onze parser op steunt ──")
    if aanwezig:
        for m, n in sorted(aanwezig.items(), key=lambda x: -x[1]):
            print(f"    ✓ {m:<24} {n:>4}×")
    ontbreekt = [m for m, n in markers.items() if not n]
    if ontbreekt:
        print(f"    ✗ ontbreekt: {', '.join(ontbreekt)}")

    teken, uitleg = oordeel(markers)
    print(f"\n  {teken} {uitleg}")

    # Ziet het eruit als een wedstrijdverslag? Dan is de eerlijkste toets: laat
    # de echte parser zijn gang gaan en lees zijn eigen diagnose. Die weet
    # preciezer dan welke gok ook welk veld hij niet vond.
    if families["wedstrijd"] or families["club"] >= 2:
        print(f"\n  ── de echte parser erop losgelaten ──")
        try:
            from transfermarkt_poc import parse_match
            record, diag = parse_match(html, 0)
            diag.rapport("parse_match op deze pagina")
            gemist = [r[0] for r in diag.rows if r[1] == "GEMIST"]
            if gemist:
                print(f"\n  Niet gevonden: {', '.join(gemist)}")
        except Exception as e:
            print(f"    ✗ parse_match liep vast: {type(e).__name__}: {e}")
            print(f"      Dat is op zichzelf een antwoord: niet herbruikbaar.")
    return 0


# ─── Zelftest ────────────────────────────────────────────────────────────────

def zelftest() -> int:
    goed = fout = 0

    def toets(wat, kreeg, verwacht):
        nonlocal goed, fout
        if kreeg == verwacht:
            goed += 1
            print(f"  ✓ {wat}")
        else:
            fout += 1
            print(f"  ✗ {wat}\n      kreeg:    {kreeg!r}\n      verwacht: {verwacht!r}")

    print("── klassen tellen ──")
    m = tel_markers('<div class="sb-team sb-heim"><a class="sb-vereinslink">x</a></div>')
    toets("aanwezige klassen worden geteld",
          (m["sb-team"], m["sb-heim"], m["sb-vereinslink"]), (1, 1, 1))
    toets("afwezige klassen tellen nul", m["sb-endstand"], 0)
    # Een deelwoord mag niet meetellen: 'sb-teams' is 'sb-team' niet.
    toets("een langere klassenaam telt niet mee als de korte",
          tel_markers('<div class="sb-teamgroep">')["sb-team"], 0)

    print("\n── ID-families ──")
    f = tel_families('<a href="/x/spieler/123"></a><a href="/y/spieler/123"></a>'
                     '<a href="/z/verein/9"></a>')
    toets("hetzelfde speler-ID telt één keer", f["speler"], 1)
    toets("een club-ID wordt gezien", f["club"], 1)
    toets("een ontbrekende familie is nul", f["wedstrijd"], 0)

    print("\n── het oordeel ──")
    niets = {m: 0 for m in SB_MARKERS}
    toets("zonder klassen: niet bruikbaar", oordeel(niets)[0], "✗")
    alles = {m: 1 for m in SB_MARKERS}
    toets("met alle klassen: waarschijnlijk bruikbaar", oordeel(alles)[0], "✓")
    paar = dict(niets)
    paar["sb-team"] = paar["sb-heim"] = 1
    toets("met een handvol: grotendeels nieuw werk", oordeel(paar)[0], "▼")
    bijna = {m: 1 for m in SB_MARKERS}
    bijna["sb-elfmeterscheissen"] = 0
    toets("met één gat: komt een eind", oordeel(bijna)[0], "·")

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} fout, {goed} goed")
    return 1 if fout else 0


def main():
    p = argparse.ArgumentParser(
        description="Kijk of Soccerdonna dezelfde vorm heeft als Transfermarkt")
    p.add_argument("url", nargs="*", help="een of meer URL's uit je browser")
    p.add_argument("--html", metavar="BESTAND",
                   help="een bewaarde pagina in plaats van een URL")
    p.add_argument("--dump", action="store_true",
                   help=f"bewaar de opgehaalde HTML in {DUMP}/")
    p.add_argument("--zelftest", action="store_true")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    if args.html:
        pad = Path(args.html)
        if not pad.exists():
            raise SystemExit(f"  {pad} bestaat niet")
        raise SystemExit(rapporteer(pad.read_text("utf-8", errors="replace"), str(pad)))

    if not args.url:
        p.print_help()
        print("\n  Geen URL meegegeven. Open een wedstrijdverslag op soccerdonna.de")
        print("  en plak die URL hierachter; dan meet deze module of onze parser")
        print("  er iets mee kan.")
        raise SystemExit(2)

    from transfermarkt_poc import fetch
    uit = 0
    for url in args.url:
        try:
            html = fetch(url, DUMP if args.dump else None,
                         re.sub(r"\W+", "-", url)[-60:])
        except SystemExit as e:
            print(f"\n  ✗ {url}\n    {e}")
            uit = 1
            continue
        uit |= rapporteer(html, url)
    raise SystemExit(uit)


if __name__ == "__main__":
    main()
