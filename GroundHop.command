#!/bin/bash
# GroundHop starten: dubbelklik dit bestand in Finder.
#
# Haalt de nieuwste versie op, installeert wat ontbreekt, start de server en
# opent de app in je browser. Laat het venster open zolang je GroundHop
# gebruikt; sluit het om te stoppen.

cd "$(dirname "$0")" || exit 1
echo ""
echo "  ⚽ GroundHop"
echo "  ─────────────────────────────"

# Draait hij al (bijvoorbeeld in een ander venster)? Dan alleen de app openen.
if curl -s -o /dev/null --max-time 2 http://localhost:4000/api/bron; then
  echo "  ✓ Draait al — de app gaat open."
  open http://localhost:4000
  exit 0
fi

# Nieuwste versie. --autostash zet je eigen, nog niet gepubliceerde data even
# opzij en daarna terug. Lukt het niet (je kopie wijkt af), dan start hij de
# versie die er staat en zegt hij dat.
if git pull --ff-only --autostash -q 2>/tmp/groundhop-pull.log; then
  echo "  ✓ Nieuwste versie"
else
  echo "  ! Bijwerken lukte niet; ik start de versie die er staat."
  sed 's/^/    /' /tmp/groundhop-pull.log
fi

if ! python3 -c "import curl_cffi, bs4, lxml, rich" 2>/dev/null; then
  echo "  … onderdelen installeren (eenmalig)"
  python3 -m pip install --user -q -r requirements.txt
fi

# Clubnummers voor de albums opzoeken (alleen als er een ontbreekt), en wat
# daardoor veranderde meteen live zetten.
python3 collecties_vul.py
python3 publiceer.py --als-gekoppeld

python3 app/build_app_data.py >/dev/null 2>&1 && echo "  ✓ App-data bijgewerkt"

( sleep 2; open http://localhost:4000 ) &
echo "  ✓ Server start — laat dit venster open, sluit het om te stoppen."
echo ""
exec python3 server.py
