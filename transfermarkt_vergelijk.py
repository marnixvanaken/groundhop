#!/usr/bin/env python3
"""
Transfermarkt vergelijk — leg de nieuwe export naast de oude, record voor record
================================================================================

transfermarkt_dashboard.py telt aan het eind op hoeveel wedstrijden, spelers en
stadions er in beide bestanden zitten. Dat zegt of de aantallen kloppen, niet of
de inhoud klopt. 165 wedstrijden kunnen er 165 zijn met de verkeerde uitslagen.

Deze module legt de twee exports record voor record naast elkaar en zoekt naar
het enige wat echt fout kan zijn: een wedstrijd die in beide bestanden staat maar
waar de twee bronnen het oneens zijn. Een andere uitslag, een ander stadion, een
andere scheidsrechter. Dat is geen migratie meer, dat is een fout — in de oude
data of in de nieuwe, maar een van de twee heeft het mis.

Wat géén fout is, en apart wordt gerapporteerd:

  * de 15 wedstrijden uit data/tm_uitgesteld.json staan alleen in de oude export.
    Dat is bekend en bewust. De module vinkt ze af tegen dat bestand, zodat een
    wedstrijd die om een ándere reden verdwijnt niet in die stapel wegvalt.
  * de spelers, stadions en clubs die alleen bij die 15 wedstrijden hoorden.
  * lagere aantallen in de nieuwe export. Minder wedstrijden is minder van alles.

Eén regel geldt overal: de nieuwe export is een deelverzameling van de oude, dus
niets mag omhóóg. Een speler met meer doelpunten in 165 wedstrijden dan in 180
telt iets dubbel. Die regel vangt meer dan een steekproef ooit zou vangen.

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
    """Voor spelers, stadions, clubs en scheidsrechters. De ids verschillen per
    bron, de namen niet — op één ding na: dezelfde naam kan twee mensen zijn.
    Dubbele namen koppelen op volgorde, en worden apart geteld."""
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


# ─── vergelijken ─────────────────────────────────────────────────────────────

def veld(w: dict, pad: str):
    """Haalt 'venue.name' uit een record, en geeft None als iets onderweg mist."""
    huidig = w
    for stuk in pad.split("."):
        if not isinstance(huidig, dict):
            return None
        huidig = huidig.get(stuk)
    return huidig


# Alleen velden die allebei de bronnen zouden moeten weten. Publiek bijvoorbeeld
# niet: Transfermarkt geeft dat lang niet altijd, en een ontbrekend publiek is
# geen tegenspraak.
WEDSTRIJDVELDEN = [("date", "datum"),
                   ("home_score", "thuisscore"),
                   ("away_score", "uitscore"),
                   ("venue.name", "stadion"),
                   ("referee.name", "scheidsrechter"),
                   ("tournament", "toernooi"),
                   ("season", "seizoen")]


def verschillen(o: dict, n: dict) -> list[tuple]:
    """De velden waar de twee bronnen elkaar tegenspreken.

    Tegenspreken, niet verschillen: als één van de twee niets weet is dat geen
    tegenspraak maar een gat, en gaten staan al in het dashboard-rapport.
    """
    uit = []
    for pad, naam in WEDSTRIJDVELDEN:
        a, b = veld(o, pad), veld(n, pad)
        if a in (None, "") or b in (None, ""):
            continue
        if a != b:
            uit.append((naam, a, b))
    return uit


# Velden die alleen omlaag mogen: de nieuwe export heeft minder wedstrijden.
OMHOOG_KAN_NIET = ["matches_seen", "goals", "assists", "yellow_cards", "red_cards",
                   "starter_appearances", "sub_appearances", "minutes_played"]


def gestegen(o: dict, n: dict, velden: list[str]) -> list[tuple]:
    """Velden die in de nieuwe export hóger zijn dan in de oude."""
    uit = []
    for f in velden:
        a, b = o.get(f), n.get(f)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a:
            uit.append((f, a, b))
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

    # ── de wedstrijden die alleen in de oude export staan ──
    bekend = {u["id"]: u for u in uitgesteld}
    verwacht = [o for o in alleen_oud if o.get("id") in bekend]
    onverwacht = [o for o in alleen_oud if o.get("id") not in bekend]

    if verwacht:
        print(f"\n  ✓ {meervoud(len(verwacht), 'daarvan staat', 'daarvan staan')} "
              f"in {UITGESTELD.name}, met reden:")
        per_reden: dict[str, int] = {}
        for o in verwacht:
            per_reden[bekend[o["id"]]["reden"]] = per_reden.get(
                bekend[o["id"]]["reden"], 0) + 1
        for reden, n in sorted(per_reden.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}× {reden}")

    if onverwacht:
        print(f"\n  ▼ {meervoud(len(onverwacht), 'wedstrijd verdwijnt', 'wedstrijden verdwijnen')} "
              f"zonder dat {UITGESTELD.name} zegt waarom:")
        toon_lijst([f"{o.get('date')}  {label(o)}" for o in
                    sorted(onverwacht, key=lambda x: x.get("date") or "")], alles)

    if alleen_nieuw:
        print(f"\n  ▼ {meervoud(len(alleen_nieuw), 'wedstrijd staat', 'wedstrijden staan')} "
              f"alleen in de nieuwe export — die horen er niet bij te komen:")
        toon_lijst([f"{n.get('date')}  {label(n)}" for n in alleen_nieuw], alles)

    # ── de wedstrijden die in allebei staan ──
    tegenspraak = [(o, n, v) for o, n in paren if (v := verschillen(o, n))]
    if tegenspraak:
        print(f"\n  ▼ {len(tegenspraak)} van de {len(paren)} gekoppelde wedstrijden "
              f"worden door de twee bronnen anders verteld:")
        regels = []
        for o, n, v in sorted(tegenspraak, key=lambda x: x[0].get("date") or ""):
            regels.append(f"{o.get('date')}  {label(o)}")
            regels += [f"  {naam}: {a!r} → {b!r}" for naam, a, b in v]
        toon_lijst(regels, alles)
    else:
        print(f"\n  ✓ alle {len(paren)} gekoppelde wedstrijden vertellen "
              f"hetzelfde verhaal: uitslag, stadion, scheidsrechter, toernooi, seizoen")

    # ── de doelpunten, op de gekoppelde wedstrijden ──
    def score(w):
        h, u = w.get("home_score"), w.get("away_score")
        return (h + u) if isinstance(h, int) and isinstance(u, int) else 0
    oud_goals = sum(score(o) for o, _ in paren)
    nieuw_goals = sum(score(n) for _, n in paren)
    vink = "✓" if oud_goals == nieuw_goals else "▼"
    print(f"\n  {vink} doelpunten in de gekoppelde wedstrijden: "
          f"{oud_goals} oud, {nieuw_goals} nieuw")

    # ── de afgeleide lijsten ──
    fout = len(onverwacht) + len(alleen_nieuw) + len(tegenspraak)
    fout += 0 if oud_goals == nieuw_goals else 1

    print(f"\n  ── de afgeleide lijsten ──")
    for sleutel, naam, velden in (
            ("players", "spelers", OMHOOG_KAN_NIET),
            ("venues", "stadions", ["matches_count"]),
            ("teams_visited", "clubs", ["matches_count", "as_home", "as_away"]),
            ("referees", "scheidsrechters", ["matches_count"]),
            ("tournaments", "toernooien", ["matches_count"]),
            ("seasons", "seizoenen", ["matches_count"])):
        p, a_oud, a_nieuw = koppel_op_naam(oud.get(sleutel) or [],
                                           nieuw.get(sleutel) or [])
        stijgers = [(o, n, g) for o, n in p if (g := gestegen(o, n, velden))]
        fout += len(a_nieuw) + len(stijgers)
        staat = (f"{len(p):>5} in beide, {len(a_oud):>4} vervallen, "
                 f"{len(a_nieuw):>3} nieuw")
        vink = "✓" if not a_nieuw and not stijgers else "▼"
        print(f"  {vink} {naam:<16} {staat}")
        if a_nieuw:
            print(f"      ▼ nieuw terwijl er niets bij kon komen:")
            toon_lijst([n.get("name", "?") for n in a_nieuw], alles, wit=8)
        if stijgers:
            print(f"      ▼ {len(stijgers)} gestegen in een kleinere dataset:")
            toon_lijst([f"{o.get('name', '?')}: " +
                        ", ".join(f"{f} {a}→{b}" for f, a, b in g)
                        for o, n, g in stijgers], alles, wit=8)

    print(f"\n{'=' * 78}")
    if fout:
        print(f"  {meervoud(fout, 'punt', 'punten')} om naar te kijken "
              f"vóór de omwisseling.")
    else:
        print(f"  Geen tegenspraak. De nieuwe export is de oude min de "
              f"{meervoud(len(verwacht), 'uitgestelde wedstrijd', 'uitgestelde wedstrijden')}.")
    print(f"{'=' * 78}")
    return fout


# ─── zelftest ────────────────────────────────────────────────────────────────

def w(mid, datum, thuis, uit, hs, as_, stadion="X", ref="R", sofa=None, toernooi="Eredivisie"):
    r = {"id": mid, "date": datum,
         "home_team": {"name": thuis}, "away_team": {"name": uit},
         "home_score": hs, "away_score": as_,
         "venue": {"name": stadion}, "referee": {"name": ref},
         "tournament": toernooi, "season": "23/24"}
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
    toets("de paren horen bij elkaar", [(o["id"], n["id"]) for o, n in p],
          [(1, 900), (3, 901)])

    print("\n── koppelen zonder id ──")
    # De wedstrijd die alleen in de export bestond: geen sofascore_id, wel
    # dezelfde datum en dezelfde clubs.
    p, ao, an = koppel_wedstrijden(oud, [w(902, "2024-02-01", "NEC", "Feyenoord", 0, 0)])
    toets("koppelt alsnog op datum en clubs", [(o["id"], n["id"]) for o, n in p],
          [(2, 902)])
    p, ao, an = koppel_wedstrijden(oud, [w(903, "2024-02-01", "NEC", "Vitesse", 0, 0)])
    toets("andere tegenstander koppelt niet", (len(p), len(an)), (0, 1))
    p, _, _ = koppel_wedstrijden(oud, [w(904, "2024-01-02", "PSV", "Ajax", 2, 1)])
    toets("andere datum koppelt niet", len(p), 0)

    print("\n── geen twee keer dezelfde ──")
    # Twee nieuwe records die op dezelfde oude wijzen: de tweede is een dubbele,
    # geen koppeling. Anders zou een dubbel gekoppelde wedstrijd onzichtbaar zijn.
    p, ao, an = koppel_wedstrijden([w(1, "2024-01-01", "PSV", "Ajax", 2, 1)],
                                   [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1),
                                    w(901, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1)])
    toets("de tweede wijst nergens heen", (len(p), len(an)), (1, 1))

    print("\n── tegenspraak ──")
    a = w(1, "2024-01-01", "PSV", "Ajax", 2, 1, stadion="Philips", ref="Higler")
    toets("gelijk is gelijk", verschillen(a, dict(a)), [])
    toets("een andere uitslag valt op",
          verschillen(a, {**a, "home_score": 3}), [("thuisscore", 2, 3)])
    toets("een ander stadion valt op",
          verschillen(a, {**a, "venue": {"name": "De Kuip"}}),
          [("stadion", "Philips", "De Kuip")])
    toets("twee verschillen tegelijk",
          len(verschillen(a, {**a, "home_score": 3, "referee": {"name": "Nijhuis"}})), 2)
    toets("een ontbrekende scheidsrechter is een gat, geen tegenspraak",
          verschillen(a, {**a, "referee": {"name": ""}}), [])
    toets("een ontbrekend stadion aan de oude kant ook",
          verschillen({**a, "venue": {}}, a), [])
    toets("0-0 is een uitslag, geen gat",
          verschillen({**a, "home_score": 0}, {**a, "home_score": 1}),
          [("thuisscore", 0, 1)])

    print("\n── koppelen op naam ──")
    p, ao, an = koppel_op_naam(
        [{"name": "Jan", "goals": 3}, {"name": "Piet", "goals": 1}],
        [{"name": "Jan", "goals": 2}, {"name": "Kees", "goals": 9}])
    toets("Jan koppelt", [(o["goals"], n["goals"]) for o, n in p], [(3, 2)])
    toets("Piet vervalt", [o["name"] for o in ao], ["Piet"])
    toets("Kees is nieuw", [n["name"] for n in an], ["Kees"])

    dubbel = [{"name": "Jan", "goals": 3}, {"name": "Jan", "goals": 5}]
    p, ao, an = koppel_op_naam(dubbel, [{"name": "Jan", "goals": 3}])
    toets("van twee naamgenoten koppelt er één", (len(p), len(ao), len(an)), (1, 1, 0))

    print("\n── stijgen kan niet ──")
    toets("gelijk is geen stijging",
          gestegen({"goals": 3}, {"goals": 3}, ["goals"]), [])
    toets("dalen mag", gestegen({"goals": 3}, {"goals": 1}, ["goals"]), [])
    toets("stijgen niet", gestegen({"goals": 3}, {"goals": 4}, ["goals"]),
          [("goals", 3, 4)])
    toets("een ontbrekend veld telt niet mee",
          gestegen({"goals": 3}, {}, ["goals", "assists"]), [])
    toets("tekst telt niet mee",
          gestegen({"goals": "3"}, {"goals": "9"}, ["goals"]), [])

    print("\n── velden uitlezen ──")
    toets("geneste naam", veld(a, "venue.name"), "Philips")
    toets("plat veld", veld(a, "date"), "2024-01-01")
    toets("ontbrekend pad geeft None", veld(a, "venue.city"), None)
    toets("pad door niets geeft None, geen fout",
          veld({"venue": None}, "venue.name"), None)

    print("\n── het hele rapport ──")
    oud_export = {"matches": oud,
                  "players": [{"name": "Jan", "goals": 3, "matches_seen": 3}],
                  "venues": [{"name": "X", "matches_count": 3}]}
    nieuw_export = {"matches": [w(900, "2024-01-01", "PSV", "Ajax", 2, 1, sofa=1),
                                w(901, "2024-03-01", "Twente", "AZ", 1, 1, sofa=3)],
                    "players": [{"name": "Jan", "goals": 2, "matches_seen": 2}],
                    "venues": [{"name": "X", "matches_count": 2}]}
    uit = [{"id": 2, "date": "2024-02-01", "reden": "oefenduel — niet in het speelschema"}]
    toets("een schone migratie geeft nul punten",
          rapport(oud_export, nieuw_export, uit, alles=True), 0)

    zonder_reden = rapport(oud_export, nieuw_export, [], alles=True)
    toets("een wedstrijd die zomaar verdwijnt telt wel", zonder_reden, 1)

    stijger = {**nieuw_export,
               "players": [{"name": "Jan", "goals": 4, "matches_seen": 2}]}
    toets("een speler die stijgt telt ook", rapport(oud_export, stijger, uit, True), 1)

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
