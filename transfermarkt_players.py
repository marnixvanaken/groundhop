#!/usr/bin/env python3
"""
Transfermarkt spelerslaag — leid spelers af uit de wedstrijdrecords
===================================================================

`data/selected_matches_tm.json` bevat per wedstrijd de opstelling, doelpunten,
kaarten en wissels. Daaruit is de volledige spelerslaag te berekenen zonder
ook maar één netwerkverzoek: wie speelde, hoe lang, en wat hij deed.

Dat vervangt de route van sofascore_tracker.py, die per wedstrijd drie aparte
Sofascore-endpoints aanriep en de uitkomst cachete.

Wat hier NIET gebeurt: profielgegevens (geboortedatum, nationaliteit, positie,
marktwaarde). Die staan niet in het wedstrijdrapport en vergen een verzoek per
speler. Dat is stap twee — zie transfermarkt_profiles.py.

Gebruik
-------
    python3 transfermarkt_players.py --zelftest   # eerst dit
    python3 transfermarkt_players.py              # dan de echte afleiding
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

WEDSTRIJDEN = Path("data/selected_matches_tm.json")
UITVOER = Path("data/tm_players.json")

REGULIER, VERLENGING = 90, 120


# ─── Minuten ─────────────────────────────────────────────────────────────────

def wedstrijdlengte(wedstrijd: dict) -> int:
    """90, of 120 als er een gebeurtenis na de 90e minuut staat.

    Alleen een minuut *boven* 90 telt: blessuretijd komt binnen als minuut 90
    met `added_time` apart, en dat is nog steeds een wedstrijd van 90 minuten.
    """
    laatste = 0
    for sleutel in ("goals", "cards", "substitutions"):
        for g in wedstrijd.get(sleutel) or []:
            laatste = max(laatste, g.get("minute") or 0)
    return VERLENGING if laatste > REGULIER else REGULIER


def minuten_per_speler(wedstrijd: dict) -> dict[int, dict]:
    """Bereken per speler zijn minuten en zijn rol in deze wedstrijd.

    Rol is 'starter', 'sub' (ingevallen) of 'bench' (niet gespeeld).
    De klok stopt bij een wissel én bij een rode kaart, en loopt door tot het
    eind van de wedstrijd — verlenging inbegrepen.
    """
    eind = wedstrijdlengte(wedstrijd)

    erin: dict[int, int] = {}
    eruit: dict[int, int] = {}
    for w in wedstrijd.get("substitutions") or []:
        # minuut 0 bestaat niet in voetbal, maar een ontbrekende minuut komt
        # binnen als None; die mag niet als 0 gaan gelden.
        minuut = w.get("minute")
        if minuut is None:
            continue
        if w.get("player_in_id"):
            erin[w["player_in_id"]] = minuut
        if w.get("player_out_id"):
            eruit[w["player_out_id"]] = minuut

    # Een rode kaart haalt de speler van het veld; vanaf dat moment telt niets
    # meer. Tweede geel telt net zo goed als direct rood.
    rood: dict[int, int] = {}
    for k in wedstrijd.get("cards") or []:
        if k.get("type") in ("red", "yellowRed", "second_yellow") and k.get("player_id"):
            minuut = k.get("minute")
            if minuut is not None:
                pid = k["player_id"]
                rood[pid] = min(rood.get(pid, minuut), minuut)

    uit_lineup: dict[int, dict] = {}
    for kant in ("home", "away"):
        ploeg = (wedstrijd.get(f"{kant}_team") or {}).get("name", "")
        for p in (wedstrijd.get("lineup") or {}).get(kant, []):
            pid = p.get("player_id")
            if pid:
                uit_lineup[pid] = {"name": p.get("player", ""), "team": ploeg,
                                   "starter": bool(p.get("starter")),
                                   "photo": p.get("photo_url") or ""}
    # Staat er een opstelling? Dan is die volledig, en is iemand die er niet in
    # voorkomt geen basisspeler maar een gat in de data. Hem 90 minuten geven
    # zou een gok als feit opschrijven; zijn doelpunt telt wel gewoon mee.
    heeft_opstelling = bool(uit_lineup)

    # Spelers die in gebeurtenissen opduiken maar niet in de opstelling staan
    # (oudere wedstrijden zonder opstellingspagina) horen er ook bij.
    def ploeg_van(gebeurtenis):
        return gebeurtenis.get("team", "")

    for g in wedstrijd.get("goals") or []:
        for id_sleutel, naam_sleutel in (("player_id", "player"), ("assist_id", "assist")):
            if g.get(id_sleutel) and g[id_sleutel] not in uit_lineup:
                uit_lineup[g[id_sleutel]] = {"name": g.get(naam_sleutel) or "",
                                             "team": ploeg_van(g), "starter": None}
    for k in wedstrijd.get("cards") or []:
        if k.get("player_id") and k["player_id"] not in uit_lineup:
            uit_lineup[k["player_id"]] = {"name": k.get("player") or "",
                                          "team": ploeg_van(k), "starter": None}
    for w in wedstrijd.get("substitutions") or []:
        for id_sleutel, naam_sleutel in (("player_in_id", "player_in"),
                                         ("player_out_id", "player_out")):
            if w.get(id_sleutel) and w[id_sleutel] not in uit_lineup:
                uit_lineup[w[id_sleutel]] = {"name": w.get(naam_sleutel) or "",
                                             "team": ploeg_van(w), "starter": None}

    uitkomst: dict[int, dict] = {}
    for pid, info in uit_lineup.items():
        ingevallen = pid in erin
        # `starter` uit de opstelling is leidend; ontbreekt die (geen opstellings-
        # pagina), dan is invallen het enige signaal dat we hebben.
        if info["starter"] is None:
            if heeft_opstelling and not ingevallen:
                # Wel in beeld, niet in de opstelling: wedstrijd telt mee, maar
                # we weten niet hoe lang hij speelde.
                uitkomst[pid] = {**info, "minutes": 0, "rol": "onbekend"}
                continue
            is_starter = not ingevallen
        else:
            is_starter = info["starter"]

        if ingevallen:
            begin, rol = erin[pid], "sub"
        elif is_starter:
            begin, rol = 0, "starter"
        else:
            # Op de bank gebleven: geen minuten, wel een vermelding.
            uitkomst[pid] = {**info, "minutes": 0, "rol": "bench"}
            continue

        stop = eind
        if pid in eruit and eruit[pid] > begin:
            stop = min(stop, eruit[pid])
        if pid in rood and rood[pid] > begin:
            stop = min(stop, rood[pid])
        uitkomst[pid] = {**info, "minutes": max(0, stop - begin), "rol": rol}

    return uitkomst


# ─── Samenvoegen over alle wedstrijden ───────────────────────────────────────

def bouw_spelers(wedstrijden: list[dict]) -> list[dict]:
    spelers: dict[int, dict] = {}

    for w in wedstrijden:
        rollen = minuten_per_speler(w)
        etiket = (f"{(w.get('home_team') or {}).get('name','')} "
                  f"{w.get('home_score')}-{w.get('away_score')} "
                  f"{(w.get('away_team') or {}).get('name','')}")

        doelpunten: dict[int, int] = defaultdict(int)
        assists: dict[int, int] = defaultdict(int)
        for g in w.get("goals") or []:
            # Een eigen doelpunt is geen doelpunt van de maker.
            if g.get("player_id") and g.get("type") != "own":
                doelpunten[g["player_id"]] += 1
            if g.get("assist_id"):
                assists[g["assist_id"]] += 1

        geel: dict[int, int] = defaultdict(int)
        rood: dict[int, int] = defaultdict(int)
        for k in w.get("cards") or []:
            if not k.get("player_id"):
                continue
            if k.get("type") in ("red", "yellowRed", "second_yellow"):
                rood[k["player_id"]] += 1
            else:
                geel[k["player_id"]] += 1

        for pid, info in rollen.items():
            s = spelers.setdefault(pid, {
                "id": pid, "id_source": "transfermarkt", "name": info["name"],
                "matches_seen": 0, "goals": 0, "assists": 0,
                "yellow_cards": 0, "red_cards": 0, "minutes_played": 0,
                "starter_appearances": 0, "sub_appearances": 0,
                "bench_appearances": 0, "teams_seen_for": [], "matches_detail": [],
            })
            if info["name"] and not s["name"]:
                s["name"] = info["name"]
            if info.get("photo") and not s.get("photo_url"):
                s["photo_url"] = info["photo"]
            s["matches_seen"] += 1
            s["goals"] += doelpunten[pid]
            s["assists"] += assists[pid]
            s["yellow_cards"] += geel[pid]
            s["red_cards"] += rood[pid]
            s["minutes_played"] += info["minutes"]
            rol_veld = {"starter": "starter_appearances", "sub": "sub_appearances",
                        "bench": "bench_appearances"}.get(info["rol"])
            if rol_veld:
                s[rol_veld] += 1
            else:
                s["unknown_appearances"] = s.get("unknown_appearances", 0) + 1
            if info["team"] and info["team"] not in s["teams_seen_for"]:
                s["teams_seen_for"].append(info["team"])
            s["matches_detail"].append({
                "match_id": w.get("id"), "date": w.get("date"),
                "match_label": etiket, "team": info["team"],
                "goals": doelpunten[pid], "assists": assists[pid],
                "yellow": geel[pid], "red": rood[pid],
                "minutes": info["minutes"], "starter": info["rol"] == "starter",
            })

    for s in spelers.values():
        s["matches_detail"].sort(key=lambda m: m.get("date") or "", reverse=True)
    return sorted(spelers.values(),
                  key=lambda s: (-s["minutes_played"], s["name"]))


# ─── Zelftest ────────────────────────────────────────────────────────────────
#
# Vier van de tien fouten in dit project waren gevúlde velden met verkeerde
# inhoud. Tellen of een veld bestaat vangt die niet. Daarom staan hier
# uitgerekende uitkomsten: elk geval heeft één juist antwoord, en dat wordt
# nagerekend in plaats van bekeken.

def _wedstrijd(lineup_home, goals=(), cards=(), subs=()):
    return {
        "id": 1, "date": "2025-01-01",
        "home_team": {"name": "PSV"}, "away_team": {"name": "Ajax"},
        "home_score": 1, "away_score": 0,
        "lineup": {"home": list(lineup_home), "away": []},
        "goals": list(goals), "cards": list(cards), "substitutions": list(subs),
    }


def _speler(pid, naam, starter=True):
    return {"player_id": pid, "player": naam, "starter": starter}


def zelftest() -> int:
    fout = 0

    def check(omschrijving, gekregen, verwacht):
        nonlocal fout
        goed = gekregen == verwacht
        fout += not goed
        vlag = "  ok  " if goed else "  FOUT"
        staart = "" if goed else f"   (verwacht {verwacht}, kreeg {gekregen})"
        print(f"{vlag} {omschrijving}{staart}")

    print("── minuten ──")

    w = _wedstrijd([_speler(1, "Basisspeler")])
    check("basisspeler speelt uit", minuten_per_speler(w)[1]["minutes"], 90)

    w = _wedstrijd([_speler(1, "Eruit")],
                   subs=[{"player_out_id": 1, "player_in_id": 2,
                          "player_out": "Eruit", "player_in": "Erin",
                          "minute": 60, "team": "PSV"}])
    r = minuten_per_speler(w)
    check("basisspeler gewisseld in de 60e", r[1]["minutes"], 60)
    check("invaller in de 60e", r[2]["minutes"], 30)
    check("invaller telt als 'sub'", r[2]["rol"], "sub")

    # Het geval waar de bestaande afleiding op stukloopt: erin én er weer uit.
    w = _wedstrijd([_speler(1, "A"), _speler(2, "B", starter=False)],
                   subs=[{"player_out_id": 1, "player_in_id": 2,
                          "player_out": "A", "player_in": "B",
                          "minute": 60, "team": "PSV"},
                         {"player_out_id": 2, "player_in_id": 3,
                          "player_out": "B", "player_in": "C",
                          "minute": 80, "team": "PSV"}])
    check("invaller die zelf gewisseld wordt", minuten_per_speler(w)[2]["minutes"], 20)

    w = _wedstrijd([_speler(1, "Rood")],
                   cards=[{"player_id": 1, "player": "Rood", "type": "red",
                           "minute": 30, "team": "PSV"}])
    check("rode kaart stopt de klok", minuten_per_speler(w)[1]["minutes"], 30)

    w = _wedstrijd([_speler(1, "TweeGeel")],
                   cards=[{"player_id": 1, "player": "TweeGeel", "type": "yellow",
                           "minute": 20, "team": "PSV"},
                          {"player_id": 1, "player": "TweeGeel", "type": "yellowRed",
                           "minute": 70, "team": "PSV"}])
    r = minuten_per_speler(w)
    check("tweede geel stopt de klok", r[1]["minutes"], 70)

    w = _wedstrijd([_speler(1, "A"), _speler(2, "Invaller", starter=False)],
                   cards=[{"player_id": 2, "player": "Invaller", "type": "red",
                           "minute": 85, "team": "PSV"}],
                   subs=[{"player_out_id": 1, "player_in_id": 2,
                          "player_out": "A", "player_in": "Invaller",
                          "minute": 70, "team": "PSV"}])
    check("invaller met rode kaart", minuten_per_speler(w)[2]["minutes"], 15)

    w = _wedstrijd([_speler(1, "A"), _speler(9, "Bank", starter=False)])
    r = minuten_per_speler(w)
    check("ongebruikte bankspeler: 0 minuten", r[9]["minutes"], 0)
    check("ongebruikte bankspeler telt als 'bench'", r[9]["rol"], "bench")

    w = _wedstrijd([_speler(1, "A")],
                   goals=[{"player_id": 1, "player": "A", "minute": 105, "team": "PSV"}])
    check("verlenging: basisspeler speelt 120", minuten_per_speler(w)[1]["minutes"], 120)

    w = _wedstrijd([_speler(1, "A")],
                   goals=[{"player_id": 1, "player": "A", "minute": 90,
                           "added_time": 4, "team": "PSV"}])
    check("blessuretijd is geen verlenging", minuten_per_speler(w)[1]["minutes"], 90)

    w = _wedstrijd([_speler(1, "A")],
                   subs=[{"player_out_id": 1, "player_in_id": 2, "player_out": "A",
                          "player_in": "B", "minute": None, "team": "PSV"}])
    check("wissel zonder minuut telt niet als minuut 0",
          minuten_per_speler(w)[1]["minutes"], 90)

    w = _wedstrijd([_speler(1, "A")],
                   goals=[{"player_id": 77, "player": "Onbekend", "minute": 10,
                           "team": "PSV"}])
    r = minuten_per_speler(w)
    check("doelpuntenmaker buiten de opstelling: geen verzonnen minuten",
          r[77]["minutes"], 0)
    check("... maar wel als 'onbekend' geteld", r[77]["rol"], "onbekend")

    w = _wedstrijd([], goals=[{"player_id": 77, "player": "Onbekend",
                               "minute": 10, "team": "PSV"}])
    check("zonder opstelling blijft de terugval op 90 staan",
          minuten_per_speler(w)[77]["minutes"], 90)

    print("\n── tellingen ──")

    w = _wedstrijd([_speler(1, "Maker"), _speler(2, "Gever")],
                   goals=[{"player_id": 1, "player": "Maker", "assist_id": 2,
                           "assist": "Gever", "minute": 10, "team": "PSV"},
                          {"player_id": 1, "player": "Maker", "minute": 20,
                           "team": "PSV"}])
    s = {x["id"]: x for x in bouw_spelers([w])}
    check("twee doelpunten geteld", s[1]["goals"], 2)
    check("assist bij de juiste speler", s[2]["assists"], 1)
    check("assistgever krijgt geen doelpunt", s[2]["goals"], 0)

    w = _wedstrijd([_speler(1, "Pechvogel")],
                   goals=[{"player_id": 1, "player": "Pechvogel", "minute": 10,
                           "type": "own", "team": "PSV"}])
    s = {x["id"]: x for x in bouw_spelers([w])}
    check("eigen doelpunt telt niet als doelpunt", s[1]["goals"], 0)

    w1 = _wedstrijd([_speler(1, "Reiziger")])
    w2 = _wedstrijd([_speler(1, "Reiziger")])
    w2["id"] = 2
    w2["date"] = "2025-02-01"
    w2["home_team"] = {"name": "VVV-Venlo"}
    s = {x["id"]: x for x in bouw_spelers([w1, w2])}
    check("twee wedstrijden opgeteld", s[1]["minutes_played"], 180)
    check("twee clubs onthouden", sorted(s[1]["teams_seen_for"]), ["PSV", "VVV-Venlo"])
    check("nieuwste wedstrijd bovenaan", s[1]["matches_detail"][0]["date"], "2025-02-01")

    print("\n── portretfoto ──")
    foto = "https://img.a.transfermarkt.technology/portrait/small/9-1.jpg"
    w = _wedstrijd([{"player_id": 9, "player": "Speler9", "starter": True,
                     "photo_url": foto}])
    s = {x["id"]: x for x in bouw_spelers([w])}
    check("foto uit de opstelling overgenomen", s[9].get("photo_url"), foto)

    # Een speler die in meer wedstrijden voorkomt houdt de eerste foto die we
    # zagen; een latere wedstrijd zonder foto mag hem niet wissen.
    w2 = _wedstrijd([{"player_id": 9, "player": "Speler9", "starter": True,
                      "photo_url": ""}])
    w2["id"], w2["date"] = 2, "2025-02-01"
    s = {x["id"]: x for x in bouw_spelers([w, w2])}
    check("een wedstrijd zonder foto wist hem niet", s[9].get("photo_url"), foto)

    # Wie alleen in een doelpunt opduikt staat niet in de opstelling en heeft
    # dus geen foto; dat mag geen fout geven.
    w3 = _wedstrijd([], goals=[{"player_id": 7, "player": "Speler7", "team": "PSV"}])
    s = {x["id"]: x for x in bouw_spelers([w3])}
    check("speler buiten de opstelling heeft geen foto", s[7].get("photo_url"), None)

    print(f"\n  {'alles goed' if not fout else str(fout) + ' FOUT'}")
    return fout


def main():
    p = argparse.ArgumentParser(description="Leid de spelerslaag af")
    p.add_argument("--zelftest", action="store_true",
                   help="reken de afleiding na op uitgewerkte gevallen")
    p.add_argument("--top", type=int, default=15, help="hoeveel spelers tonen")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(1 if zelftest() else 0)

    if not WEDSTRIJDEN.exists():
        raise SystemExit(f"  {WEDSTRIJDEN} ontbreekt — draai eerst transfermarkt_sync.py")
    wedstrijden = json.loads(WEDSTRIJDEN.read_text("utf-8"))
    spelers = bouw_spelers(wedstrijden)

    zonder_opstelling = sum(1 for w in wedstrijden
                            if not (w.get("lineup") or {}).get("home"))
    print(f"  {len(wedstrijden)} wedstrijden → {len(spelers)} spelers")
    if zonder_opstelling:
        print(f"  ! {zonder_opstelling} wedstrijden zonder opstelling — daar komen")
        print(f"    alleen spelers uit die in een gebeurtenis voorkomen")

    print(f"\n  {'speler':<26} {'wed':>4} {'min':>6} {'gl':>3} {'as':>3} {'basis':>6} {'inv':>4} {'bank':>5}")
    print(f"  {'-' * 26} {'-' * 4} {'-' * 6} {'-' * 3} {'-' * 3} {'-' * 6} {'-' * 4} {'-' * 5}")
    for s in spelers[:args.top]:
        print(f"  {s['name'][:26]:<26} {s['matches_seen']:>4} {s['minutes_played']:>6} "
              f"{s['goals']:>3} {s['assists']:>3} {s['starter_appearances']:>6} "
              f"{s['sub_appearances']:>4} {s['bench_appearances']:>5}")

    # Onafhankelijke controle: het aantal afgeleide doelpunten moet gelijk zijn
    # aan de som van alle eindstanden, min de eigen doelpunten (die schrijven we
    # niet op naam van de maker). Klopt dat niet, dan mist de doelpuntenparser
    # iets — en dat zie je niet aan een gevuld veld.
    uit_stand = sum((w.get("home_score") or 0) + (w.get("away_score") or 0)
                    for w in wedstrijden)
    eigen = sum(1 for w in wedstrijden for g in (w.get("goals") or [])
                if g.get("type") == "own")
    afgeleid = sum(s["goals"] for s in spelers)
    verwacht = uit_stand - eigen
    print(f"\n  ── controle op de doelpunten ──")
    print(f"  som van de eindstanden      {uit_stand:>6}")
    print(f"  waarvan eigen doelpunten    {eigen:>6}")
    print(f"  verwacht op spelersnaam     {verwacht:>6}")
    print(f"  afgeleid uit de records     {afgeleid:>6}"
          f"{'   ✓' if afgeleid == verwacht else '   ✗ WIJKT AF'}")
    if afgeleid != verwacht:
        tekort = verwacht - afgeleid
        print(f"  ! {abs(tekort)} doelpunten {'ontbreken' if tekort > 0 else 'te veel'}.")
        print(f"    Wedstrijden waar de telling niet klopt:")
        getoond = 0
        for w in wedstrijden:
            stand = (w.get("home_score") or 0) + (w.get("away_score") or 0)
            gevonden = len(w.get("goals") or [])
            if stand != gevonden and getoond < 10:
                print(f"      {w.get('date')}  {(w.get('home_team') or {}).get('name')} - "
                      f"{(w.get('away_team') or {}).get('name')}: "
                      f"stand {stand}, gevonden {gevonden}")
                getoond += 1

    totaal_min = sum(s["minutes_played"] for s in spelers)
    print(f"\n  {sum(s['goals'] for s in spelers)} doelpunten · "
          f"{sum(s['assists'] for s in spelers)} assists · "
          f"{sum(s['yellow_cards'] for s in spelers)} geel · "
          f"{sum(s['red_cards'] for s in spelers)} rood · "
          f"{totaal_min:,} minuten")

    UITVOER.write_text(json.dumps(spelers, ensure_ascii=False, indent=2), "utf-8")
    print(f"  ✓ {UITVOER} geschreven")
    print(f"    Profielgegevens (geboortedatum, positie, marktwaarde) volgen apart.")


if __name__ == "__main__":
    main()
