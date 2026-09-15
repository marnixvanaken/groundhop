#!/usr/bin/env python3
"""
Transfermarkt profielen — vul de spelerslaag aan met persoonsgegevens
=====================================================================

`transfermarkt_players.py` leidt af wie speelde en hoe lang, uit data die al
binnen is. Geboortedatum, nationaliteit, positie, lengte en marktwaarde staan
alleen op het spelersprofiel, en dat is één verzoek per speler.

Kosten: het profiel alleen is 1 verzoek. Transferhistorie en het verloop van de
marktwaarde komen uit twee losse ceapi-endpoints; die haalt hij alleen op voor
de spelers die je met --volledig aanwijst, want anders verdrievoudigt de run.

De spelers worden aflopend op speelminuten afgewerkt. Breek je af, dan heb je
de spelers die ertoe doen al binnen, en de volgende run pakt de rest op.

Gebruik
-------
    python3 transfermarkt_profiles.py --limit 25     # eerst een handvol
    python3 transfermarkt_profiles.py                # alles, uren werk
    python3 transfermarkt_profiles.py --volledig 150 # top 150 ook transfers
    python3 transfermarkt_profiles.py --rapport      # alleen de stand
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from datetime import date
from pathlib import Path

from transfermarkt_poc import (BASE, CEAPI_MARKTWAARDE, CEAPI_TRANSFERS,
                              fetch, haal_json, parse_player)

SPELERS = Path("data/tm_players.json")
CACHE = Path("data/tm_player_cache")
UITVOER = Path("data/tm_players_full.json")
DASHBOARD = Path("data/dashboard_data.json")

# Een run van 2759 profielen is een ander soort belasting dan 164 wedstrijden.
# De wachttijd staat daarom hoger, en is met --pauze te verhogen als Cloudflare
# alsnog begint af te remmen.
MIN_DELAY, MAX_DELAY = 3.0, 6.0


def wacht():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def haal_profiel(pid: int, volledig: bool, force: bool = False) -> dict | None:
    """Haalt en parst één spelersprofiel. Gebruikt de cache tenzij --force.

    Een profiel dat eerder zonder transfers is opgehaald wordt opnieuw gehaald
    zodra het wél volledig moet; andersom niet.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    pad = CACHE / f"{pid}.json"
    if pad.exists() and not force:
        bestaand = json.loads(pad.read_text("utf-8"))
        if bestaand.get("_volledig") or not volledig:
            return bestaand

    try:
        html = fetch(f"{BASE}/speler/profil/spieler/{pid}")
    except SystemExit as e:
        print(f"    ✗ profiel mislukt: {e}")
        return None

    transfers_data = mv_data = None
    if volledig:
        for sleutel, sjabloon in (("t", CEAPI_TRANSFERS), ("m", CEAPI_MARKTWAARDE)):
            wacht()
            try:
                data = haal_json(BASE + sjabloon.format(id=pid))
            except SystemExit:
                data = None            # ontbreekt: de rest blijft bruikbaar
            if sleutel == "t":
                transfers_data = data
            else:
                mv_data = data

    try:
        record, diag = parse_player(html, pid, transfers_data, mv_data)
    except Exception as e:
        print(f"    ✗ parsen mislukt: {type(e).__name__}: {e}")
        return None

    record["_volledig"] = volledig
    record["_gemist"] = [r[0] for r in diag.rows if r[1] == "GEMIST"]
    pad.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


# ─── Controle ────────────────────────────────────────────────────────────────

# Van mild naar ernstig. De volgorde is ook de rangorde waarmee we bij meerdere
# kandidaat-data de meest onschuldige verklaring kiezen.
VORMEN = ("één dag", "twee of drie dagen", "dag en maand verwisseld",
          "alleen het jaar", "geheel anders")


def vergelijk(tm: str, sofa: str) -> tuple:
    """Benoemt hóe twee geboortedata verschillen. Geeft (vorm, dagverschil)."""
    try:
        a, b = date.fromisoformat(tm), date.fromisoformat(sofa)
    except ValueError:
        return "geheel anders", 0
    dagen = (a - b).days
    if abs(dagen) == 1:
        return "één dag", dagen
    if a.year == b.year and a.day == b.month and a.month == b.day:
        return "dag en maand verwisseld", dagen
    if abs(dagen) <= 3:
        return "twee of drie dagen", dagen
    if (a.month, a.day) == (b.month, b.day):
        return "alleen het jaar", dagen
    return "geheel anders", dagen


def dichtstbij(tm: str, kandidaten) -> tuple:
    """Kiest uit de bekende data die met de mildste verklaring. Geeft (datum, vorm)."""
    beste = None
    for sofa in sorted(kandidaten):
        vorm, dagen = vergelijk(tm, sofa)
        sleutel = (VORMEN.index(vorm), abs(dagen))
        if beste is None or sleutel < beste[0]:
            beste = (sleutel, sofa, vorm)
    return beste[1], beste[2]


def tel_geboortedata(profielen: list[dict], op_naam: dict) -> tuple:
    """Vergelijkt de profielen met de bekende data. Geeft (vergeleken, gelijk,
    afwijkingen), waarbij elke afwijking (naam, tm, sofa, vorm, naamgenoot) is.

    Een naam die aan één van beide kanten bij meer dan één speler kan horen,
    bewijst niets meer; die markeren we als naamgenoot in plaats van als fout.
    """
    meervoudig = {n for n, v in op_naam.items() if len(v) > 1}
    tm_namen = Counter(p["name"] for p in profielen if p.get("name"))
    meervoudig |= {n for n, c in tm_namen.items() if c > 1}

    vergeleken = gelijk = 0
    afwijkend = []
    for p in profielen:
        naam, tm = p.get("name"), p.get("date_of_birth")
        kandidaten = op_naam.get(naam)
        if not kandidaten or not tm:
            continue
        vergeleken += 1
        if tm in kandidaten:
            gelijk += 1
            continue
        sofa, vorm = dichtstbij(tm, kandidaten)
        afwijkend.append((naam, tm, sofa, vorm, naam in meervoudig))
    return vergeleken, gelijk, afwijkend


def controleer(profielen: list[dict]) -> None:
    """Rekent de opgehaalde profielen na op wat onafhankelijk te toetsen is.

    Twee soorten controle. Ten eerste plausibiliteit: een geboortedatum in 1890
    of een lengte van 3 meter is geen gevuld veld maar een fout. Ten tweede een
    vergelijking met de Sofascore-data die er al ligt — staan twee bronnen op
    dezelfde naam met een andere geboortedatum, dan is er één mis, of het is een
    andere speler en zit de ID-koppeling fout.
    """
    dit_jaar = date.today().year
    ongerijmd = []
    for p in profielen:
        gb = p.get("date_of_birth") or ""
        if gb[:4].isdigit():
            jaar = int(gb[:4])
            if not (1930 <= jaar <= dit_jaar - 14):
                ongerijmd.append(f"{p.get('name')}: geboortejaar {jaar}")
        h = p.get("height_cm")
        if h and not (150 <= h <= 215):
            ongerijmd.append(f"{p.get('name')}: lengte {h} cm")
        mw = p.get("market_value")
        if mw is not None and not (0 <= mw <= 400_000_000):
            ongerijmd.append(f"{p.get('name')}: marktwaarde {mw}")

    print(f"\n  ── plausibiliteit ──")
    if ongerijmd:
        print(f"  ✗ {len(ongerijmd)} ongerijmde waarden:")
        for r in ongerijmd[:15]:
            print(f"    {r}")
    else:
        print(f"  ✓ geen ongerijmde geboortejaren, lengtes of marktwaarden")

    if not DASHBOARD.exists():
        return

    # Een naam kan bij twee spelers horen. Namen we per naam één geboortedatum,
    # dan verklaarden we de andere speler tot fout: Ben Davies staat met twee
    # data in de Sofascore-data en leverde zo altijd een afwijking op. Dus
    # verzamelen we per naam álle data die de bron kent, en is het gelijk zodra
    # de datum er één van is.
    oud = json.loads(DASHBOARD.read_text("utf-8")).get("players", [])
    op_naam: dict[str, set] = {}
    sofa_clubs: dict[str, set] = {}
    for p in oud:
        if p.get("name") and p.get("date_of_birth"):
            op_naam.setdefault(p["name"], set()).add(p["date_of_birth"])
            sofa_clubs.setdefault(p["name"], set()).update(p.get("teams_seen_for") or [])
    tm_clubs = {p["name"]: set(p.get("teams_seen_for") or [])
                for p in profielen if p.get("name")}

    # Een naam die aan beide kanten meer dan één speler kan zijn, bewijst niets
    # meer. Die tellen we apart, want een naamgenoot is geen parseerfout.
    vergeleken, gelijk, afwijkend = tel_geboortedata(profielen, op_naam)

    print(f"\n  ── geboortedatum tegen de Sofascore-data ──")
    print(f"  op naam te vergelijken   {vergeleken:>6}")
    print(f"  gelijk                   {gelijk:>6}")
    if not afwijkend:
        if vergeleken:
            print(f"  ✓ alle vergelijkbare geboortedata komen overeen")
        return
    print(f"  afwijkend                {len(afwijkend):>6}")

    naamgenoot = [r for r in afwijkend if r[4]]
    echt = [r for r in afwijkend if not r[4]]
    if naamgenoot:
        print(f"    naamgenoot mogelijk    {len(naamgenoot):>4}   "
              f"(naam hoort bij meer dan één speler)")
        print(f"    overig                 {len(echt):>4}")

    # De vorm van een afwijking zegt waar hij vandaan komt. Eén dag verschil
    # tussen twee bronnen is een dagkwestie, en als het bijna altijd dezelfde
    # kant op staat is het er één van de bron, niet van het profiel. Een datum
    # die nergens op lijkt is wél een verkeerd opgehaald profiel.
    print(f"\n  ── vorm van de afwijking ──")
    tellen = Counter(r[3] for r in echt)
    for vorm in VORMEN:
        if not tellen[vorm]:
            continue
        extra = ""
        if vorm in ("één dag", "twee of drie dagen"):
            later = sum(1 for r in echt if r[3] == vorm and r[1] > r[2])
            extra = f"   (TM later {later}, TM eerder {tellen[vorm] - later})"
        merk = "   ✗" if vorm == "geheel anders" else ""
        print(f"  {vorm:<26}{tellen[vorm]:>5}{extra}{merk}")

    anders = [r for r in echt if r[3] == "geheel anders"]
    if not anders:
        print(f"\n  ✓ geen enkele afwijking is meer dan een dag- of jaarkwestie;")
        print(f"    geen enkel profiel hoort bij een andere speler.")
        return
    # Bij een datum die nergens op lijkt is de vraag: is dit hetzelfde mens?
    # Daar is de club een getuige voor die los van de geboortedatum staat.
    # Zagen we de een bij Millwall en de ander alleen bij Vitesse, dan zijn het
    # twee spelers met dezelfde naam en klopt er niets mis.
    print(f"\n  ! Alleen 'geheel anders' kan een verkeerd profiel zijn.")
    print(f"    De clubs staan erbij: overlappen die niet, dan is het een naamgenoot.")
    for naam, tm, sofa, _, _ in anders[:25]:
        print(f"    {naam}: TM {tm} / Sofascore {sofa}")
        print(f"      TM  {', '.join(sorted(tm_clubs.get(naam, ()))) or '—'}")
        print(f"      SS  {', '.join(sorted(sofa_clubs.get(naam, ()))) or '—'}")
    if len(anders) > 25:
        print(f"    ... en nog {len(anders) - 25}")


# ─── Zelftest ────────────────────────────────────────────────────────────────

def zelftest() -> int:
    """Rekent de controle na op gevallen waarvan de uitkomst vaststaat.

    De controle is zelf een controlemiddel; als die verkeerd telt, verdwijnt een
    echte fout in een geruststellende categorie.
    """
    fouten = []

    def eis(omschrijving, werkelijk, verwacht):
        if werkelijk != verwacht:
            fouten.append(f"{omschrijving}: {werkelijk!r}, verwacht {verwacht!r}")

    # ── vorm van het verschil ──
    eis("dag later", vergelijk("2005-12-23", "2005-12-22")[0], "één dag")
    eis("dag eerder", vergelijk("1990-02-01", "1990-02-02")[0], "één dag")
    eis("over de maandgrens", vergelijk("2000-03-01", "2000-02-29")[0], "één dag")
    eis("over de jaargrens", vergelijk("2001-01-01", "2000-12-31")[0], "één dag")
    eis("twee dagen", vergelijk("2001-01-08", "2001-01-06")[0], "twee of drie dagen")
    eis("dag/maand om", vergelijk("1997-04-08", "1997-08-04")[0],
        "dag en maand verwisseld")
    eis("dag/maand om, andersom", vergelijk("2001-08-03", "2001-03-08")[0],
        "dag en maand verwisseld")
    eis("alleen het jaar", vergelijk("2000-11-28", "1999-11-28")[0], "alleen het jaar")
    eis("geheel anders", vergelijk("1993-04-24", "1995-08-11")[0], "geheel anders")
    eis("onleesbaar", vergelijk("", "1995-08-11")[0], "geheel anders")
    # Een verschil van drie dagen is geen verwisseling, ook al lijkt het erop.
    eis("drie dagen telt als dagkwestie",
        vergelijk("2000-07-20", "2000-07-18")[0], "twee of drie dagen")
    eis("dagverschil met teken", vergelijk("2005-12-23", "2005-12-22")[1], 1)
    eis("dagverschil andersom", vergelijk("1990-02-01", "1990-02-02")[1], -1)

    # ── de mildste verklaring wint ──
    eis("kiest de dichtstbijzijnde datum",
        dichtstbij("1993-04-25", {"1995-08-11", "1993-04-24"}),
        ("1993-04-24", "één dag"))

    # ── naamgenoten ──
    # Ben Davies staat in de Sofascore-data met twee data. Het profiel hoort bij
    # de ene; dat is gelijk, geen afwijking.
    v, g, a = tel_geboortedata(
        [{"name": "Ben Davies", "date_of_birth": "1993-04-24"}],
        {"Ben Davies": {"1993-04-24", "1995-08-11"}})
    eis("naamgenoot met rake datum", (v, g, len(a)), (1, 1, 0))

    # Hoort hij bij geen van beide, dan is het een afwijking, maar wel één die
    # als naamgenoot gemarkeerd staat.
    v, g, a = tel_geboortedata(
        [{"name": "Ben Davies", "date_of_birth": "1970-01-01"}],
        {"Ben Davies": {"1993-04-24", "1995-08-11"}})
    eis("naamgenoot zonder rake datum", (v, g, len(a)), (1, 0, 1))
    eis("als naamgenoot gemarkeerd", a[0][4], True)

    # Twee profielen met dezelfde naam maken die naam óók onbetrouwbaar.
    v, g, a = tel_geboortedata(
        [{"name": "Danilo", "date_of_birth": "1991-07-15"},
         {"name": "Danilo", "date_of_birth": "1999-04-07"}],
        {"Danilo": {"1991-07-15"}})
    eis("dubbele naam aan TM-kant", (v, g, len(a)), (2, 1, 1))
    eis("en die geldt als naamgenoot", a[0][4], True)

    # Een unieke naam met een afwijkende datum is wél een echte afwijking.
    v, g, a = tel_geboortedata(
        [{"name": "Paul Wanner", "date_of_birth": "2005-12-23"}],
        {"Paul Wanner": {"2005-12-22"}})
    eis("unieke naam, dag ernaast", (v, g, len(a)), (1, 0, 1))
    eis("niet als naamgenoot", a[0][4], False)
    eis("vorm meegegeven", a[0][3], "één dag")

    # Spelers zonder datum, of namen die de andere bron niet kent, tellen niet mee.
    v, g, a = tel_geboortedata(
        [{"name": "Onbekend", "date_of_birth": "2000-01-01"},
         {"name": "Paul Wanner", "date_of_birth": None},
         {"name": "Paul Wanner", "date_of_birth": "2005-12-22"}],
        {"Paul Wanner": {"2005-12-22"}})
    eis("alleen vergelijkbare spelers tellen", (v, g, len(a)), (1, 1, 0))

    if fouten:
        print(f"  ✗ {len(fouten)} van de gevallen klopt niet:")
        for f in fouten:
            print(f"    {f}")
        return 1
    print("  ✓ zelftest: de geboortedatumcontrole telt en classificeert goed")
    return 0


def main():
    p = argparse.ArgumentParser(description="Haal spelersprofielen op")
    p.add_argument("--limit", type=int, help="stop na zoveel spelers")
    p.add_argument("--volledig", type=int, default=0, metavar="N",
                   help="haal voor de N spelers met de meeste minuten ook "
                        "transfers en marktwaardeverloop op (3 verzoeken elk)")
    p.add_argument("--force", action="store_true", help="negeer de cache")
    p.add_argument("--rapport", action="store_true",
                   help="toon de stand en de controle, haal niets op")
    p.add_argument("--zelftest", action="store_true",
                   help="reken de geboortedatumcontrole na, haal niets op")
    p.add_argument("--pauze", type=float, metavar="SEC",
                   help="minimale wachttijd tussen verzoeken (standaard 3)")
    args = p.parse_args()

    if args.zelftest:
        raise SystemExit(zelftest())

    if args.pauze:
        global MIN_DELAY, MAX_DELAY
        MIN_DELAY, MAX_DELAY = args.pauze, args.pauze * 2
        print(f"  wachttijd {MIN_DELAY:.0f}-{MAX_DELAY:.0f}s tussen verzoeken")

    if not SPELERS.exists():
        raise SystemExit(f"  {SPELERS} ontbreekt — draai eerst transfermarkt_players.py")
    spelers = json.loads(SPELERS.read_text("utf-8"))
    print(f"  {len(spelers)} spelers in {SPELERS}")

    CACHE.mkdir(parents=True, exist_ok=True)
    volledig_ids = {s["id"] for s in spelers[:args.volledig]}

    te_doen = []
    for s in spelers:
        pad = CACHE / f"{s['id']}.json"
        wil_volledig = s["id"] in volledig_ids
        if args.force or not pad.exists():
            te_doen.append((s, wil_volledig))
        elif wil_volledig:
            bestaand = json.loads(pad.read_text("utf-8"))
            if not bestaand.get("_volledig"):
                te_doen.append((s, True))

    gecachet = len(list(CACHE.glob("*.json")))
    print(f"  {gecachet} al gecachet, {len(te_doen)} te doen")
    if args.volledig:
        print(f"  waarvan {len(volledig_ids)} ook transfers + marktwaardeverloop")

    if not args.rapport and te_doen:
        if args.limit:
            te_doen = te_doen[:args.limit]
            print(f"  beperkt tot {len(te_doen)}")
        verzoeken = sum(3 if v else 1 for _, v in te_doen)
        per = (MIN_DELAY + MAX_DELAY) / 2 + 0.7   # wachttijd plus ophaaltijd
        print(f"  ~{verzoeken} verzoeken, ruw geschat "
              f"{int(verzoeken * per) // 60} minuten\n")
        for i, (s, volledig) in enumerate(te_doen, 1):
            print(f"  [{i}/{len(te_doen)}] {s['name']} "
                  f"({s['minutes_played']} min){'  +transfers' if volledig else ''}")
            haal_profiel(s["id"], volledig, args.force)
            wacht()

    # Voeg de profielgegevens samen met de afgeleide spelerslaag.
    samen, zonder = [], 0
    for s in spelers:
        pad = CACHE / f"{s['id']}.json"
        if not pad.exists():
            zonder += 1
            samen.append(s)
            continue
        profiel = json.loads(pad.read_text("utf-8"))
        samengevoegd = dict(s)
        for k, v in profiel.items():
            if k.startswith("_") or k in ("id", "id_source"):
                continue
            # De afgeleide naam uit de opstelling is soms afgekort ("J. Veerman");
            # die van het profiel is volledig en wint.
            if v not in (None, "", [], {}):
                samengevoegd[k] = v
        samen.append(samengevoegd)

    met_profiel = [s for s in samen if s.get("date_of_birth")]
    print(f"\n  {len(met_profiel)} van {len(samen)} spelers met profiel"
          f"{f', {zonder} nog zonder' if zonder else ''}")

    controleer(met_profiel)

    schoon = [{k: v for k, v in s.items() if not k.startswith("_")} for s in samen]
    UITVOER.write_text(json.dumps(schoon, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n  ✓ {UITVOER} geschreven ({len(schoon)} spelers)")


if __name__ == "__main__":
    main()
