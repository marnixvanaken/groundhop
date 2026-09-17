#!/usr/bin/env python3
"""
Transfermarkt dashboard — bouw de dashboard-export uit de Transfermarkt-data
===========================================================================

Het dashboard leest één bestand: data/dashboard_data.json. Tot nu toe maakte
sofascore_tracker.py dat, door de Sofascore-cache opnieuw door te lopen. Deze
module doet hetzelfde uit de Transfermarkt-keten, en heeft die cache niet nodig:
transfermarkt_sync.py en transfermarkt_players.py hebben het rekenwerk al
gedaan. Wat hier gebeurt is optellen — stadions, clubs, toernooien, records —
en het aanvullen van de spelers met wat alleen uit de combinatie volgt: hun
leeftijd op de dag van elke wedstrijd.

Het schrijft naar data/dashboard_data_tm.json en laat data/dashboard_data.json
met rust, net zoals de sync selected_matches.json met rust laat. Vergelijk eerst,
vervang daarna.

Gebruik
-------
    python3 transfermarkt_dashboard.py              # bouwen en rapporteren
    python3 transfermarkt_dashboard.py --uitvoer X  # naar een ander bestand
    python3 transfermarkt_dashboard.py --zelftest   # alle sommen narekenen
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import transfermarkt_paden as paden

WEDSTRIJDEN = paden.wedstrijden()
SPELERS = Path("data/tm_players_full.json")
DASHBOARD_HTML = Path("dashboard.html")
OUD = Path("data/dashboard_data.json")
UITVOER = paden.dashboard()


# ─── Positie ─────────────────────────────────────────────────────────────────

# Het dashboard zet spelers in een opstelling op `position`, en dat veld moet
# dan één letter zijn: G, D, M of F. Transfermarkt schrijft de positie voluit
# en preciezer ("Centrale verdediger"). Dat is winst, geen verlies: de letter
# gaat naar `position` zodat de XI blijft werken, de volledige omschrijving naar
# `position_detail`.
#
# De volgorde van deze regels is de hele truc. "Linkervleugelverdediger" bevat
# zowel "vleugel" als "verdediger", "aanvallende middenvelder" zowel "aanval"
# als "middenvelder". Wie eerst op de aanvallende woorden toetst, zet halve
# verdedigingen en het complete middenveld in de spits.
POSITIEREGELS = [
    ("G", ("doelman", "keeper", "goalkeeper")),
    # "verdediging" staat er los naast "verdediger": op "verdedig" toetsen zou
    # korter zijn, maar dan valt "verdedigende middenvelder" ook in deze regel
    # en staat het halve middenveld achterin.
    ("D", ("verdediger", "verdediging", "back", "defender", "libero")),
    ("M", ("middenvelder", "midden", "half", "midfield")),
    ("F", ("spits", "aanval", "buiten", "vleugel", "forward", "striker",
           "winger", "attack")),
]


def positieletter(positie: str | None) -> str | None:
    """Vertaalt een uitgeschreven positie naar G, D, M of F. None als het niet lukt."""
    if not positie:
        return None
    kaal = positie.strip()
    # Een waarde die al een letter is laten we staan. Dat is geen theorie: de
    # Sofascore-export schrijft de positie zo, en die export is waar de bouwer
    # tegenaan getoetst wordt.
    if kaal.upper() in ("G", "D", "M", "F"):
        return kaal.upper()
    kaal = kaal.lower()
    for letter, woorden in POSITIEREGELS:
        if any(w in kaal for w in woorden):
            return letter
    return None


# ─── Nationaliteit ───────────────────────────────────────────────────────────

def landcodes(html_pad: Path = DASHBOARD_HTML) -> dict[str, str]:
    """
    Landnaam → alpha-2, gelezen uit de tabel die het dashboard zélf gebruikt.

    Transfermarkt.nl geeft de nationaliteit als Nederlandse landnaam; het
    dashboard heeft een vlag nodig en een alpha-2-code om op te filteren. Die
    vertaling staat al in dashboard.html, in A2_NAMES. Door hem daar te lezen in
    plaats van hier over te typen kan de vlag nooit een ander land aanwijzen dan
    de naam ernaast.
    """
    if not html_pad.exists():
        return {}
    tekst = html_pad.read_text("utf-8")
    m = re.search(r"const A2_NAMES=\{(.*?)\};", tekst, re.S)
    if not m:
        return {}
    # Sleutels staan zonder aanhalingstekens, waarden met enkele of dubbele
    # (bs:"Bahama's"). Op paren toetsen in plaats van op komma's splitsen
    # scheelt gepuzzel met leestekens binnen een naam.
    paren = re.findall(r"(\w+):\s*(?:'([^']*)'|\"([^\"]*)\")", m.group(1))
    return {(enkel or dubbel): a2 for a2, enkel, dubbel in paren}


# Transfermarkt spelt een handvol landen anders dan de tabel in het dashboard.
# Dit is geen tweede landenlijst maar een lijst verschillen, opgesteld uit wat
# de run als onbekend meldde — en dat is precies waar dat rapport voor is.
#
# Sint Maarten staat er niet bij en krijgt dus geen vlag. Zijn ISO-code is `sx`,
# maar in de tabel van het dashboard is `sx` Schotland (zo noemt Sofascore het).
# Hem toch op `sx` zetten zou één speler een Schotse vlag geven, en een verkeerde
# vlag is erger dan geen vlag.
SPELWIJZE = {
    "Democratische Republiek Congo": "cd",
    "Republiek Congo": "cg",
    "Bosnië en Herzegovina": "ba",
    "Trinidad en Tobago": "tt",
    "Haiti": "ht",
    "Wit-Rusland": "by",
    "Benin": "bj",
}


def alpha2(nationaliteit: str | None, tabel: dict[str, str]) -> str | None:
    """Zoekt de alpha-2-code bij een landnaam, hoofdletterongevoelig."""
    if not nationaliteit:
        return None
    naam = nationaliteit.strip()
    if naam in tabel:
        return tabel[naam]
    if naam in SPELWIJZE:
        return SPELWIJZE[naam]
    klein = {k.lower(): v for k, v in tabel.items()}
    klein.update({k.lower(): v for k, v in SPELWIJZE.items()})
    return klein.get(naam.lower())


# ─── Leeftijd ────────────────────────────────────────────────────────────────

def leeftijd_op(geboren: str, datum: str) -> tuple[int, int] | None:
    """
    Leeftijd op een wedstrijddag, als (volle jaren, dagen sinds de verjaardag).

    Wie op 29 februari geboren is heeft in drie van de vier jaren geen
    verjaardag. Dan telt 28 februari, zodat het aantal dagen een echt getal
    blijft in plaats van nul — nul zou zeggen "vandaag jarig", en dat is een
    ander feit dan "geen verjaardag dit jaar".
    """
    try:
        g = date.fromisoformat(geboren)
        d = date.fromisoformat(datum)
    except (TypeError, ValueError):
        return None
    if d < g:
        return None

    def verjaardag(jaar: int) -> date:
        try:
            return g.replace(year=jaar)
        except ValueError:
            return date(jaar, 2, 28)

    jaren = d.year - g.year
    if verjaardag(d.year) > d:
        jaren -= 1
    return jaren, (d - verjaardag(g.year + jaren)).days


# ─── Optellingen over de wedstrijden ─────────────────────────────────────────

def etiket(w: dict) -> str:
    """Leesbaar wedstrijdlabel, zoals het dashboard het toont."""
    return (f"{(w.get('home_team') or {}).get('name', '?')} "
            f"{w.get('home_score', '?')}-{w.get('away_score', '?')} "
            f"{(w.get('away_team') or {}).get('name', '?')}")


def doelpunten(w: dict) -> int | None:
    """De eindstand opgeteld. None als de stand ontbreekt."""
    h, u = w.get("home_score"), w.get("away_score")
    if h is None or u is None:
        return None
    return h + u


def sleutelmaker(paren: list[tuple]) -> callable:
    """
    Bepaalt op welke sleutel twee records samengevoegd worden.

    Hetzelfde id is hetzelfde ding. Heeft een record geen id, dan hoort het bij
    de groep met dezelfde naam, als die bestaat: De Kuip staat in de eigen data
    drie keer, twee keer met id 612 en één keer zonder, en dat is één stadion en
    geen twee. Bestaat er geen groep met die naam, dan wordt de naam zelf de
    sleutel — zo telt een stadion zonder id nog steeds als bezocht.

    Alleen op naam groeperen kan niet. Amsterdam ArenA en Johan Cruijff ArenA
    zijn hetzelfde gebouw onder twee namen, en alleen het id weet dat.
    """
    id_bij_naam = {}
    for pid, naam in paren:
        if pid is not None and naam and naam not in id_bij_naam:
            id_bij_naam[naam] = pid

    def sleutel(pid, naam):
        if pid is not None:
            return ("id", pid)
        if naam in id_bij_naam:
            return ("id", id_bij_naam[naam])
        return ("naam", naam)

    return sleutel


def op_datum(wedstrijden: list[dict]) -> list[dict]:
    """Oudste eerst, zodat bij het optellen de nieuwste naam het laatste woord
    heeft. Een competitie die van sponsor wisselt hoort onder de naam te staan
    waaronder je hem nu kent."""
    return sorted(wedstrijden, key=lambda w: w.get("date") or "")


def tel_clubs(wedstrijden: list[dict]) -> list[dict]:
    """Elke club die je hebt zien spelen, met hoe vaak en thuis of uit."""
    wedstrijden = op_datum(wedstrijden)
    sleutel = sleutelmaker([((w.get(f"{k}_team") or {}).get("id"),
                             (w.get(f"{k}_team") or {}).get("name"))
                            for w in wedstrijden for k in ("home", "away")])
    clubs: dict = {}
    for w in wedstrijden:
        for kant, veld in (("home", "as_home"), ("away", "as_away")):
            t = w.get(f"{kant}_team") or {}
            if not (t.get("id") is not None or t.get("name")):
                continue
            c = clubs.setdefault(sleutel(t.get("id"), t.get("name")), {
                "id": t.get("id"), "name": t.get("name", ""),
                "slug": t.get("slug", ""), "logo_url": "", "matches_count": 0,
                "as_home": 0, "as_away": 0,
            })
            c["matches_count"] += 1
            c[veld] += 1
            c["name"], c["id"] = t.get("name", c["name"]), t.get("id") or c["id"]
            if t.get("logo_url"):
                c["logo_url"] = t["logo_url"]
    return sorted(clubs.values(), key=lambda c: (-c["matches_count"], c["name"]))


# Transfermarkt noemt hetzelfde gebouw per wedstrijd anders: bij de ArenA naar
# de naam van dat seizoen, bij De Kuip nu eens kort en dan eens voluit. Zonder
# deze tabel staan die stadions twee keer in de lijst. De officiële naam van nu
# wint — dat is de afspraak; wie liever de historische naam ziet (in 2018 de
# Amsterdam ArenA, in 2025 de Johan Cruijff ArenA) haalt de regel hier weg.
#
# Alleen namen die écht hetzelfde gebouw zijn horen hier. Een stadion dat is
# vervangen door nieuwbouw op dezelfde plek is een ander stadion.
STADIONNAMEN = {
    'Stadion Feyenoord "De Kuip"': "De Kuip",
    "Amsterdam ArenA": "Johan Cruijff ArenA",
}


def hernoem_stadions(wedstrijden: list[dict]) -> list[dict]:
    """Zet de stadionnamen om naar de naam die wint, vóór er geteld wordt.

    Vóór het tellen, want anders telt de stadionlijst twee bezoeken aan één
    gebouw als twee stadions — en na het tellen zou de wedstrijd zelf nog steeds
    de oude naam tonen. De wedstrijden zelf blijven ongemoeid; er gaat een kopie
    doorheen.
    """
    uit = []
    for w in wedstrijden:
        v = w.get("venue") or {}
        nieuw = STADIONNAMEN.get(v.get("name"))
        uit.append({**w, "venue": {**v, "name": nieuw}} if nieuw else w)
    return uit


def stadionwissels(wedstrijden: list[dict]) -> list[tuple[str, str, int, bool]]:
    """Wat de aliastabel deed: per regel het aantal wedstrijden en of hij samenvoegt.

    Een aliastabel is stille code: staat er een spelfout in een sleutel, dan doet
    die regel niets en merk je dat nergens aan. Vandaar dat het rapport hem
    hardop naleest. Een regel die wel omzet maar niets samenvoegt (de doelnaam
    komt verder niet voor) verandert alleen het label, niet de telling — ook dat
    is het vermelden waard, want dat is precies het verschil tussen 41 en 39
    stadions.
    """
    namen: dict = {}
    for w in wedstrijden:
        naam = (w.get("venue") or {}).get("name")
        if naam:
            namen[naam] = namen.get(naam, 0) + 1
    return [(van, naar, namen.get(van, 0), namen.get(naar, 0) > 0)
            for van, naar in sorted(STADIONNAMEN.items())]


def tel_stadions(wedstrijden: list[dict]) -> list[dict]:
    """Elk stadion, met bezoeken, eerste en laatste keer, en het volste huis."""
    wedstrijden = op_datum(wedstrijden)
    sleutel = sleutelmaker([((w.get("venue") or {}).get("id"),
                             (w.get("venue") or {}).get("name")) for w in wedstrijden])
    stadions: dict = {}
    for w in wedstrijden:
        v = w.get("venue") or {}
        naam = v.get("name")
        if not naam:
            continue
        s = stadions.setdefault(sleutel(v.get("id"), naam), {
            "id": v.get("id"), "name": naam, "city": v.get("city", ""),
            "matches_count": 0, "first_visit": None, "last_visit": None,
            "max_attendance": None,
        })
        s["matches_count"] += 1
        # De nieuwste naam en stad winnen; het id blijft staan zodra het er is.
        s["name"], s["id"] = naam, v.get("id") or s["id"]
        if v.get("city"):
            s["city"] = v["city"]
        datum = w.get("date")
        if datum:
            if s["first_visit"] is None or datum < s["first_visit"]:
                s["first_visit"] = datum
            if s["last_visit"] is None or datum > s["last_visit"]:
                s["last_visit"] = datum
        bezoek = w.get("attendance")
        if bezoek and (s["max_attendance"] is None or bezoek > s["max_attendance"]):
            s["max_attendance"] = bezoek
    return sorted(stadions.values(), key=lambda s: (-s["matches_count"], s["name"]))


def tel_op_veld(wedstrijden: list[dict], veld: str, id_veld: str | None = None) -> list[dict]:
    """
    Telt hoe vaak elke waarde van een veld voorkomt (toernooi, seizoen).

    Op het id groeperen en niet op de naam, want competities wisselen van
    sponsor: 'Eredivisie' en 'VriendenLoterij Eredivisie' dragen allebei id 37
    en zijn één competitie. Twee regels in de lijst zou zeggen dat je in twee
    verschillende competities hebt gezeten.
    """
    wedstrijden = op_datum(wedstrijden)
    sleutel = sleutelmaker([(w.get(id_veld) if id_veld else None, w.get(veld))
                            for w in wedstrijden])
    tellingen: dict = {}
    for w in wedstrijden:
        naam = w.get(veld)
        if not naam:
            continue
        pid = w.get(id_veld) if id_veld else None
        t = tellingen.setdefault(sleutel(pid, naam), {
            "id": pid, "name": naam, "matches_count": 0,
        })
        t["matches_count"] += 1
        t["name"], t["id"] = naam, pid or t["id"]
    return sorted(tellingen.values(), key=lambda t: (-t["matches_count"], t["name"]))


def tel_scheidsrechters(wedstrijden: list[dict]) -> list[dict]:
    """Elke scheidsrechter, met zijn wedstrijden en de kaarten die daarin vielen."""
    wedstrijden = op_datum(wedstrijden)
    sleutel = sleutelmaker([((w.get("referee") or {}).get("id"),
                             (w.get("referee") or {}).get("name")) for w in wedstrijden])
    refs: dict = {}
    for w in wedstrijden:
        r = w.get("referee") or {}
        naam = r.get("name")
        if not naam:
            continue
        s = refs.setdefault(sleutel(r.get("id"), naam), {
            "id": r.get("id"), "name": naam, "matches_count": 0,
            "total_yellows_in_matches": 0, "total_reds_in_matches": 0,
            "matches": [],
        })
        s["matches_count"] += 1
        s["matches"].append(w.get("id"))
        for k in w.get("cards") or []:
            if k.get("type") in ("red", "yellowRed", "second_yellow"):
                s["total_reds_in_matches"] += 1
            else:
                s["total_yellows_in_matches"] += 1
    for s in refs.values():
        s["avg_yellows_per_match"] = (round(s["total_yellows_in_matches"]
                                            / s["matches_count"], 1)
                                      if s["matches_count"] else 0.0)
    return sorted(refs.values(), key=lambda s: (-s["matches_count"], s["name"]))


def bereken_records(wedstrijden: list[dict], spelers: list[dict]) -> dict:
    """De uitschieters: meeste goals, grootste zege, volste stadion, jongste en
    oudste speler die je hebt zien spelen."""
    records: dict = {}

    met_stand = [w for w in wedstrijden if doelpunten(w) is not None]
    if met_stand:
        meest = max(met_stand, key=lambda w: doelpunten(w))
        records["most_goals_single_match"] = {
            "count": doelpunten(meest), "match": etiket(meest),
            "date": meest.get("date", ""),
        }
        ruimst = max(met_stand,
                     key=lambda w: abs(w["home_score"] - w["away_score"]))
        records["biggest_win"] = {
            "match": etiket(ruimst), "date": ruimst.get("date", ""),
            "goal_diff": abs(ruimst["home_score"] - ruimst["away_score"]),
        }

    met_publiek = [w for w in wedstrijden if w.get("attendance")]
    if met_publiek:
        volst = max(met_publiek, key=lambda w: w["attendance"])
        records["highest_attendance"] = {
            "count": volst["attendance"], "match": etiket(volst),
            "venue": (volst.get("venue") or {}).get("name", ""),
            "date": volst.get("date", ""),
        }

    jongste = oudste = None
    for p in spelers:
        j, o = p.get("youngest_age_seen"), p.get("oldest_age_seen")
        if j and (jongste is None or
                  (j["age_years"], j["age_days"]) < (jongste[1]["age_years"],
                                                     jongste[1]["age_days"])):
            jongste = (p, j)
        if o and (oudste is None or
                  (o["age_years"], o["age_days"]) > (oudste[1]["age_years"],
                                                     oudste[1]["age_days"])):
            oudste = (p, o)
    for sleutel, gevonden in (("youngest_player", jongste), ("oldest_player", oudste)):
        if gevonden:
            p, a = gevonden
            records[sleutel] = {
                "name": p.get("name", ""), "age_years": a["age_years"],
                "age_days": a["age_days"], "date_of_birth": p.get("date_of_birth"),
                "match_date": a.get("date", ""), "match": a.get("match", ""),
            }
    return records


# ─── Spelers aanvullen ───────────────────────────────────────────────────────

def verrijk_spelers(spelers: list[dict], tabel: dict[str, str]) -> tuple[list[dict], dict]:
    """
    Vult per speler aan wat alleen uit de combinatie van profiel en wedstrijden
    volgt: de positieletter, de landcode, en de leeftijd op de jongste en oudste
    dag dat je hem hebt zien spelen.

    Geeft (spelers, ongewoon) terug, waarbij `ongewoon` de posities en
    nationaliteiten telt die niet te herleiden waren. Dat is geen foutmelding
    maar een boodschappenlijst: een positie die hier niet in past zet de speler
    buiten de opstelling, en dat wil je weten in plaats van ontdekken.
    """
    posities: dict[str, int] = defaultdict(int)
    landen: dict[str, int] = defaultdict(int)
    # Bijgehouden om te melden, niet om te gebruiken: wie er nog jonger of ouder
    # was maar die dag niet van de bank kwam. Zie de opmerking bij `minutes`.
    bank_jongste = bank_oudste = None
    uit = []
    for p in spelers:
        s = dict(p)

        ruwe_positie = s.get("position")
        letter = positieletter(ruwe_positie)
        if ruwe_positie and not letter:
            posities[ruwe_positie] += 1
        if ruwe_positie:
            s["position_detail"] = ruwe_positie
        s["position"] = letter

        a2 = alpha2(s.get("nationality"), tabel)
        if s.get("nationality") and not a2:
            landen[s["nationality"]] += 1
        s["nationality_alpha2"] = a2

        geboren = s.get("date_of_birth")
        jongste = oudste = None
        if geboren:
            for d in s.get("matches_detail") or []:
                # De bank telt niet mee. "Jongste ooit" staat in het dashboard
                # pal boven de XI, en die XI bestaat uit spelers die gespeeld
                # hebben; een zestienjarige die in trainingspak op de bank zat
                # heb je niet zien voetballen. De Sofascore-export las het
                # andersom en zette daar bankzitters neer. Het rapport noemt
                # allebei, zodat het een keuze blijft en geen aanname.
                if not (d.get("minutes") or 0) > 0:
                    continue
                leeftijd = leeftijd_op(geboren, d.get("date") or "")
                if leeftijd is None:
                    continue
                item = {"age_years": leeftijd[0], "age_days": leeftijd[1],
                        "date": d.get("date"), "match": d.get("match_label", "")}
                if jongste is None or leeftijd < (jongste["age_years"], jongste["age_days"]):
                    jongste = item
                if oudste is None or leeftijd > (oudste["age_years"], oudste["age_days"]):
                    oudste = item
            for d in s.get("matches_detail") or []:
                leeftijd = leeftijd_op(geboren, d.get("date") or "")
                if leeftijd is None:
                    continue
                staat = (s.get("name", ""), leeftijd[0], leeftijd[1], d.get("date"))
                if bank_jongste is None or leeftijd < bank_jongste[1:3]:
                    bank_jongste = staat
                if bank_oudste is None or leeftijd > bank_oudste[1:3]:
                    bank_oudste = staat
        s["youngest_age_seen"] = jongste
        s["oldest_age_seen"] = oudste
        uit.append(s)
    return uit, {"posities": dict(posities), "landen": dict(landen),
                 "bank_jongste": bank_jongste, "bank_oudste": bank_oudste}


# ─── Bouwen ──────────────────────────────────────────────────────────────────

def bouw(wedstrijden: list[dict], spelers: list[dict],
         tabel: dict[str, str]) -> tuple[dict, dict]:
    """Zet wedstrijden en spelers om naar het schema dat het dashboard leest."""
    wissels = stadionwissels(wedstrijden)
    wedstrijden = hernoem_stadions(wedstrijden)
    spelers, ongewoon = verrijk_spelers(spelers, tabel)
    ongewoon["stadionwissels"] = wissels
    data = sorted(w.get("date") for w in wedstrijden if w.get("date"))
    goals = [doelpunten(w) for w in wedstrijden]

    export = {
        "generated_at": datetime.now().isoformat(),
        "source": "transfermarkt",
        "total_matches": len(wedstrijden),
        "total_goals_witnessed": sum(g for g in goals if g is not None),
        "date_range": {"first": data[0] if data else None,
                       "last": data[-1] if data else None},
        "matches": sorted(wedstrijden, key=lambda w: w.get("date") or "", reverse=True),
        "players": spelers,
        "referees": tel_scheidsrechters(wedstrijden),
        "venues": tel_stadions(wedstrijden),
        "teams_visited": tel_clubs(wedstrijden),
        "tournaments": tel_op_veld(wedstrijden, "tournament", "tournament_id"),
        "seasons": tel_op_veld(wedstrijden, "season"),
        "records": bereken_records(wedstrijden, spelers),
    }
    return export, ongewoon


def rapporteer(export: dict, ongewoon: dict):
    """Legt de nieuwe export naast de oude, en noemt wat niet te herleiden was."""
    print(f"\n{'=' * 78}\n  EXPORT — {export['total_matches']} wedstrijden, "
          f"{len(export['players'])} spelers\n{'=' * 78}")

    oud = json.loads(OUD.read_text("utf-8")) if OUD.exists() else {}
    rijen = [("wedstrijden", export["total_matches"], oud.get("total_matches")),
             ("doelpunten", export["total_goals_witnessed"],
              oud.get("total_goals_witnessed")),
             ("spelers", len(export["players"]), len(oud.get("players") or [])),
             ("scheidsrechters", len(export["referees"]), len(oud.get("referees") or [])),
             ("stadions", len(export["venues"]), len(oud.get("venues") or [])),
             ("clubs", len(export["teams_visited"]), len(oud.get("teams_visited") or [])),
             ("toernooien", len(export["tournaments"]), len(oud.get("tournaments") or [])),
             ("seizoenen", len(export["seasons"]), len(oud.get("seasons") or []))]
    # Vóór de omwisseling staat er Sofascore naast; erna is 'oud' de vorige
    # Transfermarkt-run. Even bruikbaar, maar het label moet wel kloppen.
    kop = "vorige run" if paden.omgewisseld() else "was (Sofascore)"
    print(f"  {'':<18} {'Transfermarkt':>14}   {kop:>16}")
    print(f"  {'-' * 18} {'-' * 14}   {'-' * 16}")
    for naam, nieuw, was in rijen:
        pijl = "  " if was in (None, 0) else ("↑" if nieuw > was else
                                              ("↓" if nieuw < was else " "))
        print(f"  {naam:<18} {nieuw:>14} {pijl:>2} {was if was else '—':>16}")

    wissels = ongewoon.get("stadionwissels") or []
    if wissels:
        print("\n  ── de aliastabel voor stadionnamen ──")
        for van, naar, aantal, voegt_samen in wissels:
            if not aantal:
                teken, wat = "✗", "komt in deze data niet voor — sleutel klopt niet"
            elif voegt_samen:
                teken, wat = "✓", f"{aantal} wedstrijden, telt nu als één stadion"
            else:
                teken, wat = "·", f"{aantal} wedstrijden, alleen het label wijzigt"
            print(f"  {teken} {van!r} → {naar!r}")
            print(f"      {wat}")
        if any(not a for _, _, a, _ in wissels):
            print("  ✗ = die regel doet niets. Controleer de spelling tegen de "
                  "naam die Transfermarkt gebruikt.")

    p = export["players"]
    met_positie = sum(1 for s in p if s.get("position"))
    met_vlag = sum(1 for s in p if s.get("nationality_alpha2"))
    met_leeftijd = sum(1 for s in p if s.get("youngest_age_seen"))
    clubs = export["teams_visited"]
    met_foto = sum(1 for s in p if s.get("photo_url"))
    met_wapen = sum(1 for c in clubs if c.get("logo_url"))
    print(f"\n  {met_positie} van {len(p)} spelers in een linie (nodig voor de XI)")
    print(f"  {met_vlag} van {len(p)} met een landcode")
    print(f"  {met_leeftijd} van {len(p)} met een leeftijd op de wedstrijddag")
    print(f"  {met_foto} van {len(p)} met een portretfoto")
    print(f"  {met_wapen} van {len(clubs)} clubs met een wapen")

    for kop, telling, gevolg in (
            ("posities", ongewoon["posities"], "deze spelers vallen buiten de XI"),
            ("nationaliteiten", ongewoon["landen"], "deze spelers krijgen geen vlag")):
        if telling:
            print(f"\n  ▼ {len(telling)} onbekende {kop} — {gevolg}:")
            for naam, n in sorted(telling.items(), key=lambda x: -x[1])[:15]:
                print(f"    {n:>4}× {naam}")
            if len(telling) > 15:
                print(f"    ... en nog {len(telling) - 15}")

    rec = export["records"]
    if rec:
        print(f"\n  ── records ──")
        for sleutel in ("youngest_player", "oldest_player", "most_goals_single_match",
                        "biggest_win", "highest_attendance"):
            r = rec.get(sleutel)
            if not r:
                print(f"  {sleutel:<26} —")
            elif "age_years" in r:
                print(f"  {sleutel:<26} {r['name']} "
                      f"({r['age_years']}j {r['age_days']}d, {r['match_date']})")
            else:
                kop = r.get("count", r.get("goal_diff"))
                print(f"  {sleutel:<26} {kop} — {r['match']} ({r['date']})")

    # De bank-lezing erbij, zodat zichtbaar is wat de keuze kost.
    for sleutel, bank in (("youngest_player", ongewoon.get("bank_jongste")),
                          ("oldest_player", ongewoon.get("bank_oudste"))):
        r, richting = rec.get(sleutel), ("jongere" if "young" in sleutel else "oudere")
        if not (r and bank):
            continue
        naam, jaren, dagen, datum = bank
        if naam != r["name"]:
            print(f"    op de bank zat een {richting}: {naam} "
                  f"({jaren}j {dagen}d, {datum}) — niet meegeteld, hij speelde niet")


# ─── Zelftest ────────────────────────────────────────────────────────────────

def _w(mid, datum, thuis, uit, hs, aw, **rest):
    w = {"id": mid, "date": datum,
         "home_team": {"name": thuis, "id": hash(thuis) % 9999, "slug": thuis.lower()},
         "away_team": {"name": uit, "id": hash(uit) % 9999, "slug": uit.lower()},
         "home_score": hs, "away_score": aw, "cards": [], "goals": []}
    w.update(rest)
    return w


def zelftest() -> int:
    goed = fout = 0

    def toets(naam, gekregen, verwacht):
        nonlocal goed, fout
        if gekregen == verwacht:
            print(f"  ok   {naam}")
            goed += 1
        else:
            print(f"  FOUT {naam}\n       verwacht {verwacht!r}\n       kreeg    {gekregen!r}")
            fout += 1

    print("── positie ──")
    for ruw, verwacht in [
            ("Doelman", "G"), ("Keeper", "G"),
            ("Centrale verdediger", "D"), ("Linksback", "D"), ("Rechtsback", "D"),
            ("Linkervleugelverdediger", "D"),   # 'vleugel' mag niet winnen van 'verdediger'
            ("Vrije verdediger", "D"),
            ("Defensieve middenvelder", "M"), ("Centrale middenvelder", "M"),
            ("Aanvallende middenvelder", "M"),  # 'aanval' mag niet winnen van 'middenvelder'
            ("Linkshalf", "M"),
            ("Linksbuiten", "F"), ("Rechtsbuiten", "F"), ("Spits", "F"),
            ("Hangende spits", "F"),
            ("Goalkeeper", "G"), ("Centre-Back", "D"), ("Right Winger", "F"),
            ("  SPITS  ", "F"),                 # hoofdletters en spaties
            ("Verdediging", "D"),            # groepskop, geen aparte positie
            ("Verdedigende middenvelder", "M"),  # mag niet door "verdedig" heen vallen
            ("Trainer", None), ("", None), (None, None)]:
        toets(f"{ruw!r} → {verwacht}", positieletter(ruw), verwacht)

    print("\n── landcode ──")
    for ruw, verwacht in [("Democratische Republiek Congo", "cd"),
                          ("Republiek Congo", "cg"),
                          ("Bosnië en Herzegovina", "ba"),
                          ("Trinidad en Tobago", "tt"),
                          ("Wit-Rusland", "by"),
                          ("Benin", "bj"),
                          ("Sint Maarten", None)]:
        toets(f"{ruw} → {verwacht}", alpha2(ruw, landcodes()), verwacht)
    tabel = landcodes()
    toets("A2_NAMES uit dashboard.html gelezen", len(tabel) > 150, True)
    toets("Nederland → nl", alpha2("Nederland", tabel), "nl")
    toets("Duitsland → de", alpha2("Duitsland", tabel), "de")
    toets("België → be", alpha2("België", tabel), "be")
    toets("Ivoorkust → ci (dubbele aanhalingstekens)", alpha2("Ivoorkust", tabel), "ci")
    toets("Bahama's → bs (apostrof in de naam)", alpha2("Bahama's", tabel), "bs")
    toets("hoofdletterongevoelig", alpha2("nederland", tabel), "nl")
    toets("onbekend land geeft niets", alpha2("Atlantis", tabel), None)
    toets("leeg geeft niets", alpha2(None, tabel), None)

    print("\n── leeftijd ──")
    toets("de dag voor de verjaardag", leeftijd_op("2000-06-15", "2020-06-14"), (19, 365))
    toets("op de verjaardag", leeftijd_op("2000-06-15", "2020-06-15"), (20, 0))
    toets("de dag erna", leeftijd_op("2000-06-15", "2020-06-16"), (20, 1))
    toets("geboortedag zelf", leeftijd_op("2000-06-15", "2000-06-15"), (0, 0))
    toets("29 februari, in een schrikkeljaar", leeftijd_op("2004-02-29", "2024-02-29"), (20, 0))
    toets("29 februari, in een gewoon jaar", leeftijd_op("2004-02-29", "2023-02-28"), (19, 0))
    toets("vóór de geboorte bestaat niet", leeftijd_op("2000-06-15", "1999-01-01"), None)
    toets("onzin geeft niets", leeftijd_op("geen datum", "2020-01-01"), None)

    print("\n── optellingen ──")
    ws = [
        _w(1, "2024-01-10", "PSV", "Ajax", 2, 1, attendance=35000,
           venue={"name": "Philips Stadion", "city": "Eindhoven", "id": 7},
           referee={"name": "Higler", "id": 4610},
           cards=[{"type": "yellow"}, {"type": "red"}],
           tournament="Eredivisie", tournament_id="NL1", season="Eredivisie 23/24"),
        _w(2, "2024-02-20", "Ajax", "PSV", 0, 5, attendance=52000,
           venue={"name": "Johan Cruijff ArenA", "city": "Amsterdam", "id": 9},
           referee={"name": "Higler", "id": 4610},
           cards=[{"type": "yellow"}],
           tournament="Eredivisie", tournament_id="NL1", season="Eredivisie 23/24"),
        _w(3, "2023-11-05", "PSV", "Feyenoord", 3, 3,
           venue={"name": "Philips Stadion", "city": "Eindhoven", "id": 7},
           referee={"name": "Gozubuyuk", "id": 78563},
           tournament="KNVB Beker", tournament_id="NLP", season="KNVB Beker 23/24"),
    ]
    clubs = {c["name"]: c for c in tel_clubs(ws)}
    toets("PSV drie keer gezien", clubs["PSV"]["matches_count"], 3)
    toets("PSV twee keer thuis", clubs["PSV"]["as_home"], 2)
    toets("PSV één keer uit", clubs["PSV"]["as_away"], 1)
    toets("Feyenoord één keer", clubs["Feyenoord"]["matches_count"], 1)
    toets("vier clubs in totaal", len(clubs), 3)

    stadions = {s["name"]: s for s in tel_stadions(ws)}
    toets("Philips Stadion twee bezoeken", stadions["Philips Stadion"]["matches_count"], 2)
    toets("eerste bezoek is de vroegste datum",
          stadions["Philips Stadion"]["first_visit"], "2023-11-05")
    toets("laatste bezoek is de laatste datum",
          stadions["Philips Stadion"]["last_visit"], "2024-01-10")
    toets("hoogste opkomst, ook als een wedstrijd er geen heeft",
          stadions["Philips Stadion"]["max_attendance"], 35000)

    toernooien = {t["name"]: t for t in tel_op_veld(ws, "tournament", "tournament_id")}
    toets("Eredivisie twee keer", toernooien["Eredivisie"]["matches_count"], 2)
    toets("toernooi houdt zijn id", toernooien["Eredivisie"]["id"], "NL1")
    toets("bekerduel apart geteld", toernooien["KNVB Beker"]["matches_count"], 1)

    print("\n── samenvoegen ──")
    # De Kuip staat in de eigen data drie keer, één keer zonder id.
    kuip = [_w(11, "2008-06-01", "A", "B", 1, 0,
               venue={"name": "De Kuip", "city": "Rotterdam", "id": None}),
            _w(12, "2023-08-04", "C", "D", 1, 0,
               venue={"name": "De Kuip", "city": "Rotterdam", "id": 612}),
            _w(13, "2025-09-17", "E", "F", 1, 0,
               venue={"name": "De Kuip", "city": "Rotterdam", "id": 612})]
    st = tel_stadions(kuip)
    toets("stadion zonder id gaat op in de naamgenoot mét id", len(st), 1)
    toets("en telt gewoon mee", st[0]["matches_count"], 3)
    toets("het id blijft behouden", st[0]["id"], 612)
    toets("eerste bezoek is de wedstrijd zonder id", st[0]["first_visit"], "2008-06-01")

    # Eén gebouw onder twee namen: alleen het id weet dat.
    arena = [_w(21, "2010-01-01", "A", "B", 0, 0,
                venue={"name": "Amsterdam ArenA", "city": "Amsterdam", "id": 5}),
             _w(22, "2024-01-01", "A", "B", 0, 0,
                venue={"name": "Johan Cruijff ArenA", "city": "Amsterdam", "id": 5})]
    st = tel_stadions(arena)
    toets("twee namen onder één id blijven één stadion", len(st), 1)
    toets("de nieuwste naam wint", st[0]["name"], "Johan Cruijff ArenA")

    print("\n── de officiële naam wint ──")
    # Zonder id kan sleutelmaker twee namen niet aan elkaar knopen; de
    # aliastabel doet dat vóór het tellen. Transfermarkt geeft stadions geen id,
    # dus hier staat het op None — precies zoals in de echte data.
    tm = [_w(41, "2018-09-06", "A", "B", 0, 0,
             venue={"name": "Amsterdam ArenA", "city": "Amsterdam", "id": None}),
          _w(42, "2025-09-21", "A", "B", 0, 0,
             venue={"name": "Johan Cruijff ArenA", "city": "Amsterdam", "id": None})]
    toets("zonder de tabel zijn het twee stadions", len(tel_stadions(tm)), 2)
    st = tel_stadions(hernoem_stadions(tm))
    toets("met de tabel is het er één", len(st), 1)
    toets("onder de officiële naam", st[0]["name"], "Johan Cruijff ArenA")
    toets("en met beide bezoeken", st[0]["matches_count"], 2)

    kuip_tm = [_w(43, "2023-04-30", "A", "B", 0, 0,
                  venue={"name": 'Stadion Feyenoord "De Kuip"', "city": "Rotterdam",
                         "id": None}),
               _w(44, "2025-09-17", "A", "B", 0, 0,
                  venue={"name": "De Kuip", "city": "Rotterdam", "id": None})]
    st = tel_stadions(hernoem_stadions(kuip_tm))
    toets("De Kuip idem", (len(st), st[0]["name"], st[0]["matches_count"]),
          (1, "De Kuip", 2))

    toets("de wedstrijd zelf toont de nieuwe naam ook",
          (hernoem_stadions(kuip_tm)[0]["venue"]["name"]), "De Kuip")
    toets("de stad blijft staan",
          hernoem_stadions(kuip_tm)[0]["venue"]["city"], "Rotterdam")
    toets("de oorspronkelijke wedstrijd blijft ongemoeid",
          kuip_tm[0]["venue"]["name"], 'Stadion Feyenoord "De Kuip"')
    # De tabel hardop nalezen: wat deed elke regel, en deed hij iets?
    wissels = dict((van, (aantal, samen)) for van, _, aantal, samen
                   in stadionwissels(tm + kuip_tm))
    toets("een regel die samenvoegt wordt zo gemeld",
          wissels["Amsterdam ArenA"], (1, True))
    toets("De Kuip idem", wissels['Stadion Feyenoord "De Kuip"'], (1, True))
    alleen_oud = [_w(47, "2018-09-06", "A", "B", 0, 0,
                     venue={"name": "Amsterdam ArenA", "city": "Amsterdam", "id": None})]
    toets("zonder de nieuwe naam ernaast voegt de regel niets samen",
          dict((van, (a, sam)) for van, _, a, sam
               in stadionwissels(alleen_oud))["Amsterdam ArenA"], (1, False))
    toets("een sleutel die nergens voorkomt telt nul",
          dict((van, a) for van, _, a, _
               in stadionwissels([]))["Amsterdam ArenA"], 0)

    onbekend = [_w(45, "2020-01-01", "A", "B", 0, 0,
                   venue={"name": "Philips Stadion", "city": "Eindhoven", "id": None})]
    toets("een stadion dat niet in de tabel staat blijft zoals het was",
          hernoem_stadions(onbekend)[0]["venue"]["name"], "Philips Stadion")
    toets("een wedstrijd zonder stadion geeft geen fout",
          hernoem_stadions([_w(46, "2020-01-01", "A", "B", 0, 0, venue={})]
                           )[0]["venue"], {})

    # Een naam die nergens een id heeft blijft een eigen regel.
    los = [_w(31, "2020-01-01", "A", "B", 0, 0,
              venue={"name": "Gofferstadion", "city": "Nijmegen", "id": None}),
           _w(32, "2020-02-01", "A", "B", 0, 0,
              venue={"name": "Philips Stadion", "city": "Eindhoven", "id": 7})]
    toets("stadion zonder id nergens telt apart", len(tel_stadions(los)), 2)

    # Een competitie die van sponsor wisselt is één competitie.
    spons = [_w(41, "2018-01-01", "A", "B", 0, 0, tournament="Eredivisie", tournament_id=37),
             _w(42, "2024-01-01", "A", "B", 0, 0,
                tournament="VriendenLoterij Eredivisie", tournament_id=37)]
    tn = tel_op_veld(spons, "tournament", "tournament_id")
    toets("sponsorwissel splitst de competitie niet", len(tn), 1)
    toets("onder de naam waaronder je hem nu kent", tn[0]["name"], "VriendenLoterij Eredivisie")
    toets("beide wedstrijden geteld", tn[0]["matches_count"], 2)

    refs = {r["name"]: r for r in tel_scheidsrechters(ws)}
    toets("Higler twee wedstrijden", refs["Higler"]["matches_count"], 2)
    toets("Higler twee gele kaarten", refs["Higler"]["total_yellows_in_matches"], 2)
    toets("Higler één rode", refs["Higler"]["total_reds_in_matches"], 1)
    toets("gemiddelde per wedstrijd", refs["Higler"]["avg_yellows_per_match"], 1.0)
    toets("wedstrijden staan erbij", sorted(refs["Higler"]["matches"]), [1, 2])

    print("\n── records ──")
    ps = [
        {"id": 1, "name": "Jong", "date_of_birth": "2007-01-01", "position": "Spits",
         "nationality": "Nederland",
         "matches_detail": [{"date": "2024-01-10", "minutes": 90, "match_label": "PSV 2-1 Ajax"}]},
        {"id": 2, "name": "Oud", "date_of_birth": "1983-01-01", "position": "Doelman",
         "nationality": "Duitsland",
         "matches_detail": [{"date": "2024-02-20", "minutes": 90, "match_label": "Ajax 0-5 PSV"},
                            {"date": "2023-11-05", "minutes": 0, "match_label": "PSV 3-3 Feyenoord"}]},
    ]
    verrijkt, ongewoon = verrijk_spelers(ps, tabel)
    toets("geen onbekende posities", ongewoon["posities"], {})
    toets("geen onbekende landen", ongewoon["landen"], {})
    toets("spits wordt F", verrijkt[0]["position"], "F")
    toets("volledige positie blijft bewaard", verrijkt[0]["position_detail"], "Spits")
    toets("vlag gezet", verrijkt[1]["nationality_alpha2"], "de")
    toets("een bankzitter telt niet als gezien",
          verrijkt[1]["youngest_age_seen"]["date"], "2024-02-20")

    rec = bereken_records(ws, verrijkt)
    toets("meeste goals in één duel", rec["most_goals_single_match"]["count"], 6)
    toets("grootste zege", rec["biggest_win"]["goal_diff"], 5)
    toets("volste stadion", rec["highest_attendance"]["count"], 52000)
    toets("jongste speler", rec["youngest_player"]["name"], "Jong")
    toets("oudste speler", rec["oldest_player"]["name"], "Oud")

    print("\n── de hele export ──")
    export, _ = bouw(ws, ps, tabel)
    toets("wedstrijden geteld", export["total_matches"], 3)
    toets("doelpunten opgeteld", export["total_goals_witnessed"], 14)
    toets("eerste datum", export["date_range"]["first"], "2023-11-05")
    toets("laatste datum", export["date_range"]["last"], "2024-02-20")
    toets("nieuwste wedstrijd bovenaan", export["matches"][0]["id"], 2)
    toets("bron staat erbij", export["source"], "transfermarkt")

    leeg, _ = bouw([], [], tabel)
    toets("een lege bron geeft een lege export, geen fout",
          (leeg["total_matches"], leeg["total_goals_witnessed"],
           leeg["date_range"]["first"], leeg["records"]),
          (0, 0, None, {}))

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} van {goed + fout} fout")
    return 1 if fout else 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Bouw de dashboard-export uit Transfermarkt-data")
    p.add_argument("--uitvoer", help=f"schrijf naar dit bestand (standaard {UITVOER})")
    p.add_argument("--zelftest", action="store_true",
                   help="reken alle sommen na, zonder bestanden te schrijven")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    for pad in (WEDSTRIJDEN, SPELERS):
        if not pad.exists():
            raise SystemExit(f"  {pad} ontbreekt — draai eerst transfermarkt_sync.py "
                             f"en transfermarkt_profiles.py")

    wedstrijden = json.loads(WEDSTRIJDEN.read_text("utf-8"))
    spelers = json.loads(SPELERS.read_text("utf-8"))
    print(f"  {len(wedstrijden)} wedstrijden in {WEDSTRIJDEN}")
    print(f"  {len(spelers)} spelers in {SPELERS}")

    tabel = landcodes()
    if not tabel:
        print(f"  ! {DASHBOARD_HTML} gaf geen landentabel — spelers krijgen geen vlag")

    export, ongewoon = bouw(wedstrijden, spelers, tabel)
    rapporteer(export, ongewoon)

    uit = Path(args.uitvoer) if args.uitvoer else UITVOER
    uit.write_text(json.dumps(export, ensure_ascii=False), "utf-8")
    print(f"\n  ✓ {uit} geschreven ({uit.stat().st_size / 1e6:.1f} MB)")
    if uit == OUD:
        print(f"    Dit is het bestand dat het dashboard leest; de vorige stand "
              f"is overschreven.")
    else:
        print(f"    {OUD} is ongewijzigd — vergelijk eerst, vervang daarna.")


if __name__ == "__main__":
    main()
