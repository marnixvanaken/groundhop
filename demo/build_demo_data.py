#!/usr/bin/env python3
"""
Bouwt demo/match-data.js: één wedstrijd uit dashboard_data.json, compact genoeg
om in een losse demopagina te laden.

Twee dingen worden hier afgeleid en staan niet kant-en-klaar in de bron:

1. De opstelling. Het veld `lineup` staat op 1 van de 180 wedstrijden, maar
   `players[].matches_detail` dekt er 179, met minuten, rating, goals en
   assists per speler. De opstelling komt dus vanaf de spelerskant.

2. De tellers. Hoeveelste bezoek aan dit stadion, hoeveelste duel van deze
   club, hoeveelste in dit toernooi — chronologisch geteld tot en met deze
   wedstrijd. Dat is wat deze app kan en een uitslagensite niet.

Gebruik:  python3 demo/build_demo_data.py [match_id]
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "dashboard_data.json"
DEMO = Path(__file__).resolve().parent
TARGET = DEMO / "match-data.js"
CRESTS = DEMO / "crests"
PHOTOS = DEMO / "players"
LOGOS = DEMO / "tournaments"

# PSV Eindhoven 6-2 Napoli, Champions League, 21 oktober 2025.
# Gekozen omdat dit duel als enige alles heeft: stadion, publiek,
# scheidsrechter en acht goals.
DEFAULT_MATCH = 14566893


def extensie(pad):
    """De bestanden in img/ hebben geen extensie; zonder extensie serveert een
    webserver ze als octet-stream en toont de browser niets."""
    kop = pad.read_bytes()[:12]
    if kop[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if kop[:4] == b"RIFF" and kop[8:12] == b"WEBP":
        return ".webp"
    if kop[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return None


def kopieer(soort, ident, bronmap, doelmap):
    bron = ROOT / "img" / bronmap / str(ident)
    if not bron.exists():
        return None
    ext = extensie(bron)
    if ext is None:
        return None
    doelmap.mkdir(exist_ok=True)
    shutil.copyfile(bron, doelmap / f"{ident}{ext}")
    return f"{soort}/{ident}{ext}"


def copy_crest(team_id):
    return kopieer("crests", team_id, "team", CRESTS)


def copy_photo(player_id):
    """Van de 3016 spelers staan er 300 lokaal; de rest valt terug op initialen."""
    return kopieer("players", player_id, "player", PHOTOS)


def copy_logo(tournament_id):
    """Competitielogo's staan er pas na tools/fetch_images.py; tot die tijd
    toont het scherm de naam, zoals het nu ook doet."""
    return kopieer("tournaments", tournament_id, "tournament", LOGOS)


def nth(matches, match, key):
    """Hoeveelste keer dit duel voorkomt in de reeks, chronologisch geteld."""
    earlier = [m for m in matches if key(m) == key(match) and m["date"] <= match["date"]]
    return len(earlier)


def build_lineup(players, match_id):
    """Reconstrueert de opstelling vanaf de spelerskant."""
    teams = {}
    for p in players:
        for md in p.get("matches_detail", []):
            if md["match_id"] != match_id:
                continue
            teams.setdefault(md["team"], []).append({
                "name": p.get("short_name") or p.get("name"),
                "id": p["id"],
                "position": p.get("position") or "",
                "country": p.get("nationality_alpha2"),
                "minutes": md.get("minutes"),
                "rating": md.get("rating"),
                "goals": md.get("goals") or 0,
                "assists": md.get("assists") or 0,
                "starter": bool(md.get("starter")),
                "photo": copy_photo(p["id"]),
                # Hoe vaak je deze speler in totaal hebt zien spelen.
                "seen": p.get("matches_seen") or 0,
            })
    order = {"G": 0, "D": 1, "M": 2, "F": 3, "": 4}
    for side in teams.values():
        side.sort(key=lambda x: (not x["starter"], order.get(x["position"], 4), -(x["minutes"] or 0)))
    return teams


def main():
    match_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MATCH
    d = json.loads(SOURCE.read_text(encoding="utf-8"))
    matches = d["matches"]
    match = next((m for m in matches if m["id"] == match_id), None)
    if match is None:
        sys.exit(f"wedstrijd {match_id} niet gevonden")

    venue_name = match.get("venue", {}).get("name")
    home = match["home_team"]["name"]

    lineup = build_lineup(d["players"], match_id)
    venue = next((v for v in d["venues"] if v["name"] == venue_name), None)

    goals = sorted(
        match.get("goals", []),
        key=lambda g: (g["minute"] or 0, g.get("added_time") or 0),
    )

    payload = {
        "id": match["id"],
        "date": match["date"],
        "tournament": match["tournament"],
        "tournament_logo": copy_logo(match.get("tournament_id")),
        "season": match["season"],
        "round": match.get("round"),
        "home": {
            "name": home,
            "id": match["home_team"]["id"],
            "score": match["home_score"],
            "crest": copy_crest(match["home_team"]["id"]),
        },
        "away": {
            "name": match["away_team"]["name"],
            "id": match["away_team"]["id"],
            "score": match["away_score"],
            "crest": copy_crest(match["away_team"]["id"]),
        },
        "half_time": match.get("half_time"),
        "venue": match.get("venue"),
        "attendance": match.get("attendance"),
        "referee": match.get("referee"),
        "goals": goals,
        "lineup": lineup,
        "context": {
            "venue_visit": nth(matches, match, lambda m: m.get("venue", {}).get("name"))
            if venue_name else None,
            "venue_total": venue["matches_count"] if venue else None,
            "venue_first": venue["first_visit"] if venue else None,
            "club_match": nth(
                matches, match,
                lambda m: home in (m["home_team"]["name"], m["away_team"]["name"]),
            ),
            "tournament_match": nth(matches, match, lambda m: m["tournament"]),
            "match_nr": nth(matches, match, lambda m: True),
            "total_matches": len(matches),
        },
    }

    js = "window.MATCH = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n"
    TARGET.write_text(js, encoding="utf-8")
    kb = len(js) / 1024
    print(f"{TARGET.relative_to(ROOT)} geschreven — {kb:.0f} KB")
    print(f"  {payload['home']['name']} {payload['home']['score']}-{payload['away']['score']} {payload['away']['name']}")
    print(f"  goals: {len(goals)}")
    for team, side in lineup.items():
        print(f"  opstelling {team}: {len(side)} spelers ({sum(1 for p in side if p['starter'])} basis)")
    print(f"  context: {payload['context']}")


if __name__ == "__main__":
    main()
