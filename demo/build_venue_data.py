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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
TARGET = DEMO / "venue-data.js"

TONEN = ["Philips Stadion", "Bernabéu"]


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
    for m in ms:
        clubs[m["home_team"]["name"]] += 1
        clubs[m["away_team"]["name"]] += 1

    spelers = {
        p["id"]
        for p in data["players"]
        for md in p.get("matches_detail", [])
        if md["match_id"] in ids
    }

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
        "name": naam,
        "city": bron["city"],
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
        "clubs_top": [{"name": n, "count": c} for n, c in clubs.most_common(4)],
        "players": len(spelers),
        "tournaments": [
            {"name": n, "count": c}
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
    coords = {
        v["name"]: v
        for v in json.loads((ROOT / "data" / "venue_coords.json").read_text(encoding="utf-8"))["venues"]
    }

    # Alle 31 punten gaan mee voor de kaartkop; de twee uitgewerkte stadions
    # krijgen de volledige afleiding.
    kaart = [
        {
            "name": v["name"],
            "lat": v["lat"],
            "lon": v["lon"],
            "country": v["country"],
            "visits": next(
                b["matches_count"] for b in data["venues"] if b["name"] == v["name"]
            ),
        }
        for v in coords.values()
    ]

    payload = {
        "venues": [bouw(n, data, coords[n]) for n in TONEN],
        "map": kaart,
        "totals": {
            "venues": len(data["venues"]),
            "countries": len({v["country"] for v in coords.values()}),
            "cities": len({v["city"] for v in data["venues"]}),
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
    print(f"  kaartpunten: {len(payload['map'])}")
    print(f"  totalen: {payload['totals']}")


if __name__ == "__main__":
    main()
