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
from collections import defaultdict
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
    """Het portret; zelfde redenering als bij crest().

    De export van Transfermarkt wijst naar de kleinste maat (/portrait/small/),
    die op het spelersscherm (88 pixels, dubbel zo scherp op een telefoon)
    korrelig wordt. /portrait/big/ staat op hetzelfde adres. Het standaard-
    silhouet van Transfermarkt ('default') telt als geen foto: initialen
    zeggen meer dan een grijze schim.
    """
    if BRON["naam"] == "sofascore":
        return kopieer("players", speler["id"], "player") or f"/img/player/{speler['id']}"
    url = speler.get("photo_url") or ""
    if not url or "default" in url.rsplit("/", 1)[-1]:
        return None
    return url.replace("/portrait/small/", "/portrait/big/")


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


# Transfermarkt laat bij een paar landen de landcode leeg terwijl de naam er
# wel staat. Sint Maarten ontbreekt hier bewust: zijn ISO-code 'sx' is bij
# Transfermarkt al Schotland.
LANDCODE_OP_NAAM = {"Gibraltar": "gi"}


def landcode(speler):
    code = speler.get("nationality_alpha2") or LANDCODE_OP_NAAM.get(speler.get("nationality") or "")
    return code.lower() if code else None


def plat(tekst):
    """Alleen letters en cijfers, zonder accenten: 'Stadion "Galgenwaard"' en
    'Stadion Galgenwaard' zijn dan hetzelfde."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(tekst or "")).encode("ascii", "ignore").decode()
    return "".join(c for c in t.lower() if c.isalnum())


def albums(d, clubs, coords, venues):
    """De verzamelalbums uit data/collecties.json, met wat je al zag.

    Een club telt als je hem zag spelen, in welke competitie ook; gekoppeld op
    Transfermarkt-id, anders op naam. Een stadion telt als je er een wedstrijd
    zag. Stadionnamen verschillen per bron en per sponsor, dus elke naam die een
    bezocht stadion draagt (ook de aliassen in venue_coords.json) doet mee, en
    een naam van minstens zes tekens mag in de andere voorkomen ('Stayen' in
    'Daio Wasabi Stayen Stadium').
    """
    pad = ROOT / "data" / "collecties.json"
    if not pad.exists():
        return []
    ref = json.loads(pad.read_text(encoding="utf-8"))
    # Transfermarkt-nummers die je laptop heeft opgezocht voor clubs die je nog
    # nooit zag (collecties_vul.py); daarmee krijgen ook die een logo.
    ids_pad = ROOT / "data" / "collecties_ids.json"
    opgezocht = json.loads(ids_pad.read_text(encoding="utf-8")) if ids_pad.exists() else {}

    def wapen(tm_id):
        return f"https://img.a.transfermarkt.technology/wappen/normquad/{tm_id}.png" if tm_id else None

    def club_uit(c):
        """De club zoals het album hem toont: uit je data als je hem zag,
        anders met het logo van Transfermarkt (grijs in het album)."""
        tm = c.get("tm") or opgezocht.get(c["naam"])
        gezien = clubs.get(tm) or club_op_naam.get(plat(c["naam"]))
        if gezien:
            return {"naam": gezien["name"], "gezien": True, "n": gezien["count"],
                    "crest": gezien["crest"], "club": gezien["id"]}
        return {"naam": c["naam"], "gezien": False, "n": 0, "crest": wapen(tm), "club": None}

    club_op_naam = {plat(c["name"]): c for c in clubs.values()}
    bezocht = {}
    for v in venues:
        c = coords.get(v["key"]) or {}
        for naam in {v["key"], *v["namen"], c.get("display"), *c.get("aliases", [])}:
            if naam:
                bezocht[plat(naam)] = v
    def stadion_van(naam):
        k = plat(naam)
        if k in bezocht:
            return bezocht[k]
        if len(k) >= 6:
            for b, v in bezocht.items():
                if k in b or (len(b) >= 6 and b in k):
                    return v
        return None

    # De lijst van het lopende seizoen, als je laptop die heeft opgehaald
    # (collecties_vul.py); anders de terugvallijst uit collecties.json.
    sz_pad = ROOT / "data" / "collecties_seizoen.json"
    seizoen = json.loads(sz_pad.read_text(encoding="utf-8")) if sz_pad.exists() else {}

    uit = []
    for comp in ref["competities"]:
        opgehaald = (seizoen.get("competities") or {}).get(comp["id"])
        if opgehaald:
            j = seizoen["seizoen"]
            lijst, label = opgehaald, f"{j}/{(j + 1) % 100:02d}"
        else:
            lijst, label = comp["clubs"], comp["seizoen"]
        groep = f"{comp['naam']} {label}"
        items = [club_uit(c) for c in lijst]
        uit.append({"id": f"{comp['id']}-clubs", "soort": "clubs", "groep": groep,
                    "titel": "Clubs", "items": items})

        stadions = {}
        for c in lijst:
            if not c.get("stadion"):
                continue
            s_ = stadions.setdefault(c["stadion"], {"naam": c["stadion"], "clubs": []})
            k = club_uit(c)
            s_["clubs"].append({"naam": k["naam"], "crest": k["crest"]})
        items = []
        for s_ in stadions.values():
            v = stadion_van(s_["naam"])
            items.append({"naam": s_["naam"], "sub": " / ".join(k["naam"] for k in s_["clubs"]),
                          "clubs": s_["clubs"],
                          "gezien": bool(v), "n": v["visits"] if v else 0,
                          "key": v["key"] if v else None})
        uit.append({"id": f"{comp['id']}-stadions", "soort": "stadions", "groep": groep,
                    "titel": "Stadions", "items": items})

    landen = defaultdict(int)
    for p in d["players"]:
        if landcode(p):
            landen[landcode(p)] += 1
    for w in ref["werelddelen"]:
        uit.append({"id": f"landen-{w['id']}", "soort": "landen", "groep": "Spelers uit elk land",
                    "titel": w["naam"],
                    "items": [{"code": c, "gezien": landen[c] > 0, "n": landen[c]} for c in w["codes"]]})

    for a in uit:
        a["gezien"] = sum(1 for i in a["items"] if i["gezien"])
        a["totaal"] = len(a["items"])
    return uit


def main():
    d = json.loads(SOURCE.read_text(encoding="utf-8"))
    BRON["naam"] = d.get("source", "sofascore")
    LOGO_URL.update({c["id"]: c["logo_url"] for c in d.get("teams_visited", []) if c.get("logo_url")})

    coords = {}
    for v in json.loads((ROOT / "data" / "venue_coords.json").read_text(encoding="utf-8"))["venues"]:
        for naam in [v["name"], *v.get("aliases", [])]:
            coords[naam] = v

    def stadion_sleutel(naam):
        """De naam waaronder een stadion in de app staat: de hoofdnaam uit
        venue_coords.json als het een alias is, anders de naam zelf."""
        if not naam:
            return None
        return (coords.get(naam) or {}).get("name") or naam

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
        v = stadion_sleutel((m.get("venue") or {}).get("name"))
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
    # Gegroepeerd op naam, niet op het id uit de export. Bij interlands draagt
    # het stadion het id van het Nederlands elftal, waardoor De Kuip en de ArenA
    # samenvielen; en één stadion heet per sponsor anders (MySteel en GS
    # Staalwerken in Helmond). De aliassen in venue_coords.json brengen elke
    # naam terug tot één stadion.
    agg = {}
    for m in matches:
        ruw = (m.get("venue") or {}).get("name")
        if not ruw:
            continue
        k = stadion_sleutel(ruw)
        a_ = agg.setdefault(k, {"namen": set(), "data": [], "publiek": [], "stad": ""})
        a_["namen"].add(ruw)
        a_["data"].append(m["date"])
        if m.get("attendance"):
            a_["publiek"].append(m["attendance"])
        a_["stad"] = a_["stad"] or (m.get("venue") or {}).get("city") or ""
    venues = []
    zonder_coord = []
    for k, a_ in agg.items():
        c = coords.get(k)
        if c is None:
            zonder_coord.append(k)
        venues.append({
            "key": k,
            "name": toonnaam(k, c),
            "city": a_["stad"] or (c or {}).get("city") or "",
            "country": (c or {}).get("country") or "",
            "lat": (c or {}).get("lat"),
            "lon": (c or {}).get("lon"),
            "coord": (c or {}).get("status"),
            "visits": len(a_["data"]),
            "first": min(a_["data"]),
            "last": max(a_["data"]),
            "max_att": max(a_["publiek"]) if a_["publiek"] else None,
        })
    venues.sort(key=lambda v: (-v["visits"], v["name"]))

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
        "albums": albums(d, clubs, coords,
                         [dict(v, namen=agg[v["key"]]["namen"]) for v in venues]),
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
            "c": landcode(p),
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
    vlagnaam = {"en": "gb-eng", "sx": "gb-sct", "wa": "gb-wls", "wl": "gb-wls", "nx": "gb-nir"}
    zonder_vlag = sorted({p["c"] for p in spelers.values() if p["c"]
                          and not (DEMO / "vlaggen" / f"{vlagnaam.get(p['c'], p['c'])}.svg").exists()})
    if zonder_vlag:
        print(f"  ! nationaliteiten zonder vlag in app/vlaggen/: {', '.join(zonder_vlag)}")
    for a in app["albums"]:
        print(f"  album {a['groep']} · {a['titel']}: {a['gezien']} van {a['totaal']}")
    for namen_ in samengevoegd.values():
        print(f"  één competitie: {' + '.join(namen_)}")
    if zonder_coord:
        print(f"  zonder coordinaat ({len(zonder_coord)}): {', '.join(sorted(zonder_coord))}")


if __name__ == "__main__":
    main()
