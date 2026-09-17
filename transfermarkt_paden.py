#!/usr/bin/env python3
"""
Transfermarkt paden — waar de keten schrijft, vóór en na de omwisseling
======================================================================

Tijdens de migratie schreef de Transfermarkt-keten naar eigen bestanden met een
`_tm`-achtervoegsel. Dat was de hele afspraak: de Sofascore-data blijft staan tot
er vergeleken is, zodat de twee naast elkaar gelegd kunnen worden.

Na de omwisseling is die bescherming niet alleen overbodig maar schadelijk.
`selected_matches.json` is dan de Transfermarkt-lijst, maar de keten zou naar
`selected_matches_tm.json` blijven schrijven — en dan lopen er twee
wedstrijdlijsten uit elkaar. Het dashboard leest de ene, de keten vult de andere,
en een net toegevoegde wedstrijd staat in de verkeerde. Twee bestanden die
allebei de waarheid claimen is precies de fout die deze migratie moest oplossen.

Vandaar dit bestandje: één plek die zegt of de omwisseling gebeurd is, en drie
paden die zich daarnaar voegen. Waaraan te zien is dat het gebeurd is? Aan de
export zelf — die schrijft zijn eigen herkomst mee in `source`. Er is dus geen
instelling die iemand kan vergeten om te zetten; de data zegt het zelf.
"""

from __future__ import annotations

import json
from pathlib import Path

SELECTED = Path("data/selected_matches.json")
SELECTED_TM = Path("data/selected_matches_tm.json")
DASHBOARD = Path("data/dashboard_data.json")
DASHBOARD_TM = Path("data/dashboard_data_tm.json")


def bron_van(pad: Path = DASHBOARD) -> str:
    """Van welke bron komt de export die het dashboard nu leest?

    Een export zonder `source` is van vóór de Transfermarkt-keten en dus van
    Sofascore. Een onleesbaar bestand telt ook als Sofascore: dan vooral niets
    overschrijven.
    """
    if not pad.exists():
        return "sofascore"
    try:
        return json.loads(pad.read_text("utf-8")).get("source") or "sofascore"
    except (json.JSONDecodeError, OSError):
        return "sofascore"


def omgewisseld(pad: Path = DASHBOARD) -> bool:
    return bron_van(pad) == "transfermarkt"


def wedstrijden(pad: Path = DASHBOARD) -> Path:
    """Het bestand met de opgehaalde wedstrijden, waar de keten op draait."""
    return SELECTED if omgewisseld(pad) else SELECTED_TM


def dashboard(pad: Path = DASHBOARD) -> Path:
    """Het bestand dat het dashboard inleest."""
    return DASHBOARD if omgewisseld(pad) else DASHBOARD_TM


# ─── Zelftest ────────────────────────────────────────────────────────────────

def zelftest() -> int:
    import tempfile
    goed = fout = 0

    def toets(wat, kreeg, verwacht):
        nonlocal goed, fout
        if kreeg == verwacht:
            goed += 1
            print(f"  ✓ {wat}")
        else:
            fout += 1
            print(f"  ✗ {wat}\n      kreeg:    {kreeg!r}\n      verwacht: {verwacht!r}")

    print("── welke bron ──")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        weg = tmp / "bestaat-niet.json"
        toets("zonder export is het nog Sofascore", bron_van(weg), "sofascore")
        toets("en dus niet omgewisseld", omgewisseld(weg), False)

        sofa = tmp / "sofa.json"
        sofa.write_text('{"total_matches": 180}')
        toets("een export zonder source is van vóór de keten",
              bron_van(sofa), "sofascore")

        tm = tmp / "tm.json"
        tm.write_text('{"source": "transfermarkt", "total_matches": 165}')
        toets("een export die zichzelf Transfermarkt noemt", bron_van(tm),
              "transfermarkt")
        toets("die is omgewisseld", omgewisseld(tm), True)

        stuk = tmp / "stuk.json"
        stuk.write_text("{dit is geen json")
        toets("een onleesbare export overschrijft niets", omgewisseld(stuk), False)

        leeg = tmp / "leeg.json"
        leeg.write_text('{"source": null}')
        toets("een lege source telt als Sofascore", bron_van(leeg), "sofascore")

    print("\n── welke bestanden ──")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        sofa, tm = tmp / "s.json", tmp / "t.json"
        sofa.write_text('{"total_matches": 180}')
        tm.write_text('{"source": "transfermarkt"}')

        toets("vóór de omwisseling schrijft de keten naast Sofascore",
              (wedstrijden(sofa), dashboard(sofa)), (SELECTED_TM, DASHBOARD_TM))
        toets("erna schrijft hij de echte bestanden",
              (wedstrijden(tm), dashboard(tm)), (SELECTED, DASHBOARD))
        # De kern: ná de omwisseling mag er geen tweede wedstrijdlijst meer zijn.
        toets("er is dan nog maar één wedstrijdlijst",
              wedstrijden(tm) != SELECTED_TM, True)

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} fout, {goed} goed")
    return 1 if fout else 0


if __name__ == "__main__":
    raise SystemExit(zelftest())
