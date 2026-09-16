#!/usr/bin/env python3
"""
Transfermarkt vergelijk — leg de nieuwe export naast de oude, record voor record
================================================================================

De eerste versie van deze module noemde 1020 punten om naar te kijken. Bijna
allemaal onzin: 'Gofferstadion' tegen 'Goffertstadion', 'PSV Eindhoven' tegen
'PSV', 'Eredivisie 10/11' tegen 'Eredivisie 2010/11'. Twee bronnen die dezelfde
wedstrijd beschrijven spellen alles anders — dat is geen tegenspraak, dat is
vertaling. En de regel "niets mag omhoog" klopte niet: de oude export mist bij
179 van de 180 wedstrijden de opstelling, dus zijn de minuten daar onvolledig.
Méér minuten in de nieuwe data is winst, geen dubbeltelling.

Wat overblijft is wél de moeite waard, en deze module scheidt het in vieren:

  1. TEGENSPRAAK — dezelfde wedstrijd, een andere datum of een andere uitslag.
     Hier kan maar één van de twee gelijk hebben. Dit zijn de enige regels waar
     je echt naar moet kijken.

  2. VERTALING — dezelfde zaak, een andere naam. Afgeleid uit de gekoppelde
     wedstrijden zelf: als in wedstrijd X het stadion vroeger 'Gofferstadion'
     heette en nu 'Goffertstadion', dan is dat één naamwissel, geen fout. Wat
     hier wél opvalt: een oude naam die in twee nieuwe namen uiteenvalt.

  3. DEKKING — wat de nieuwe bron erbij heeft, en wat hij kwijtraakt.

  4. SPELERS — hoeveel er vervallen, hoeveel erbij komen, en of de doelpunten
     van de spelers optellen tot de eindstanden. Dat laatste is de echte proef
     op de som: een export waarin die twee niet kloppen telt iets verkeerd.

Deze module schrijft niets. Hij leest twee bestanden en praat.

Gebruik
-------
    python3 transfermarkt_vergelijk.py            # het hele rapport
    python3 transfermarkt_vergelijk.py --alles    # zonder afkappen op 15 regels
    python3 transfermarkt_vergelijk.py --zelftest # de vergelijking zelf narekenen
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

OUD = Path("data/dashboard_data.json")
NIEUW = Path("data/dashboard_data_tm.json")
UITGESTELD = Path("data/tm_uitgesteld.json")

TOON = 15  # regels per lijst, tenzij --alles


# ─── koppelen ────────────────────────────────────────────────────────────────

def label(w: dict) -> str:
    """Thuis - uit, zoals het in het dashboard staat."""
    return (f"{(w.get('home_team') or {}).get('name', '?')} - "
            f"{(w.get('away_team') or {}).get('name', '?')}")


def datumsleutel(w: dict) -> tuple:
    """Datum plus beide clubnamen. Twee bronnen kunnen andere ids geven aan
    dezelfde wedstrijd, maar niet een andere datum aan dezelfde twee clubs."""
    return (w.get("date"), label(w))


def koppel_wedstrijden(oud: list[dict], nieuw: list[dict]) -> tuple[list, list, list]:
    """Koppelt op sofascore_id, en anders op datum-plus-clubs.

    De sync schrijft sofascore_id mee als herkomst, dus de meeste wedstrijden
    koppelen daarop. De koppeling op datum is er voor de wedstrijd die alleen in
    de export bestond en die dus geen betrouwbaar id meekreeg.
    """
    per_id = {w["id"]: w for w in oud if w.get("id") is not None}
    per_datum = {}
    for w in oud:
        per_datum.setdefault(datumsleutel(w), w)

    paren, alleen_nieuw = [], []
    gebruikt = set()
    for n in nieuw:
        o = per_id.get(n.get("sofascore_id"))
        if o is None:
            o = per_datum.get(datumsleutel(n))
        if o is None or id(o) in gebruikt:
            alleen_nieuw.append(n)
        else:
            gebruikt.add(id(o))
            paren.append((o, n))
    alleen_oud = [o for o in oud if id(o) not in gebruikt]
    return paren, alleen_oud, alleen_nieuw


def koppel_op_naam(oud: list[dict], nieuw: list[dict]) -> tuple[list, list, list]:
    """Voor spelers. De ids verschillen per bron, de namen niet — op één ding na:
    dezelfde naam kan twee mensen zijn. Dubbele namen koppelen op volgorde."""
    per_naam: dict[str, list] = {}
    for o in oud:
        per_naam.setdefault(o.get("name", ""), []).append(o)

    paren, alleen_nieuw = [], []
    for n in nieuw:
        rij = per_naam.get(n.get("name", ""))
        if rij:
            paren.append((rij.pop(0), n))
        else:
            alleen_nieuw.append(n)
    alleen_oud = [o for rij in per_naam.values() for o in rij]
    return paren, alleen_oud, alleen_nieuw


# ─── 1. tegenspraak ──────────────────────────────────────────────────────────

def veld(w: dict, pad: str):
    """Haalt 'venue.name' uit een record, en geeft None als iets onderweg mist."""
    huidig = w
    for stuk in pad.split("."):
        if not isinstance(huidig, dict):
            return None
        huidig = huidig.get(stuk)
    return huidig


# Alleen velden waar 'anders' ook echt 'fout' betekent. Een stadionnaam hoort
# hier niet bij: twee bronnen mogen hetzelfde gebouw anders noemen. Een uitslag
# niet: 2-1 en 3-1 kunnen niet allebei waar zijn.
HARDE_VELDEN = [("date", "datum"),
                ("home_score", "thuisscore"),
                ("away_score", "uitscore")]


def strafschoppen_verklaren(o: dict, n: dict) -> bool:
    """Of het verschil in uitslag precies de strafschoppenserie is.

    Transfermarkt telt bij een beslissende serie de benutte strafschoppen bij de
    eindstand op; de parser haalt ze er weer af en legt ze apart vast. Sofascore
    zet die opgetelde stand in de uitslag. Ajax - PSV 2023 eindigde 1-1 en werd
    met 2-3 beslist: 'oud 3-4' en 'nieuw 1-1' beschrijven dus hetzelfde duel.
    Dat is een andere afspraak, geen tegenspraak.
    """
    serie = n.get("penalty_shootout")
    if not serie:
        return False
    for kant in ("home", "away"):
        oud, nieuw = o.get(f"{kant}_score"), n.get(f"{kant}_score")
        if not isinstance(oud, int) or not isinstance(nieuw, int):
            return False
        if oud != nieuw + (serie.get(kant) or 0):
            return False
    return True


def tegenspraak(o: dict, n: dict) -> list[tuple]:
    """De velden waar de twee bronnen elkaar écht tegenspreken.

    Weet één van de twee het niet, dan is dat een gat en geen tegenspraak;
    gaten staan in de dekkingstabel. En is het verschil in uitslag precies de
    strafschoppenserie, dan tellen de scores niet mee — de datum wel.
    """
    serie = strafschoppen_verklaren(o, n)
    uit = []
    for pad, naam in HARDE_VELDEN:
        if serie and pad in ("home_score", "away_score"):
            continue
        a, b = veld(o, pad), veld(n, pad)
        if a is None or b is None or a == "" or b == "":
            continue
        if a != b:
            uit.append((naam, a, b))
    return uit


# ─── 2. vertaling ────────────────────────────────────────────────────────────

# Namen die per wedstrijd te vergelijken zijn. Verschilt er één, dan is dat een
# naamwissel — tenzij dezelfde oude naam in twee verschillende nieuwe uiteenvalt.
NAAMVELDEN = [("venue.name", "stadion"),
              ("referee.name", "scheidsrechter"),
              ("tournament", "toernooi"),
              ("season", "seizoen"),
              ("home_team.name", "thuisclub"),
              ("away_team.name", "uitclub")]


def naamwissels(paren: list[tuple], pad: str) -> dict:
    """Leidt uit de gekoppelde wedstrijden af hoe namen zijn veranderd.

    Geeft vier groepen terug. 'gesplitst' is de enige verontrustende: dezelfde
    oude naam wees blijkbaar naar twee verschillende dingen, of de nieuwe bron
    houdt uit elkaar wat de oude samennam. 'samengevoegd' is meestal juist goed
    (Amsterdam ArenA en Johan Cruijff ArenA zijn hetzelfde gebouw).

    Bij een splitsing staan de wedstrijden erbij. Zonder die wedstrijden weet je
    wel dát 'Pol van Boekel' ook 'Bas Nijhuis' werd, maar niet waar je moet
    kijken — en dat is nu juist het enige wat je nodig hebt.
    """
    heen: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    terug: dict[str, set] = defaultdict(set)
    for o, n in paren:
        a, b = veld(o, pad), veld(n, pad)
        if not a or not b:
            continue
        heen[a][b].append(f"{o.get('date')}  {label(o)}")
        terug[b].add(a)

    gelijk, hernoemd, gesplitst, samengevoegd = [], [], [], []
    for a, takken in heen.items():
        if len(takken) > 1:
            gesplitst.append((a, sorted((b, sorted(w)) for b, w in takken.items())))
        else:
            b = next(iter(takken))
            if a == b:
                gelijk.append(a)
            elif len(terug[b]) > 1:
                samengevoegd.append((a, b))
            else:
                hernoemd.append((a, b))
    return {"gelijk": sorted(gelijk), "hernoemd": sorted(hernoemd),
            "gesplitst": sorted(gesplitst), "samengevoegd": sorted(samengevoegd)}


# ─── 3. dekking ──────────────────────────────────────────────────────────────

def gevuld(w: dict, pad: str) -> bool:
    """Of dit veld iets bevat. Een lege lijst en een lege string tellen niet."""
    waarde = veld(w, pad)
    if waarde is None or waarde == "" or waarde == [] or waarde == {}:
        return False
    return True


DEKKINGSVELDEN = [("venue.name", "stadion"),
                  ("referee.name", "scheidsrechter"),
                  ("attendance", "publiek"),
                  ("goals", "doelpunten"),
                  ("cards", "kaarten"),
                  ("substitutions", "wissels"),
                  ("lineup", "opstelling"),
                  ("half_time", "ruststand"),
                  ("round", "ronde")]


def dekking(paren: list[tuple]) -> list[tuple]:
    """Per veld: bij hoeveel gekoppelde wedstrijden staat het in de oude en in
    de nieuwe export."""
    uit = []
    for pad, naam in DEKKINGSVELDEN:
        a = sum(1 for o, _ in paren if gevuld(o, pad))
        b = sum(1 for _, n in paren if gevuld(n, pad))
        uit.append((naam, a, b))
    return uit


# ─── 4. spelers ──────────────────────────────────────────────────────────────

def doelpuntsom(export: dict) -> tuple[int, int]:
    """De doelpunten op twee manieren geteld: uit de eindstanden, en uit de
    spelers. Die twee horen op de eigen doelpunten na gelijk te zijn — dat is
    de scherpste controle die er op een export bestaat."""
    stand = sum((w.get("home_score") or 0) + (w.get("away_score") or 0)
                for w in export.get("matches") or [])
    spelers = sum(p.get("goals") or 0 for p in export.get("players") or [])
    return stand, spelers


# De twee bronnen markeren een eigen doelpunt anders: Sofascore schrijft
# type 'ownGoal', de Transfermarkt-parser 'own'. Wie er maar één van toetst,
# krijgt bij de andere bron nul eigen doelpunten en dus een onterechte ✗.
EIGEN_SOORTEN = {"own", "ownGoal", "owngoal", "own_goal"}


def eigen_doelpunten(export: dict) -> int:
    """Telt de doelpuntrecords die als eigen doelpunt gemarkeerd staan."""
    n = 0
    for w in export.get("matches") or []:
        for g in w.get("goals") or []:
            if g.get("type") in EIGEN_SOORTEN or g.get("own_goal") is True:
                n += 1
    return n


BEWEGING = ["goals", "assists", "yellow_cards", "red_cards", "matches_seen"]


def beweging(paren: list[tuple]) -> dict:
    """Per veld: hoeveel spelers gelijk blijven, dalen, stijgen."""
    uit = {}
    for f in BEWEGING:
        gelijk = omlaag = omhoog = 0
        for o, n in paren:
            a, b = o.get(f), n.get(f)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                continue
            if b == a:
                gelijk += 1
            elif b < a:
                omlaag += 1
            else:
                omhoog += 1
        uit[f] = (gelijk, omlaag, omhoog)
    return uit


# ─── rapport ─────────────────────────────────────────────────────────────────

def meervoud(n: int, enkel: str, meer: str) -> str:
    """'1 wedstrijd', '15 wedstrijden'. Een rapport dat je vijftien keer leest
    mag geen kromme regels bevatten."""
    return f"{n} {enkel if n == 1 else meer}"


def toon_lijst(regels: list[str], alles: bool, wit: int = 4):
    for r in regels[: None if alles else TOON]:
        print(f"{' ' * wit}{r}")
    if not alles and len(regels) > TOON:
        print(f"{' ' * wit}... en nog {len(regels) - TOON} (--alles toont ze allemaal)")


def rapport(oud: dict, nieuw: dict, uitgesteld: list[dict], alles: bool) -> int:
    """Print het hele rapport en geeft het aantal echte tegenspraken terug."""
    print(f"\n{'=' * 78}\n  VERGELIJKING — {OUD.name} naast {NIEUW.name}\n{'=' * 78}")

    paren, alleen_oud, alleen_nieuw = koppel_wedstrijden(
        oud.get("matches") or [], nieuw.get("matches") or [])
    print(f"\n  {len(paren)} wedstrijden in beide bestanden, "
          f"{len(alleen_oud)} alleen in de oude, {len(alleen_nieuw)} alleen in de nieuwe")

    fout = 0

    # ── welke wedstrijden vallen weg ──
    bekend = {u["id"]: u for u in uitgesteld}
    verwacht = [o for o in alleen_oud if o.get("id") in bekend]
    onverwacht = [o for o in alleen_oud if o.get("id") not in bekend]

    if verwacht:
        print(f"\n  ✓ {meervoud(len(verwacht), 'daarvan staat', 'daarvan staan')} "
              f"in {UITGESTELD.name}, met reden:")
        per_reden: dict[str, int] = {}
        for o in verwacht:
            reden = bekend[o["id"]]["reden"]
            per_reden[reden] = per_reden.get(reden, 0) + 1
        for reden, n in sorted(per_reden.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}× {reden}")

    if onverwacht:
        fout += len(onverwacht)
        print(f"\n  ▼ {meervoud(len(onverwacht), 'wedstrijd verdwijnt', 'wedstrijden verdwijnen')} "
              f"zonder dat {UITGESTELD.name} zegt waarom:")
        toon_lijst([f"{o.get('date')}  {label(o)}" for o in
                    sorted(onverwacht, key=lambda x: x.get("date") or "")], alles)

    if alleen_nieuw:
        fout += len(alleen_nieuw)
        print(f"\n  ▼ {meervoud(len(alleen_nieuw), 'wedstrijd staat', 'wedstrijden staan')} "
              f"alleen in de nieuwe export — die horen er niet bij te komen:")
        toon_lijst([f"{n.get('date')}  {label(n)}" for n in alleen_nieuw], alles)

    # ── 1. tegenspraak ──
    print(f"\n{'─' * 78}\n  1. TEGENSPRAAK — dezelfde wedstrijd, een andere uitkomst\n{'─' * 78}")
    print("  Datum en uitslag. Hier kan maar één van de twee bronnen gelijk hebben.")
    series = [(o, n) for o, n in paren if strafschoppen_verklaren(o, n)]
    if series:
        print(f"\n  ✓ {meervoud(len(series), 'wedstrijd werd', 'wedstrijden werden')} "
              f"op strafschoppen beslist. Sofascore telt die bij de uitslag op,")
        print(f"    Transfermarkt houdt de veldstand aan en legt de serie apart vast:")
        for o, n in sorted(series, key=lambda x: x[0].get("date") or ""):
            ps = n.get("penalty_shootout") or {}
            print(f"    {o.get('date')}  {label(o)}: "
                  f"{o.get('home_score')}-{o.get('away_score')} → "
                  f"{n.get('home_score')}-{n.get('away_score')} "
                  f"+ {ps.get('home')}-{ps.get('away')} strafschoppen")

    botsing = [(o, n, v) for o, n in paren if (v := tegenspraak(o, n))]
    if botsing:
        fout += len(botsing)
        print(f"\n  ▼ {meervoud(len(botsing), 'wedstrijd', 'wedstrijden')} van de "
              f"{len(paren)}:")
        regels = []
        for o, n, v in sorted(botsing, key=lambda x: x[0].get("date") or ""):
            regels.append(f"{o.get('date')}  {label(o)}")
            regels += [f"  {naam}: {a!r} → {b!r}" for naam, a, b in v]
        toon_lijst(regels, alles)
    else:
        print(f"\n  ✓ alle {len(paren)} gekoppelde wedstrijden hebben dezelfde datum "
              f"en dezelfde uitslag")

    # ── 2. vertaling ──
    print(f"\n{'─' * 78}\n  2. VERTALING — dezelfde zaak, een andere naam\n{'─' * 78}")
    print("  Afgeleid uit de gekoppelde wedstrijden. Een andere spelling is geen fout;")
    print("  een oude naam die in twee nieuwe uiteenvalt wél.")
    print(f"\n  {'':<16} {'gelijk':>8} {'hernoemd':>9} {'samengev.':>10} {'gesplitst':>10}")
    print(f"  {'-' * 16} {'-' * 8} {'-' * 9} {'-' * 10} {'-' * 10}")
    gesplitst_totaal = []
    for pad, naam in NAAMVELDEN:
        g = naamwissels(paren, pad)
        vink = "▼" if g["gesplitst"] else " "
        print(f"  {naam:<16} {len(g['gelijk']):>8} {len(g['hernoemd']):>9} "
              f"{len(g['samengevoegd']):>10} {len(g['gesplitst']):>10} {vink}")
        for a, takken in g["gesplitst"]:
            gesplitst_totaal.append(f"{naam}: {a!r} werd:")
            for b, wanneer in takken:
                # De kleinste tak is de afwijking; die krijgt zijn wedstrijden
                # erbij, de grote tak alleen een telling.
                if len(wanneer) <= 3:
                    for w in wanneer:
                        gesplitst_totaal.append(f"    {b!r}  —  {w}")
                else:
                    gesplitst_totaal.append(f"    {b!r}  —  {len(wanneer)} wedstrijden")
        if g["hernoemd"] or g["samengevoegd"]:
            wissels = ([f"{a!r} → {b!r}" for a, b in g["hernoemd"]] +
                       [f"{a!r} → {b!r}  (samengevoegd)" for a, b in g["samengevoegd"]])
            toon_lijst(wissels, alles, wit=6)

    if gesplitst_totaal:
        fout += len(gesplitst_totaal)
        print(f"\n  ▼ {meervoud(len(gesplitst_totaal), 'naam valt', 'namen vallen')} uiteen "
              f"— dat is geen spelling maar een andere indeling:")
        toon_lijst(gesplitst_totaal, alles)

    # ── 3. dekking ──
    print(f"\n{'─' * 78}\n  3. DEKKING — wat de nieuwe bron erbij heeft, over dezelfde "
          f"{len(paren)} wedstrijden\n{'─' * 78}")
    print(f"  {'':<16} {'Sofascore':>10} {'Transfermarkt':>14}")
    print(f"  {'-' * 16} {'-' * 10} {'-' * 14}")
    for naam, a, b in dekking(paren):
        pijl = "↑" if b > a else ("↓" if b < a else " ")
        print(f"  {naam:<16} {a:>10} {b:>13} {pijl}")

    # ── 4. spelers ──
    print(f"\n{'─' * 78}\n  4. SPELERS\n{'─' * 78}")
    p, a_oud, a_nieuw = koppel_op_naam(oud.get("players") or [],
                                       nieuw.get("players") or [])
    print(f"  {len(p)} op naam gekoppeld, {len(a_oud)} vervallen, {len(a_nieuw)} nieuw")
    print(f"  ({len(a_nieuw)} 'nieuw' hoort bij een wedstrijd die de oude export wel had")
    print(f"   maar zonder opstelling — daar kende Sofascore de bank niet.)")
    print(f"\n  {'':<16} {'gelijk':>8} {'lager':>8} {'hoger':>8}")
    print(f"  {'-' * 16} {'-' * 8} {'-' * 8} {'-' * 8}")
    for f, (gelijk, omlaag, omhoog) in beweging(p).items():
        print(f"  {f:<16} {gelijk:>8} {omlaag:>8} {omhoog:>8}")

    print(f"\n  ── tellen de doelpunten op? ──")
    print(f"  {'':<16} {'eindstanden':>12} {'via spelers':>12} {'eigen doelp.':>13}")
    print(f"  {'-' * 16} {'-' * 12} {'-' * 12} {'-' * 13}")
    for naam, export in (("Sofascore", oud), ("Transfermarkt", nieuw)):
        stand, via = doelpuntsom(export)
        eigen = eigen_doelpunten(export)
        klopt = "✓" if stand - eigen == via else "✗"
        print(f"  {naam:<16} {stand:>12} {via:>12} {eigen:>13}   {klopt}")
    print(f"  Eindstanden min eigen doelpunten hoort gelijk te zijn aan de som")
    print(f"  van de spelers. Klopt dat niet, dan mist die export doelpunten.")

    print(f"\n{'=' * 78}")
    if fout:
        print(f"  {meervoud(fout, 'punt', 'punten')} om naar te kijken "
              f"vóór de omwisseling.")
    else:
        print(f"  Geen tegenspraak. De nieuwe export is de oude min de "
              f"{meervoud(len(verwacht), 'uitgestelde wedstrijd', 'uitgestelde wedstrijden')},"
              f" in andere bewoordingen.")
    print(f"{'=' * 78}")
    return fout


# ─── zelftest ────────────────────────────────────────────────────────────────

def w(mid, datum, thuis, uit, hs, as_, stadion="X", ref="R", sofa=None,
      toernooi="Eredivisie", seizoen="23/24"):
    r = {"id": mid, "date": datum,
         "home_team": {"name": thuis}, "away_team": {"name": uit},
         "home_score": hs, "away_score": as_,
         "venue": {"name": stadion}, "referee": {"name": ref},
         "tournament": toernooi, "season": seizoen}
    if sofa is not None:
        r["sofascore_id"] = sofa
    return r


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

    print("── koppelen op id ──")
    oud = [w(1, "2024-01-01", "PSV", "Ajax", 2, 1),
           w(2, "2024-02-01", "NEC", "Feyenoord", 0, 0),
           w(3, "2024-03-01", "Twente", "AZ", 1, 1)]
    nieuw = [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1),
             w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3)]
    p, ao, an = koppel_wedstrijden(oud, nieuw)
    toets("twee koppelingen via sofascore_id", len(p), 2)
    toets("de niet-gekoppelde blijft over", [o["id"] for o in ao], [2])
    toets("niets komt er alleen in de nieuwe bij", an, [])

    print("\n── koppelen zonder id ──")
    p, _, _ = koppel_wedstrijden(oud, [w(902, "2024-02-01", "NEC", "Feyenoord", 0, 0)])
    toets("koppelt alsnog op datum en clubs", [(o["id"], n["id"]) for o, n in p],
          [(2, 902)])
    p, _, an = koppel_wedstrijden(oud, [w(903, "2024-02-01", "NEC", "Vitesse", 0, 0)])
    toets("andere tegenstander koppelt niet", (len(p), len(an)), (0, 1))
    p, ao, an = koppel_wedstrijden([w(1, "2024-01-01", "PSV", "Ajax", 2, 1)],
                                   [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1),
                                    w(901, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1)])
    toets("een dubbele nieuwe wijst nergens heen", (len(p), len(an)), (1, 1))

    print("\n── tegenspraak: alleen datum en uitslag ──")
    a = w(1, "2024-01-01", "PSV", "Ajax", 2, 1, stadion="Philips", ref="Higler")
    toets("gelijk is gelijk", tegenspraak(a, dict(a)), [])
    toets("een andere uitslag is tegenspraak",
          tegenspraak(a, {**a, "home_score": 3}), [("thuisscore", 2, 3)])
    toets("een andere datum ook",
          tegenspraak(a, {**a, "date": "2024-01-02"}),
          [("datum", "2024-01-01", "2024-01-02")])
    # Dit is de kern van de herziening: een andere stadionnaam is géén fout meer.
    toets("een ander stadion is geen tegenspraak",
          tegenspraak(a, {**a, "venue": {"name": "De Kuip"}}), [])
    toets("een andere toernooinaam evenmin",
          tegenspraak(a, {**a, "tournament": "Oefeninterlands"}), [])
    toets("0-0 is een uitslag, geen gat",
          tegenspraak({**a, "home_score": 0}, {**a, "home_score": 1}),
          [("thuisscore", 0, 1)])
    toets("een ontbrekende uitslag is een gat",
          tegenspraak({**a, "home_score": None}, a), [])

    print("\n── de strafschoppenserie ──")
    # Ajax - PSV 2023: veldstand 1-1, met 2-3 beslist. Sofascore schreef 3-4 op.
    veld_ = w(1, "2023-04-30", "AFC Ajax", "PSV", 1, 1)
    veld_["penalty_shootout"] = {"home": 2, "away": 3}
    sofa_ = w(9, "2023-04-30", "AFC Ajax", "PSV", 3, 4)
    toets("de serie verklaart het verschil", strafschoppen_verklaren(sofa_, veld_), True)
    toets("en is dus geen tegenspraak", tegenspraak(sofa_, veld_), [])
    toets("een andere datum telt nog steeds wel",
          tegenspraak({**sofa_, "date": "2023-05-01"}, veld_),
          [("datum", "2023-05-01", "2023-04-30")])
    toets("zonder serie is het wel tegenspraak",
          len(tegenspraak(sofa_, w(9, "2023-04-30", "AFC Ajax", "PSV", 1, 1))), 2)
    scheef = dict(veld_)
    scheef["penalty_shootout"] = {"home": 4, "away": 5}
    toets("een serie die het verschil niet dekt verklaart niets",
          strafschoppen_verklaren(sofa_, scheef), False)
    toets("... en blijft dus tegenspraak", len(tegenspraak(sofa_, scheef)), 2)

    print("\n── vertaling ──")
    paren = [(w(1, "2024-01-01", "PSV", "Ajax", 1, 0, stadion="Gofferstadion"),
              w(9, "2024-01-01", "PSV", "Ajax", 1, 0, stadion="Goffertstadion")),
             (w(2, "2024-02-01", "PSV", "Ajax", 1, 0, stadion="Philips"),
              w(8, "2024-02-01", "PSV", "Ajax", 1, 0, stadion="Philips"))]
    g = naamwissels(paren, "venue.name")
    toets("gelijke naam telt als gelijk", g["gelijk"], ["Philips"])
    toets("een spelfout telt als hernoemd", g["hernoemd"],
          [("Gofferstadion", "Goffertstadion")])
    toets("niets gesplitst", g["gesplitst"], [])

    samen = [(w(1, "2024-01-01", "A", "B", 0, 0, stadion="Amsterdam ArenA"),
              w(9, "2024-01-01", "A", "B", 0, 0, stadion="Johan Cruijff ArenA")),
             (w(2, "2024-02-01", "A", "B", 0, 0, stadion="Johan Cruijff ArenA"),
              w(8, "2024-02-01", "A", "B", 0, 0, stadion="Johan Cruijff ArenA"))]
    g = naamwissels(samen, "venue.name")
    toets("twee oude namen naar één nieuwe heet samengevoegd",
          g["samengevoegd"], [("Amsterdam ArenA", "Johan Cruijff ArenA")])
    toets("de gelijkgebleven naam telt niet dubbel", g["gelijk"],
          ["Johan Cruijff ArenA"])

    split = [(w(1, "2024-01-01", "A", "B", 0, 0, stadion="De Kuip"),
              w(9, "2024-01-01", "A", "B", 0, 0, stadion="Stadion Feijenoord")),
             (w(2, "2024-02-01", "A", "B", 0, 0, stadion="De Kuip"),
              w(8, "2024-02-01", "A", "B", 0, 0, stadion="Varkenoord"))]
    g = naamwissels(split, "venue.name")
    toets("één oude naam naar twee nieuwe heet gesplitst",
          [a for a, _ in g["gesplitst"]], ["De Kuip"])
    toets("en de wedstrijden staan erbij, zodat je weet waar je moet kijken",
          g["gesplitst"][0][1],
          [("Stadion Feijenoord", ["2024-01-01  A - B"]),
           ("Varkenoord", ["2024-02-01  A - B"])])
    toets("een gesplitste naam telt niet als hernoemd", g["hernoemd"], [])

    leeg = [(w(1, "2024-01-01", "A", "B", 0, 0, stadion=""),
             w(9, "2024-01-01", "A", "B", 0, 0, stadion="Philips"))]
    g = naamwissels(leeg, "venue.name")
    toets("een leeg veld levert geen naamwissel op",
          (g["gelijk"], g["hernoemd"]), ([], []))

    print("\n── dekking ──")
    o1 = w(1, "2024-01-01", "A", "B", 0, 0)
    o1["goals"], o1["lineup"] = [], []
    n1 = w(9, "2024-01-01", "A", "B", 0, 0)
    n1["goals"], n1["lineup"] = [{"player": "X"}], [{"player": "Y"}]
    d = dict((naam, (a, b)) for naam, a, b in dekking([(o1, n1)]))
    toets("een lege lijst telt niet als gevuld", d["doelpunten"], (0, 1))
    toets("een gevulde opstelling telt wel", d["opstelling"], (0, 1))
    toets("een ontbrekend veld telt als leeg", d["publiek"], (0, 0))
    toets("stadion staat in allebei", d["stadion"], (1, 1))

    print("\n── doelpunten optellen ──")
    export = {"matches": [{"home_score": 2, "away_score": 1,
                           "goals": [{"type": "regular"}, {"type": "ownGoal"},
                                     {"type": "penalty"}]}],
              "players": [{"name": "A", "goals": 2}]}
    toets("eindstanden en spelers geteld", doelpuntsom(export), (3, 2))
    toets("eigen doelpunten herkend uit Sofascore's 'ownGoal'",
          eigen_doelpunten(export), 1)
    # Transfermarkt schrijft 'own'. Alleen op 'ownGoal' toetsen gaf de nieuwe
    # export nul eigen doelpunten en dus een onterechte ✗.
    toets("en uit Transfermarkt's 'own'",
          eigen_doelpunten({"matches": [{"goals": [{"type": "own"}]}]}), 1)
    toets("en uit 'own_goal'",
          eigen_doelpunten({"matches": [{"goals": [{"own_goal": True}]}]}), 1)
    toets("een gewoon doelpunt telt niet mee",
          eigen_doelpunten({"matches": [{"goals": [{"type": "regular"},
                                                   {"type": "penalty"}]}]}), 0)
    toets("3 min 1 eigen doelpunt is 2 via de spelers: dat klopt",
          doelpuntsom(export)[0] - eigen_doelpunten(export), doelpuntsom(export)[1])

    print("\n── beweging ──")
    b = beweging([({"goals": 3}, {"goals": 3}), ({"goals": 3}, {"goals": 1}),
                  ({"goals": 3}, {"goals": 4}), ({"goals": 3}, {})])
    toets("gelijk, lager, hoger apart geteld; ontbrekend telt niet mee",
          b["goals"], (1, 1, 1))

    print("\n── het hele rapport ──")
    oud_export = {"matches": oud,
                  "players": [{"name": "Jan", "goals": 3, "matches_seen": 3}]}
    nieuw_export = {"matches": [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1),
                                w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3)],
                    "players": [{"name": "Jan", "goals": 2, "matches_seen": 2}]}
    uit = [{"id": 2, "date": "2024-02-01", "reden": "oefenduel"}]
    toets("een schone migratie geeft nul punten",
          rapport(oud_export, nieuw_export, uit, alles=True), 0)
    toets("een wedstrijd die zomaar verdwijnt telt wel",
          rapport(oud_export, nieuw_export, [], alles=True), 1)

    andere_stand = {**nieuw_export,
                    "matches": [w(900, "2024-01-01", "PSV", "Ajax", 3, 1, sofa=1),
                                w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3)]}
    toets("een andere uitslag telt wel",
          rapport(oud_export, andere_stand, uit, alles=True), 1)

    # Elke wedstrijd een eigen stadion: anders wijst de oude naam 'X' straks
    # naar twee nieuwe namen, en dat is terecht een splitsing.
    oud_stadions = {"matches": [w(1, "2024-01-01", "PSV", "Ajax", 2, 1, stadion="Philips"),
                                w(2, "2024-02-01", "NEC", "Feyenoord", 0, 0, stadion="Goffert"),
                                w(3, "2024-03-01", "Twente", "AZ", 1, 1, stadion="Grolsch")],
                    "players": []}
    andere_naam = {"matches": [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1,
                                 stadion="Philips Stadion"),
                               w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3,
                                 stadion="Grolsch")],
                   "players": []}
    toets("een andere stadionnaam telt niet",
          rapport(oud_stadions, andere_naam, uit, alles=True), 0)

    twee_kanten = {"matches": [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1,
                                 stadion="Philips Stadion"),
                               w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3,
                                 stadion="Philips Stadion")],
                   "players": []}
    toets("maar twee stadions die één worden is samenvoegen, ook geen fout",
          rapport(oud_stadions, twee_kanten, uit, alles=True), 0)

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} van {goed + fout} fout")
    return 1 if fout else 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Leg de Transfermarkt-export naast de Sofascore-export")
    p.add_argument("--alles", action="store_true",
                   help="toon elke regel, niet de eerste 15 per lijst")
    p.add_argument("--zelftest", action="store_true",
                   help="reken de vergelijking zelf na, zonder bestanden te lezen")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    for pad in (OUD, NIEUW):
        if not pad.exists():
            raise SystemExit(f"  {pad} ontbreekt — draai eerst transfermarkt_dashboard.py")

    oud = json.loads(OUD.read_text("utf-8"))
    nieuw = json.loads(NIEUW.read_text("utf-8"))
    uitgesteld = (json.loads(UITGESTELD.read_text("utf-8"))
                  if UITGESTELD.exists() else [])
    if not uitgesteld:
        print(f"  ! {UITGESTELD} ontbreekt — elke verdwenen wedstrijd komt "
              f"als onverklaard binnen")

    raise SystemExit(1 if rapport(oud, nieuw, uitgesteld, args.alles) else 0)


if __name__ == "__main__":
    main()
