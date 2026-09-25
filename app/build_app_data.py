#!/usr/bin/env python3
"""
Bouwt de data voor de hele demo uit data/dashboard_data.json.

Twee bestanden:
- app/app-data.js     alle wedstrijden, stadions, clubs, competities en de kaart
- app/speler-data.js  alle spelers met per wedstrijd hun minuten en goals

Elk scherm leest hieruit en rekent zelf uit wat het nodig heeft: de tellers op
een wedstrijd, de ranglijst van een stadion, de duels van een speler. Daarmee
is elke wedstrijd, elk stadion en elke speler aan te klikken, in plaats van één
vooraf gekozen voorbeeld per scherm.

Spelers staan apart omdat ze het grootste deel zijn en alleen de schermen met
een opstelling of een speler ze nodig hebben.

Werkt op beide bronnen. Sofascore levert ratings, Transfermarkt niet; de
schermen tonen een kolom alleen als er iets in staat.

Gebruik:  python3 app/build_app_data.py
"""

import collections
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "dashboard_data.json"

LOGO_URL = {}


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


def kopieer(soort, ident, bronmap):
    if ident is None:
        return None
    bron = ROOT / "img" / bronmap / str(ident)
    if not bron.exists():
        return None
    ext = extensie(bron)
    if ext is None:
        return None
    doel = DEMO / soort
    doel.mkdir(exist_ok=True)
    shutil.copyfile(bron, doel / f"{ident}{ext}")
    return f"{soort}/{ident}{ext}"


BRON = {"naam": "sofascore"}


def crest(team_id):
    """Het clublogo.

    De bestanden in img/ zijn op Sofascore-id opgeslagen. Een Transfermarkt-id
    is een ander nummer, en kan toevallig het id van een andere Sofascore-club
    zijn: dan zou PSV het logo van een wildvreemde club krijgen. Die map geldt
    dus alleen voor een Sofascore-export.

    Sofascore zonder lokaal bestand: /img/team/<id>. Dat pad bedient server.py
    lokaal en api/img op Vercel. Transfermarkt: de URL uit de export zelf; hun
    beeldserver laat een <img> gewoon toe.
    """
    if BRON["naam"] == "sofascore":
        return kopieer("crests", team_id, "team") or f"/img/team/{team_id}"
    return LOGO_URL.get(team_id)


def foto(speler):
    """Het portret; zelfde redenering als bij crest()."""
    if BRON["naam"] == "sofascore":
        return kopieer("players", speler["id"], "player") or f"/img/player/{speler['id']}"
    return speler.get("photo_url")


def seizoen(datum):
    """Een seizoen begint in juli; 2023 betekent 2023/24."""
    jaar, maand = int(datum[:4]), int(datum[5:7])
    return jaar if maand >= 7 else jaar - 1


def toonnaam(naam, coord=None):
    """Transfermarkt schrijft sommige stadions in kapitalen. Tussen gewone namen
    leest dat als schreeuwen, dus alleen dat geval wordt omgezet."""
    if coord and coord.get("display"):
        return coord["display"]
    letters = [c for c in naam if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return naam.title()
    return naam


def main():
    d = json.loads(SOURCE.read_text(encoding="utf-8"))
    BRON["naam"] = d.get("source", "sofascore")
    LOGO_URL.update({c["id"]: c["logo_url"] for c in d.get("teams_visited", []) if c.get("logo_url")})

    coords = {}
    for v in json.loads((ROOT / "data" / "venue_coords.json").read_text(encoding="utf-8"))["venues"]:
        for naam in [v["name"], *v.get("aliases", [])]:
            coords[naam] = v

    # ── Wedstrijden ─────────────────────────────────────────────────────────
    matches = sorted(d["matches"], key=lambda m: (m["date"], m.get("startTimestamp") or 0),
                     reverse=True)
    clubs = {}
    for m in matches:
        for kant in ("home_team", "away_team"):
            t = m[kant]
            clubs.setdefault(t["id"], {"id": t["id"], "name": t["name"], "count": 0})
            clubs[t["id"]]["count"] += 1
    for c in clubs.values():
        c["crest"] = crest(c["id"])

    # Een competitie wisselt van naam met de sponsor: 'Eredivisie' en
    # 'VriendenLoterij Eredivisie' zijn dezelfde, met hetzelfde id. Samenvoegen
    # op id, en alleen zonder id op de naam. Elke wedstrijd krijgt de naam die
    # in die groep het vaakst voorkomt, zodat de schermen op één naam groeperen.
    def sleutel(m):
        return m.get("tournament_id") or m["tournament"]

    namen = collections.defaultdict(collections.Counter)
    for m in matches:
        namen[sleutel(m)][m["tournament"]] += 1
    naam_van = {k: c.most_common(1)[0][0] for k, c in namen.items()}

    comps = {}
    for m in matches:
        naam = naam_van[sleutel(m)]
        c = comps.setdefault(naam, {"name": naam, "id": m.get("tournament_id"), "count": 0})
        c["count"] += 1
    for c in comps.values():
        c["logo"] = kopieer("tournaments", c["id"], "tournament")
    samengevoegd = {k: sorted(c) for k, c in namen.items() if len(c) > 1}

    def wedstrijd(m):
        v = (m.get("venue") or {}).get("name")
        ref = m.get("referee") or {}
        ht = m.get("half_time") or {}
        return {
            "id": m["id"],
            "date": m["date"],
            "season": seizoen(m["date"]),
            "hid": m["home_team"]["id"],
            "aid": m["away_team"]["id"],
            "hs": m.get("home_score"),
            "as": m.get("away_score"),
            # Transfermarkt laat de ruststand weg na verlenging; dan niets tonen.
            "ht": [ht["home"], ht["away"]] if ht.get("home") is not None
                  and ht.get("away") is not None else None,
            "t": naam_van[sleutel(m)],
            "round": m.get("round"),
            "venue": v,
            "att": m.get("attendance"),
            "ref": ref.get("name"),
            "refc": ref.get("country"),
            "goals": [
                {"min": g.get("minute"), "add": g.get("added_time"), "p": g.get("player"),
                 "pid": g.get("player_id"), "a": g.get("assist"), "team": g.get("team"),
                 "type": g.get("type")}
                for g in sorted(m.get("goals") or [],
                                key=lambda g: (g.get("minute") or 0, g.get("added_time") or 0))
            ],
            "cards": [
                {"min": k.get("minute"), "p": k.get("player"), "team": k.get("team"),
                 "type": k.get("type")}
                for k in m.get("cards") or [] if k.get("type") in ("red", "yellowRed")
            ],
        }

    # ── Stadions ────────────────────────────────────────────────────────────
    venues = []
    zonder_coord = []
    for v in d["venues"]:
        c = coords.get(v["name"])
        if c is None:
            zonder_coord.append(v["name"])
        venues.append({
            "key": v["name"],
            "name": toonnaam(v["name"], c),
            "city": v.get("city") or (c or {}).get("city") or "",
            "country": (c or {}).get("country") or "",
            "lat": (c or {}).get("lat"),
            "lon": (c or {}).get("lon"),
            "coord": (c or {}).get("status"),
            "visits": v["matches_count"],
            "first": v.get("first_visit"),
            "last": v.get("last_visit"),
            "max_att": v.get("max_attendance"),
        })
    venues.sort(key=lambda v: -v["visits"])

    omtrek = json.loads((ROOT / "data" / "europe_outline.json").read_text(encoding="utf-8"))
    west, zuid, oost, noord = omtrek["_uitsnede"]

    alle_goals = sum(len(m.get("goals") or []) for m in matches)
    app = {
        "source": d.get("source", "sofascore"),
        "generated": d.get("generated_at"),
        "matches": [wedstrijd(m) for m in matches],
        "clubs": sorted(clubs.values(), key=lambda c: -c["count"]),
        "comps": sorted(comps.values(), key=lambda c: -c["count"]),
        "venues": venues,
        "outline": {"bbox": omtrek["_uitsnede"], "countries": omtrek["countries"]},
        "offmap": [v["key"] for v in venues if v["lat"] is not None
                   and not (west <= v["lon"] <= oost and zuid <= v["lat"] <= noord)],
        "records": d.get("records") or {},
        "totals": {
            "matches": len(matches),
            "goals": d.get("total_goals_witnessed") or alle_goals,
            "venues": len(venues),
            "clubs": len(clubs),
            "countries": len({v["country"] for v in venues if v["country"]}),
            "players": len(d["players"]),
            "first": matches[-1]["date"] if matches else None,
            "last": matches[0]["date"] if matches else None,
        },
    }

    # ── Spelers ─────────────────────────────────────────────────────────────
    spelers = {}
    for p in d["players"]:
        md = p.get("matches_detail") or []
        if not md:
            continue
        spelers[p["id"]] = {
            "n": p.get("name"),
            "s": p.get("short_name") or p.get("name"),
            "c": p.get("nationality_alpha2"),
            "pos": p.get("position") or "",
            "img": foto(p),
            "dob": p.get("date_of_birth"),
            "seen": p.get("matches_seen") or len(md),
            "g": p.get("goals") or 0,
            "as": p.get("assists") or 0,
            "teams": p.get("teams_seen_for") or [],
            "m": [[x["match_id"], x.get("team"), x.get("minutes"), x.get("goals") or 0,
                   x.get("assists") or 0, 1 if x.get("starter") else 0, x.get("rating")]
                  for x in md],
        }

    def schrijf(naam, var, data):
        pad = DEMO / naam
        pad.write_text(f"window.{var} = " + json.dumps(data, ensure_ascii=False,
                                                         separators=(",", ":")) + ";\n",
                       encoding="utf-8")
        print(f"  {pad.relative_to(ROOT)}  {pad.stat().st_size / 1024:.0f} KB")

    print(f"bron: {app['source']} — {len(matches)} wedstrijden, {len(venues)} stadions, "
          f"{len(clubs)} clubs, {len(spelers)} spelers")
    schrijf("app-data.js", "APP", app)
    schrijf("speler-data.js", "SPELERS", spelers)

    zonder_logo = sum(1 for c in clubs.values() if not c["crest"])
    zonder_foto = sum(1 for p in spelers.values() if not p["img"])
    print(f"  clublogo's: {len(clubs) - zonder_logo} van {len(clubs)}; spelersfoto's: "
          f"{len(spelers) - zonder_foto} van {len(spelers)} (rest: initialen)")
    for namen_ in samengevoegd.values():
        print(f"  één competitie: {' + '.join(namen_)}")
    if zonder_coord:
        print(f"  zonder coordinaat ({len(zonder_coord)}): {', '.join(sorted(zonder_coord))}")


if __name__ == "__main__":
    main()
