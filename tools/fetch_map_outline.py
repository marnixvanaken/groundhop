#!/usr/bin/env python3
"""
Haalt de landsgrenzen op en schrijft een vereenvoudigde omtrek naar
data/europe_outline.json.

Waarom niet gewoon een kaartdienst: de gepubliceerde demo mag geen externe
afbeeldingen laden, dus kaarttegels vallen af. Vectoren kunnen wel mee in de
pagina, en dan werkt de kaart ook zonder netwerk.

Bron: Natural Earth (publiek domein), 110m admin-0. Eenmalig draaien; de
uitkomst staat in git zodat niemand anders hem hoeft op te halen.

  python3 tools/fetch_map_outline.py
"""

import json
import sys
from pathlib import Path

try:
    import requests
    from shapely.geometry import shape, box, mapping
except ImportError:
    sys.exit("ontbreekt: pip install requests shapely")

ROOT = Path(__file__).resolve().parent.parent
DOEL = ROOT / "data" / "europe_outline.json"
BRON = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "master/geojson/ne_110m_admin_0_countries.geojson")

# Ruim genoeg voor alles van Lissabon tot Malta, zonder de halve wereld.
UITSNEDE = box(-11.0, 34.0, 17.0, 56.5)
TOLERANTIE = 0.04   # graden; genoeg detail op een kaart van ~370 pixels breed
DECIMALEN = 3       # ~100 meter, ruim voldoende op deze schaal


def ringen(geom):
    """Alle buitenranden, zonder gaten: op dit formaat zijn die niet zichtbaar."""
    stukken = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for p in stukken:
        if p.is_empty:
            continue
        coords = [[round(x, DECIMALEN), round(y, DECIMALEN)]
                  for x, y in p.exterior.coords]
        # Een ring van minder dan vier punten tekent niets.
        if len(coords) >= 4:
            yield coords


def main():
    print(f"ophalen: {BRON.rsplit('/', 1)[-1]}")
    data = requests.get(BRON, timeout=120).json()

    landen = []
    for f in data["features"]:
        geom = shape(f["geometry"])
        if not geom.intersects(UITSNEDE):
            continue
        binnen = geom.intersection(UITSNEDE).simplify(TOLERANTIE, preserve_topology=True)
        stukken = list(ringen(binnen))
        if not stukken:
            continue
        naam = f["properties"].get("NAME") or f["properties"].get("ADMIN") or "?"
        landen.append({"name": naam, "rings": stukken})

    landen.sort(key=lambda l: l["name"])
    punten = sum(len(r) for l in landen for r in l["rings"])
    uit = {
        "_bron": "Natural Earth 110m admin-0 countries, publiek domein",
        "_uitsnede": [-11.0, 34.0, 17.0, 56.5],
        "_tolerantie": TOLERANTIE,
        "countries": landen,
    }
    DOEL.write_text(json.dumps(uit, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(f"{DOEL.relative_to(ROOT)}: {len(landen)} landen, {punten} punten, "
          f"{DOEL.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
