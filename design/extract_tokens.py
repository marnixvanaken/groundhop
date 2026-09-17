#!/usr/bin/env python3
"""
Leest de design tokens uit dashboard.html en schrijft design/tokens.json,
klaar voor import in Figma via de plugin 'Tokens Studio for Figma'.

De code is de bron van waarheid: draai dit script opnieuw zodra het
token-object T in dashboard.html verandert, en importeer tokens.json
opnieuw in Figma.

Gebruik:  python3 design/extract_tokens.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "dashboard.html"
TARGET = Path(__file__).resolve().parent / "tokens.json"

# Tokens die geen kleur zijn maar een CSS-filter of schaduw.
FILTER_KEYS = {"blur", "blurHeavy"}
SHADOW_KEYS = {"shadowGlass", "shadowGlassHover", "shadow", "shadowMd"}


def read_object(text, start):
    """Geeft de inhoud van het object-literal dat op index `start` opent."""
    assert text[start] == "{"
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i
    raise ValueError("Geen sluitende accolade gevonden")


def parse_pairs(body):
    """Alle waarden in T zijn enkel-gequote strings zonder escapes."""
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", body))


def extract_modes():
    text = SOURCE.read_text(encoding="utf-8")
    anchor = text.index("const T=isDark?")
    dark_start = text.index("{", anchor)
    dark_body, dark_end = read_object(text, dark_start)

    light_start = text.index("{", dark_end)
    light_body, _ = read_object(text, light_start)

    return parse_pairs(light_body), parse_pairs(dark_body)


def to_token_set(pairs):
    """Zet platte key/value paren om naar de Tokens Studio structuur."""
    colors, filters, shadows = {}, {}, {}
    for key, value in pairs.items():
        if key in FILTER_KEYS:
            filters[key] = {"value": value, "type": "other"}
        elif key in SHADOW_KEYS:
            shadows[key] = {"value": value, "type": "other"}
        else:
            colors[key] = {"value": value, "type": "color"}
    return {"color": colors, "filter": filters, "shadow": shadows}


# Waarden die in dashboard.html hardcoded in de componenten staan.
# Handmatig verzameld uit Card, Pill, SearchInput, StatBox, SectionTitle en nav.
CORE = {
    "spacing": {
        name: {"value": str(px), "type": "spacing"}
        for name, px in [
            ("xs", 4), ("sm", 8), ("md", 12), ("lg", 16), ("xl", 20), ("2xl", 24),
        ]
    },
    "radius": {
        name: {"value": str(px), "type": "borderRadius"}
        for name, px in [
            ("badge", 10), ("input", 14), ("card", 20), ("nav", 34), ("pill", 999),
        ]
    },
    "fontFamily": {
        "base": {"value": "Outfit", "type": "fontFamilies"},
    },
    "fontSize": {
        name: {"value": str(px), "type": "fontSizes"}
        for name, px in [
            ("caption", 10), ("label", 12), ("body", 15), ("title", 16),
            ("logo", 20), ("stat", 26),
        ]
    },
    "fontWeight": {
        name: {"value": str(w), "type": "fontWeights"}
        for name, w in [
            ("regular", 400), ("medium", 500), ("semibold", 600),
            ("bold", 700), ("heavy", 800), ("black", 900),
        ]
    },
}


def main():
    light, dark = extract_modes()
    doc = {
        "core": CORE,
        "light": to_token_set(light),
        "dark": to_token_set(dark),
        "$themes": [
            {
                "id": "light",
                "name": "Light",
                "group": "mode",
                "selectedTokenSets": {"core": "source", "light": "enabled"},
            },
            {
                "id": "dark",
                "name": "Dark",
                "group": "mode",
                "selectedTokenSets": {"core": "source", "dark": "enabled"},
            },
        ],
        "$metadata": {"tokenSetOrder": ["core", "light", "dark"]},
    }
    TARGET.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)} geschreven")
    print(f"  light: {len(light)} tokens")
    print(f"  dark:  {len(dark)} tokens")


if __name__ == "__main__":
    main()
