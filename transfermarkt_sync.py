#!/usr/bin/env python3
"""
Transfermarkt sync — haal de gekoppelde wedstrijden op
=====================================================

Leest data/tm_match_map.json en haalt voor elke koppeling het wedstrijdrapport
plus de opstelling op. Het resultaat komt in data/selected_matches_tm.json, in
exact het schema van selected_matches.json.

Het originele selected_matches.json wordt NIET aangeraakt. Zolang de migratie
niet af is blijft dat de werkende bron, en kun je de twee naast elkaar leggen.

Elke wedstrijd wordt na het parsen gecachet in data/tm_match_cache/, zodat een
onderbroken of herhaalde run niet opnieuw gaat downloaden. Wissen van die map
forceert een verse ophaal.

Gebruik
-------
    python3 transfermarkt_sync.py              # alles wat nog niet gecachet is
    python3 transfermarkt_sync.py --limit 5    # eerst een handvol proberen
    python3 transfermarkt_sync.py --force      # negeer de cache
    python3 transfermarkt_sync.py --rapport    # alleen de stand, zonder ophalen
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from transfermarkt_poc import BASE, fetch, parse_match

SELECTED = Path("data/selected_matches.json")
MATCH_MAP = Path("data/tm_match_map.json")
UITGESTELD = Path("data/tm_uitgesteld.json")
CACHE = Path("data/tm_match_cache")
UITVOER = Path("data/selected_matches_tm.json")

MIN_DELAY, MAX_DELAY = 2.0, 4.0

# Velden die het dashboard gebruikt en die we per wedstrijd willen tellen, om
# na afloop te kunnen zeggen wat de overstap concreet heeft opgeleverd.
# `round` is bij Transfermarkt vaak leeg bij bekerduels: daar staat een fase
# ("Groepsfase", "Achtste finale") in plaats van een nummer, en die komt in
# `round_name` terecht. Beide velden tellen mee, anders leest het rapport een
# betere weergave als verlies. Het dashboard toont `round` overigens alleen bij
# zoekresultaten uit de live Sofascore-API (dashboard.html:1604), nooit vanuit
# een opgeslagen wedstrijd.
TELVELDEN = ["date", "tournament", "round", "round_name", "venue", "attendance",
             "referee", "goals", "cards", "substitutions", "lineup"]


def wacht():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def gevuld(record: dict, veld: str) -> bool:
    """Is dit veld daadwerkelijk gevuld? Lege lijsten en dicts tellen niet mee."""
    waarde = record.get(veld)
    if veld == "venue":
        return bool((waarde or {}).get("name"))
    if veld == "referee":
        return bool((waarde or {}).get("name"))
    if veld == "lineup":
        return bool((waarde or {}).get("home")) and bool((waarde or {}).get("away"))
    if isinstance(waarde, (list, dict)):
        return bool(waarde)
    return waarde not in (None, "", 0)


def haal_wedstrijd(tm_id: int, force: bool = False) -> dict | None:
    """Haalt en parst één wedstrijd. Gebruikt de cache tenzij --force."""
    CACHE.mkdir(parents=True, exist_ok=True)
    pad = CACHE / f"{tm_id}.json"
    if pad.exists() and not force:
        return json.loads(pad.read_text("utf-8"))

    try:
        html = fetch(f"{BASE}/spielbericht/index/spielbericht/{tm_id}")
        wacht()
        try:
            lineup_html = fetch(f"{BASE}/spielbericht/aufstellung/spielbericht/{tm_id}")
        except SystemExit:
            lineup_html = None      # opstelling ontbreekt: de rest blijft bruikbaar
    except SystemExit as e:
        print(f"    ✗ ophalen mislukt: {e}")
        return None

    try:
        record, diag = parse_match(html, tm_id, lineup_html)
    except Exception as e:
        # Een parserfout op één wedstrijd mag de andere 163 niet meenemen.
        print(f"    ✗ parsen mislukt: {type(e).__name__}: {e}")
        return None
    gemist = [r[0] for r in diag.rows if r[1] == "GEMIST"]
    record["_gemist"] = gemist
    pad.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def rapporteer(records: list[dict], mapping: dict, origineel: list[dict]):
    """Vergelijkt de opbrengst met de bestaande data."""
    n = len(records)
    print(f"\n{'=' * 78}\n  OPBRENGST — {n} wedstrijden opgehaald\n{'=' * 78}")
    if not n:
        return

    oud = {str(m["id"]): m for m in origineel}
    # Welke Sofascore-wedstrijd hoort bij welke TM-wedstrijd?
    tm_naar_sofa = {str(v["tm_match_id"]): k for k, v in mapping.items()}

    print(f"  {'veld':<16} {'Transfermarkt':>16}   {'was (Sofascore)':>16}")
    print(f"  {'-' * 16} {'-' * 16}   {'-' * 16}")
    for veld in TELVELDEN:
        nieuw = sum(1 for r in records if gevuld(r, veld))
        oud_n = 0
        for r in records:
            sofa_id = tm_naar_sofa.get(str(r["id"]))
            if sofa_id and sofa_id in oud and gevuld(oud[sofa_id], veld):
                oud_n += 1
        pijl = "  ↑" if nieuw > oud_n else ("  ↓" if nieuw < oud_n else "   ")
        print(f"  {veld:<16} {nieuw:>7} / {n:<6} {pijl} {oud_n:>7} / {n}")

    problemen = [r for r in records if r.get("_gemist")]
    if problemen:
        print(f"\n  ▼ {len(problemen)} wedstrijden met gemiste velden:")
        for r in problemen[:10]:
            print(f"    {r.get('date', '?')}  {r['home_team']['name']} - "
                  f"{r['away_team']['name']}: {', '.join(r['_gemist'])}")
        if len(problemen) > 10:
            print(f"    ... en nog {len(problemen) - 10}")
    else:
        print(f"\n  Geen enkel gemist veld.")


def main():
    p = argparse.ArgumentParser(description="Haal de gekoppelde wedstrijden op")
    p.add_argument("--limit", type=int, help="stop na zoveel wedstrijden")
    p.add_argument("--force", action="store_true", help="negeer de cache")
    p.add_argument("--rapport", action="store_true",
                   help="toon alleen de stand, haal niets op")
    args = p.parse_args()

    if not MATCH_MAP.exists():
        raise SystemExit(f"  {MATCH_MAP} ontbreekt — draai eerst transfermarkt_map.py --map")
    mapping = json.loads(MATCH_MAP.read_text("utf-8"))
    origineel = json.loads(SELECTED.read_text("utf-8"))
    print(f"  {len(mapping)} koppelingen in {MATCH_MAP}")

    if UITGESTELD.exists():
        uit = json.loads(UITGESTELD.read_text("utf-8"))
        print(f"  {len(uit)} wedstrijden uitgesteld (zie {UITGESTELD})")

    CACHE.mkdir(parents=True, exist_ok=True)
    gecachet = {p.stem for p in CACHE.glob("*.json")}
    te_doen = [(k, v) for k, v in mapping.items()
               if args.force or str(v["tm_match_id"]) not in gecachet]
    print(f"  {len(gecachet)} al gecachet, {len(te_doen)} te doen")

    if not args.rapport and te_doen:
        if args.limit:
            te_doen = te_doen[:args.limit]
            print(f"  beperkt tot {len(te_doen)}")
        print()
        mislukt = []
        for i, (sofa_id, info) in enumerate(te_doen, 1):
            print(f"  [{i}/{len(te_doen)}] {info['date']}  {info['sofascore_label']}")
            if haal_wedstrijd(info["tm_match_id"], args.force) is None:
                mislukt.append(f"{info['date']}  {info['sofascore_label']}")
            wacht()
        if mislukt:
            print(f"\n  ▼ {len(mislukt)} wedstrijden niet opgehaald — draai opnieuw,")
            print(f"    de rest zit in de cache en wordt overgeslagen:")
            for r in mislukt:
                print(f"    {r}")

    # Alles wat in de cache zit en in de mapping voorkomt, wordt uitvoer.
    wil = {str(v["tm_match_id"]) for v in mapping.values()}
    records = []
    for pad in sorted(CACHE.glob("*.json")):
        if pad.stem in wil:
            records.append(json.loads(pad.read_text("utf-8")))
    records.sort(key=lambda r: r.get("date") or "")

    rapporteer(records, mapping, origineel)

    # Het zoektabblad in het dashboard zoekt bij Sofascore en markeert een
    # resultaat als "al opgeslagen" door het event-ID te vergelijken met de
    # opgeslagen wedstrijden. Een Transfermarkt-record draagt een TM-ID, dus dat
    # zou na de overstap op niets meer matchen en zou elke wedstrijd die je al
    # hebt opnieuw aanbieden. De koppeling die we toch al hebben lost dat op:
    # we schrijven het Sofascore-ID mee, als herkomst, niet als sleutel.
    tm_naar_sofa = {str(v["tm_match_id"]): int(k) for k, v in mapping.items()}
    schoon = []
    for r in records:
        rec = {k: v for k, v in r.items() if not k.startswith("_")}
        sofa = tm_naar_sofa.get(str(r["id"]))
        if sofa is not None:
            rec["sofascore_id"] = sofa
        schoon.append(rec)
    UITVOER.write_text(json.dumps(schoon, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  ✓ {UITVOER} geschreven ({len(schoon)} wedstrijden)")
    print(f"    {SELECTED} is ongewijzigd — vergelijk eerst, vervang daarna.")


if __name__ == "__main__":
    main()
