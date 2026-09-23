#!/usr/bin/env python3
"""
Bouwt demo/venue-data.js: twee stadions uit de dataset, gekozen om de uitersten
te tonen waar dit scherm mee om moet gaan.

Philips Stadion heeft 94 bezoeken over negen seizoenen; het Bernabéu één avond.
Hetzelfde scherm moet beide dragen, dus de demo levert ze allebei.

Bijna alles hier wordt afgeleid: de bron geeft per stadion maar zeven velden.
Goals, clubs, spelers, toernooien en scheidsrechters komen uit de wedstrijden
op dat adres, en de posities uit de vergelijking met de andere 30 stadions.

Gebruik:  python3 demo/build_venue_data.py
"""

import collections
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
TARGET = DEMO / "venue-data.js"
CRESTS = DEMO / "crests"
LOGOS = DEMO / "tournaments"

def kies_stadions(venues, bekend):
    """Twee uitersten: het stadion waar je het vaakst kwam, en het
    indrukwekkendste dat je één keer zag. Op naam vastleggen brak zodra de
    bron wisselde en Transfermarkt een stadion anders schrijft.

    Alleen stadions waarvan een coordinaat bekend is komen in aanmerking;
    zonder coordinaat kan het scherm de ligging niet tonen.
    """
    venues = [v for v in venues if v["name"] in bekend]
    if not venues:
        return []
    op_bezoek = sorted(venues, key=lambda v: -v["matches_count"])
    vaakst = op_bezoek[0]
    eenmalig = [v for v in venues if v["matches_count"] == 1]
    # Onder de eenmalige het stadion met het grootste publiek; is dat nergens
    # bekend, dan het meest recente bezoek.
    if eenmalig:
        eenmalig.sort(key=lambda v: (v.get("max_attendance") or 0, v["first_visit"]), reverse=True)
        return [vaakst["name"], eenmalig[0]["name"]]
    return [vaakst["name"]]


def logo(tournament_id):
    """Zie tools/fetch_images.py; ontbreekt het bestand, dan blijft het bij de naam."""
    bron = ROOT / "img" / "tournament" / str(tournament_id)
    if not bron.exists():
        return None
    LOGOS.mkdir(exist_ok=True)
    kop = bron.read_bytes()[:12]
    ext = (".png" if kop[:8] == b"\x89PNG\r\n\x1a\n"
           else ".webp" if kop[:4] == b"RIFF" and kop[8:12] == b"WEBP"
           else ".jpg" if kop[:3] == b"\xff\xd8\xff" else None)
    if ext is None:
        return None
    shutil.copyfile(bron, LOGOS / f"{tournament_id}{ext}")
    return f"tournaments/{tournament_id}{ext}"


def toonnaam(naam):
    """Transfermarkt schrijft sommige stadions in kapitalen, zoals de eigenaar
    ze zelf zet. Tussen namen in gewone schrijfwijze leest dat als schreeuwen,
    dus alleen dat geval wordt omgezet; de rest blijft precies zoals de bron
    hem levert, inclusief aanhalingstekens."""
    letters = [c for c in naam if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return naam.title()
    return naam


def crest(team_id):
    """Clublogo naast deze pagina zetten. De bestanden in img/team/ hebben geen
    extensie; zonder extensie serveert een webserver ze als octet-stream."""
    bron = ROOT / "img" / "team" / str(team_id)
    if not bron.exists():
        return None
    kop = bron.read_bytes()[:12]
    ext = (".png" if kop[:8] == b"\x89PNG\r\n\x1a\n"
           else ".webp" if kop[:4] == b"RIFF" and kop[8:12] == b"WEBP"
           else ".jpg" if kop[:3] == b"\xff\xd8\xff" else None)
    if ext is None:
        return None
    CRESTS.mkdir(exist_ok=True)
    shutil.copyfile(bron, CRESTS / f"{team_id}{ext}")
    return f"crests/{team_id}{ext}"


def seizoen(datum):
    """Een seizoen loopt van juli tot juni, zoals in dashboard.html."""
    jaar, maand = int(datum[:4]), int(datum[5:7])
    start = jaar if maand >= 7 else jaar - 1
    return f"{str(start)[2:]}/{str(start + 1)[2:]}"


def bouw(naam, data, coords):
    venues = {v["name"]: v for v in data["venues"]}
    bron = venues[naam]
    ms = [m for m in data["matches"] if m.get("venue", {}).get("name") == naam]
    ms.sort(key=lambda m: m["date"], reverse=True)
    ids = {m["id"] for m in ms}

    clubs = collections.Counter()
    club_ids = {}
    for m in ms:
        for kant in ("home_team", "away_team"):
            clubs[m[kant]["name"]] += 1
            club_ids[m[kant]["name"]] = m[kant]["id"]

    spelers = {
        p["id"]
        for p in data["players"]
        for md in p.get("matches_detail", [])
        if md["match_id"] in ids
    }

    toernooi_ids = {m["tournament"]: m.get("tournament_id") for m in ms}
    publiek = [m["attendance"] for m in ms if m.get("attendance")]
    goals = sum(len(m.get("goals", [])) for m in ms)

    seizoenen = collections.Counter(seizoen(m["date"]) for m in ms)
    # Lege seizoenen horen als nul in de reeks. Ze overslaan maakt van een
    # onderbreking een ononderbroken lijn en liegt over het verloop:
    # 20/21 is hier geen ontbrekende meting maar een seizoen zonder bezoek.
    jaren = sorted(int(s[:2]) for s in seizoenen)
    balken = [
        {"name": f"{j:02d}/{j + 1:02d}", "value": seizoenen.get(f"{j:02d}/{j + 1:02d}", 0)}
        for j in range(jaren[0], jaren[-1] + 1)
    ] if seizoenen else []

    # Positie binnen de verzameling: zonder die context zegt één bezoek niets.
    op_bezoeken = sorted(venues.values(), key=lambda v: -v["matches_count"])
    met_publiek = sorted(
        [v for v in venues.values() if v.get("max_attendance")],
        key=lambda v: -v["max_attendance"],
    )
    rang_publiek = next(
        (i + 1 for i, v in enumerate(met_publiek) if v["name"] == naam), None
    )

    return {
        "name": toonnaam(naam),
        # Transfermarkt levert de stad niet mee; de coordinatenlijst wel.
        "city": bron.get("city") or coords.get("city") or "",
        "country": coords["country"],
        "lat": coords["lat"],
        "lon": coords["lon"],
        "coord_status": coords["status"],
        "visits": len(ms),
        "visits_source": bron["matches_count"],
        "first": bron["first_visit"],
        "last": bron["last_visit"],
        "goals": goals,
        "goals_per_match": round(goals / len(ms), 1) if ms else 0,
        "clubs": len(clubs),
        "clubs_top": [
            {"name": n, "count": c, "crest": crest(club_ids[n])}
            for n, c in clubs.most_common(4)
        ],
        "players": len(spelers),
        "tournaments": [
            {"name": n, "count": c, "logo": logo(toernooi_ids.get(n))}
            for n, c in collections.Counter(m["tournament"] for m in ms).most_common(4)
        ],
        "referees": len({m["referee"]["name"] for m in ms if m.get("referee", {}).get("name")}),
        "seasons": len(seizoenen),
        "season_bars": balken,
        "attendance_known": len(publiek),
        "attendance_max": max(publiek) if publiek else None,
        "attendance_avg": sum(publiek) // len(publiek) if publiek else None,
        "rank_visits": next(i + 1 for i, v in enumerate(op_bezoeken) if v["name"] == naam),
        "rank_attendance": rang_publiek,
        "venues_total": len(venues),
        "matches": [
            {
                "id": m["id"],
                "date": m["date"],
                "home": m["home_team"]["name"],
                "away": m["away_team"]["name"],
                "home_crest": crest(m["home_team"]["id"]),
                "away_crest": crest(m["away_team"]["id"]),
                "home_score": m["home_score"],
                "away_score": m["away_score"],
                "tournament": m["tournament"],
                "goals": len(m.get("goals", [])),
                "attendance": m.get("attendance"),
                "referee": m.get("referee", {}).get("name") or None,
            }
            for m in ms[:6]
        ],
    }


def main():
    data = json.loads((ROOT / "data" / "dashboard_data.json").read_text(encoding="utf-8"))
    # Elk punt is vindbaar onder elke naam die het draagt, zodat een wissel
    # van bron de kaart niet leeg trekt.
    coords = {}
    for v in json.loads((ROOT / "data" / "venue_coords.json").read_text(encoding="utf-8"))["venues"]:
        for naam in [v["name"], *v.get("aliases", [])]:
            coords[naam] = v

    # De kaart komt uit de export: wat je bezocht hebt, niet wat er toevallig
    # een coordinaat heeft. Andersom zou elk punt dubbel tellen, want een punt
    # draagt meerdere namen.
    kaart = []
    zonder_coord = []
    for v in data["venues"]:
        c = coords.get(v["name"])
        if c is None:
            zonder_coord.append(v["name"])
            continue
        kaart.append({
            "name": v["name"],
            "lat": c["lat"],
            "lon": c["lon"],
            "country": c["country"],
            "visits": v["matches_count"],
        })
    zonder_coord.sort()
    # Punten die onder geen enkele naam in de export voorkomen: die namen zijn
    # verouderd of de bron schrijft ze weer anders.
    herkend = {coords[v["name"]]["name"] for v in data["venues"] if v["name"] in coords}
    ongebruikt = sorted({c["name"] for c in coords.values()} - herkend)

    tonen = kies_stadions(data["venues"], coords)
    if not tonen:
        namen = sorted(v["name"] for v in data["venues"])[:5]
        raise SystemExit(
            "geen enkel stadion uit de export staat in data/venue_coords.json.\n"
            f"  In de export staat bijvoorbeeld: {', '.join(namen)}")
    print(f"bron: {data.get('source', 'sofascore')} — toont {', '.join(tonen)}")

    payload = {
        "venues": [bouw(n, data, coords[n]) for n in tonen],
        "map": kaart,
        "totals": {
            "venues": len(data["venues"]),
            "countries": len({v["country"] for v in coords.values()}),
            "cities": len({
                v.get("city") or (coords.get(v["name"]) or {}).get("city")
                for v in data["venues"]
            } - {None, ""}),
            "visits": sum(v["matches_count"] for v in data["venues"]),
            "matches_without_venue": sum(
                1 for m in data["matches"] if not m.get("venue", {}).get("name")
            ),
        },
    }

    js = "window.VENUES = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n"
    TARGET.write_text(js, encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)} geschreven — {len(js)/1024:.0f} KB")
    for v in payload["venues"]:
        print(f"  {v['name']}: {v['visits']} bezoeken, {v['goals']} goals, "
              f"{v['clubs']} clubs, {v['players']} spelers, "
              f"publiek bekend bij {v['attendance_known']}, "
              f"nr {v['rank_visits']} van {v['venues_total']}")
    print(f"  kaartpunten: {len(payload['map'])} van de {len(data['venues'])} stadions")
    if zonder_coord:
        print(f"  zonder coordinaat ({len(zonder_coord)}): {', '.join(zonder_coord)}")
    if ongebruikt:
        print(f"  coordinaat zonder stadion in de export ({len(ongebruikt)}): "
              f"{', '.join(ongebruikt)}")
    print(f"  totalen: {payload['totals']}")


if __name__ == "__main__":
    main()
