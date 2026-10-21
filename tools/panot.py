"""Generate the panot-de-flor pavement tiles and write them into page_template.html.

The geometry follows Wikimedia Commons' 'Flower of Barcelona.svg' (a 116-unit tile): four petal
rings with raised discs, a raised centre disc in its own ring, joints at the tile edges.
Change the shades below, then run:  python3 tools/panot.py
"""
import re, sys, urllib.parse
from pathlib import Path

PETALS = [(39.85, 39.85), (76.15, 39.85), (39.85, 76.15), (76.15, 76.15)]

def tile(groove, groove_op, joint, joint_op, hi, hi_op, shade_op):
    inner = "".join(f"<circle cx='{x}' cy='{y}' r='12.95' fill='#000'/>" for x, y in PETALS)
    outer = "".join(f"<circle cx='{x}' cy='{y}' r='20.85'/>" for x, y in PETALS) + "<circle cx='58' cy='58' r='22.4'/>"
    # recess = petal rings + ring round the centre; raised = petal discs (trimmed at r 22.4) + centre disc
    mask = (f"<mask id='m'><rect width='116' height='116' fill='#fff'/>{inner}"
            f"<circle cx='58' cy='58' r='22.4' fill='#fff'/><circle cx='58' cy='58' r='13.9' fill='#000'/></mask>")
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='116' height='116' viewBox='0 0 116 116'>"
        f"<defs>{mask}</defs>"
        # groove floor, plus a darker copy nudged up-left: the shadow cast by the groove's upper wall
        f"<g mask='url(#m)'><g fill='{groove}' opacity='{groove_op}'>{outer}</g>"
        f"<g fill='{groove}' opacity='{shade_op}' transform='translate(-1.6 -1.6)'>{outer}</g></g>"
        # joints: dark on the right and bottom edge, a lit bevel on the top and left
        f"<path d='M115 0V116M0 115H116' stroke='{joint}' stroke-opacity='{joint_op}' stroke-width='2.4' fill='none'/>"
        f"<path d='M1.6 0V113.8M0 1.6H113.8' stroke='{hi}' stroke-opacity='{hi_op}' stroke-width='2' fill='none'/>"
        "</svg>"
    )
    return 'url("data:image/svg+xml,' + urllib.parse.quote(svg, safe="=:/ '") + '")'

LIGHT = tile("#4a4337", .09, "#3a362f", .16, "#ffffff", .55, .05)
LIGHT_STRONG = tile("#4a4337", .16, "#3a362f", .28, "#ffffff", .7, .09)
DARK = tile("#000000", .26, "#000000", .5, "#ffffff", .03, .12)
DARK_STRONG = tile("#000000", .34, "#000000", .6, "#ffffff", .05, .16)

path = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'page_template.html'
h = open(path, encoding="utf-8").read()
it = iter([LIGHT, DARK, DARK]); h = re.sub(r'--panot: url\("[^"]*"\);', lambda m: f"--panot: {next(it)};", h)
it = iter([LIGHT_STRONG, DARK_STRONG, DARK_STRONG]); h = re.sub(r'--panot-strong: url\("[^"]*"\);', lambda m: f"--panot-strong: {next(it)};", h)
open(path, "w", encoding="utf-8").write(h)
print("patched", h.count("--panot: url("), h.count("--panot-strong: url("), "tokens;", len(LIGHT), "chars per tile")
