#!/usr/bin/env python3
"""
Zet de demopagina's om naar de vorm die het artifact-platform vraagt.

Twee verschillen met de gewone pagina's:
- De hoofdpagina levert alleen titel, stijl en inhoud; het platform zet er
  zelf een documentskelet omheen.
- Het platform kent drie themastanden, niet twee: een expliciete keuze zet
  data-theme op de wortel, en bij 'systeem' staat er niets. De donkere tokens
  moeten daarom twee keer staan, afgeschermd tegen elkaar.

Externe stijlbladen zijn geblokkeerd op één lettertypehost na, dus de
gedeelde css gaat inline mee in beide pagina's.

Gebruik:  python3 demo/build_artifact.py <doelmap>
"""

import re
import shutil
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
FONTS = '''<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&display=swap">'''


def themas(css):
    """Donkere tokens ook onder data-theme, zodat de keuze op het platform wint."""
    m = re.search(r'@media \(prefers-color-scheme: dark\)\{\n  :root\{\n(.*?)\n  \}\n\}', css, re.S)
    dark = m.group(1)
    return css.replace(m.group(0), f'''@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
{dark}
  }}
}}
:root[data-theme="dark"]{{
{dark}
}}''')


def onderdelen(pad):
    s = Path(pad).read_text(encoding="utf-8")
    eigen = re.search(r'<style>\n(.*?)\n</style>', s, re.S).group(1)
    body = re.search(r'<body>\n(.*?)\n</body>', s, re.S).group(1)
    titel = re.search(r'<title>(.*?)</title>', s).group(1)
    return eigen, body, titel


def controleer(doel):
    """Elk bestand dat de pagina's opvragen moet ook meegeleverd zijn.

    Twee keer ging hier iets mis: eerst ontbraken de portretten, daarna het
    gedeelde script, en beide keren zag je dat pas aan een leeg scherm. Een
    ontbrekend script is stiller dan een ontbrekende afbeelding, dus laat de
    bouw hier struikelen in plaats van de pagina.
    """
    verwijzingen = set()
    for pagina in doel.glob("*.html"):
        tekst = pagina.read_text(encoding="utf-8")
        for attr in ("src", "href"):
            verwijzingen |= set(re.findall(attr + r'="([^"#:]+?)"', tekst))
    # Ook wat de datavelden noemen: logo's en portretten staan daar als pad.
    for js in doel.glob("*-data.js"):
        verwijzingen |= set(re.findall(r'"((?:crests|players|tournaments)/[^"]+)"',
                                       js.read_text(encoding="utf-8")))

    ontbreekt = sorted(v for v in verwijzingen if not (doel / v).exists())
    if ontbreekt:
        raise SystemExit("ontbrekende bestanden in de bouw:\n  " + "\n  ".join(ontbreekt))
    print(f"  gecontroleerd: {len(verwijzingen)} verwijzingen, alles aanwezig")


def main():
    doel = Path(sys.argv[1])
    doel.mkdir(parents=True, exist_ok=True)
    gedeeld = themas((DEMO / "groundhop.css").read_text(encoding="utf-8"))

    # Hoofdpagina: zonder documentskelet, met een naam in plaats van een omschrijving.
    # Die heet hier index.html, dus ook de verwijzingen naar zichzelf om.
    eigen, body, _ = onderdelen(DEMO / "wedstrijddetail.html")
    body = body.replace('href="wedstrijddetail.html"', 'href="index.html"')
    (doel / "index.html").write_text(
        f"<title>GroundHop Wedstrijddetail</title>\n{FONTS}\n"
        f"<style>\n{gedeeld}\n\n{eigen}\n</style>\n\n{body}\n",
        encoding="utf-8")

    # Tweede scherm: wordt als los bestand geserveerd, dus compleet document.
    eigen, body, _ = onderdelen(DEMO / "stadiondetail.html")
    body = body.replace('href="wedstrijddetail.html"', 'href="index.html"')
    (doel / "stadiondetail.html").write_text(
        '<!DOCTYPE html>\n<html lang="nl">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">\n'
        "<title>Stadiondetail</title>\n" + FONTS + "\n"
        f"<style>\n{gedeeld}\n\n{eigen}\n</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n",
        encoding="utf-8")

    for naam in ["groundhop.js", "match-data.js", "venue-data.js"]:
        shutil.copyfile(DEMO / naam, doel / naam)

    # Alle beeldmappen mee, niet alleen de clublogo's: zonder de portretten
    # valt de opstelling terug op initialen en is het verschil juist weg.
    for map_ in ["crests", "players", "tournaments"]:
        bron = DEMO / map_
        if not bron.is_dir():
            continue
        (doel / map_).mkdir(exist_ok=True)
        for f in bron.iterdir():
            shutil.copyfile(f, doel / map_ / f.name)

    controleer(doel)

    for f in sorted(doel.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(doel)}  {f.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
