#!/usr/bin/env python3
"""
Draait alles nog op de Python die hier staat?
=============================================

De venv op de ontwikkelmachine draait Python 3.9 (zoals de macOS Command Line
Tools). Daar is `str | None` in een annotatie geen fout bij het inlezen maar bij
het uitvoeren — vandaar dat `server.py` er maanden mee weg kwam: hij struikelde
eerder al over een ontbrekende module en kwam nooit tot die regel.

Elke module hoort daarom `from __future__ import annotations` te dragen zodra
hij PEP 604 gebruikt. Deze toets rekent dat na op de hele map, zodat een nieuwe
module het niet opnieuw kan vergeten.

    python3 test/versie.test.py [3.9]
    python3 test/versie.test.py --zelftest
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAP = Path(__file__).resolve().parent.parent


def annotaties(boom: ast.AST):
    """Elke annotatie in dit bestand: argumenten, retourwaarden en variabelen."""
    for node in ast.walk(boom):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns:
                yield node.returns
            a = node.args
            for arg in a.args + a.kwonlyargs + a.posonlyargs:
                if arg.annotation:
                    yield arg.annotation
        elif isinstance(node, ast.AnnAssign) and node.annotation:
            yield node.annotation


def heeft_future(boom: ast.Module) -> bool:
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names)
               for n in boom.body)


def gebruikt_pep604(boom: ast.Module) -> bool:
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
               for ann in annotaties(boom) for n in ast.walk(ann))


def keur(pad: Path, doel: tuple[int, int]) -> str | None:
    """Geeft een reden terug als dit bestand niet op `doel` draait, anders None."""
    bron = pad.read_text("utf-8")
    try:
        ast.parse(bron, str(pad), feature_version=doel)
    except SyntaxError as e:
        return f"regel {e.lineno}: {e.msg}"
    boom = ast.parse(bron)
    if gebruikt_pep604(boom) and not heeft_future(boom):
        return "PEP 604-annotaties (X | Y) zonder 'from __future__ import annotations'"
    return None


def zelftest() -> int:
    """Kan deze toets überhaupt rood worden? Anders bewijst groen niets."""
    import tempfile
    goed = fout = 0

    def toets(wat, kreeg, verwacht):
        nonlocal goed, fout
        if kreeg == verwacht:
            goed += 1
            print(f"  ✓ {wat}")
        else:
            fout += 1
            print(f"  ✗ {wat}\n      kreeg:    {kreeg!r}\n      verwacht: {verwacht!r}")

    gevallen = [
        ("PEP 604 zonder de import wordt afgekeurd",
         "def f(x: str | None): pass", True),
        ("met de import mag het wel",
         "from __future__ import annotations\ndef f(x: str | None): pass", False),
        ("een retourwaarde telt ook",
         "def f() -> int | None: pass", True),
        ("en een variabele-annotatie",
         "x: int | None = None", True),
        ("een bitwise-of buiten een annotatie is geen probleem",
         "masker = 1 | 2", False),
        ("een match-statement bestaat niet op 3.9",
         "match x:\n    case 1: pass", True),
        ("gewone code is gewoon goed",
         "def f(x: str) -> str:\n    return x", False),
    ]
    with tempfile.TemporaryDirectory() as d:
        for wat, bron, verwacht_fout in gevallen:
            pad = Path(d) / "proef.py"
            pad.write_text(bron, "utf-8")
            toets(wat, keur(pad, (3, 9)) is not None, verwacht_fout)

    print(f"\n  alles goed ({goed})" if not fout else f"\n  {fout} fout, {goed} goed")
    return 1 if fout else 0


def main() -> int:
    if "--zelftest" in sys.argv:
        return zelftest()
    doel = (3, 9)
    if len(sys.argv) > 1:
        groot, klein = sys.argv[1].split(".")
        doel = (int(groot), int(klein))

    print(f"\n  Draait alles op Python {doel[0]}.{doel[1]}?\n")
    fout = 0
    for pad in sorted(MAP.glob("*.py")):
        reden = keur(pad, doel)
        if reden:
            fout += 1
            print(f"  ✗ {pad.name}: {reden}")
        else:
            print(f"  ✓ {pad.name}")
    print(f"\n  {'alles goed' if not fout else f'{fout} bestanden niet'}")
    return 1 if fout else 0


if __name__ == "__main__":
    raise SystemExit(main())
