"""Glyph designs for Parchment Hand.

Coordinates are in *source pixels*: (0, 0) is the centre of the bottom-left
pixel of the glyph (column 0, baseline row). Caps occupy rows 0-9, lowercase
x-height rows 0-7, digits rows 0-8, descenders down to row -2. One pixel is
PX font units, so at 1000/PX ppem the font lands back on the source grid.

Each glyph is a set of centreline strokes (SVG path data, absolute M/L/C/Z
only) drawn with an elliptical nib, plus filled shapes (dots).
"""
import math
import re

PX = 70
K = 0.5523
NUM = r"-?\d+(?:\.\d+)?"


def px(d):
    """Convert a path in pixel coordinates to font units."""
    return re.sub(NUM, lambda m: f"{(float(m.group(0)) + 0.5) * PX:.1f}", d)


def ell(cx, cy, rx, ry):
    kx, ky = rx * K, ry * K
    return (f"M {cx} {cy + ry} C {cx + kx} {cy + ry} {cx + rx} {cy + ky} {cx + rx} {cy} "
            f"C {cx + rx} {cy - ky} {cx + kx} {cy - ry} {cx} {cy - ry} "
            f"C {cx - kx} {cy - ry} {cx - rx} {cy - ky} {cx - rx} {cy} "
            f"C {cx - rx} {cy + ky} {cx - kx} {cy + ry} {cx} {cy + ry} Z")


def dot(cx, cy, r=1.5):
    return ell(cx, cy, r, r)


def blob(cx, cy, rx=1.5, ry=1.32, angle=30, flat=(1,), kflat=0.36):
    """An irregular dot: a squashed oval tilted by `angle` degrees (leaning
    right), with the listed quadrants flattened (0 top-right, 1 bottom-right,
    2 bottom-left, 3 top-left, before rotation). The source's dots are 3x3
    blobs missing a corner or two, not circles."""
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)

    def rot(x, y):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)

    pts = [(0, ry), (rx, 0), (0, -ry), (-rx, 0)]
    segs = []
    for i in range(4):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % 4]
        k = kflat if i in flat else K
        c1 = (x0 + k * (x1 if x0 == 0 else 0), y0 + k * (y1 if y0 == 0 else 0))
        c2 = (x1 + k * (x0 if x1 == 0 else 0), y1 + k * (y0 if y1 == 0 else 0))
        segs.append((rot(*c1), rot(*c2), rot(x1, y1)))
    sx, sy = rot(*pts[0])
    d = f"M {sx:.3f} {sy:.3f} " + " ".join(
        f"C {a[0]:.3f} {a[1]:.3f} {b[0]:.3f} {b[1]:.3f} {c[0]:.3f} {c[1]:.3f}" for a, b, c in segs)
    return d + " Z"


def _maxx(d):
    nums = [float(n) for n in re.findall(NUM, d)]
    return max(nums[0::2]) if nums else 0


def G(s=(), f=(), adv=None, rough=None):
    s, f = list(s), list(f)
    if adv is None:
        mx = max([_maxx(d) for d in s + f] or [0])
        adv = math.floor(mx + 0.5) + 2
    return dict(s=[px(d) for d in s], f=[px(d) for d in f], adv=adv * PX, src_s=s, src_f=f, rough=rough)


def mirror_x(d, w):
    """Mirror a pixel-space path horizontally about x = w/2."""
    out, idx = [], 0
    for tok in re.split(f"({NUM})", d):
        if re.fullmatch(NUM, tok or ""):
            v = float(tok)
            out.append(f"{(w - v) if idx % 2 == 0 else v:g}")
            idx += 1
        else:
            out.append(tok)
    return "".join(out)


def quote_l(x):  # ‘ : head top-left, tail runs down to the right
    return [f"M {x} 9 C {x + 0.3} 8 {x + 0.7} 7 {x + 1} 6"], [dot(x + 0.45, 7.8, 0.75)]


def quote_r(x):  # ’ : head top-right, tail runs down to the left
    return [f"M {x + 1} 9 C {x + 0.7} 8 {x + 0.3} 7 {x} 6"], [dot(x + 0.55, 7.8, 0.75)]


def quote_s(x):  # straight '
    return [f"M {x + 0.3} 9.1 L {x} 6.3"], [dot(x + 0.25, 8.3, 0.7)]


def scaled(d, cx, cy, sx, sy=None):
    """Scale a pixel-space path about (cx, cy). Used to lay a slightly
    shrunken copy of a bowl inside itself, thickening it inward."""
    sy = sx if sy is None else sy
    out, idx = [], 0
    for tok in re.split(f"({NUM})", d):
        if re.fullmatch(NUM, tok or ""):
            v = float(tok)
            v = cx + (v - cx) * sx if idx % 2 == 0 else cy + (v - cy) * sy
            out.append(f"{v:.3f}")
            idx += 1
        else:
            out.append(tok)
    return "".join(out)


def tip(x, top=0.9, bottom=-0.25, half=0.48, blunt=0.22):
    """Filled wedge tapering to a softened point below a stroke join at
    (x, ~top): the nib only makes round ends, so pointed V bottoms are added
    as fills. `blunt` rounds off the very point (0 = sharp)."""
    return (f"M {x - half} {top} C {x - half * 0.85} {top - 0.55} {x - blunt} {bottom + 0.12} {x} {bottom} "
            f"C {x + blunt} {bottom + 0.12} {x + half * 0.85} {top - 0.55} {x + half} {top} Z")


def star(cx, cy, outer, inner, points=5):
    """Closed star outline (pixel space), first point straight up."""
    pts = []
    for i in range(points * 2):
        a = math.pi / 2 + i * math.pi / points
        r = outer if i % 2 == 0 else inner
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in pts) + " Z"


_HEART = ("M 3.5 0 C 2 1.5 0 3.4 0 5.6 C 0 7 0.8 7.8 1.8 7.8 C 2.6 7.8 3.2 7.2 3.5 6.4 "
          "C 3.8 7.2 4.4 7.8 5.2 7.8 C 6.2 7.8 7 7 7 5.6 C 7 3.4 5 1.5 3.5 0 Z")


GLYPHS = {}

# Uppercase -----------------------------------------------------------------

GLYPHS.update({
    # Left leg bows slightly outward; the right leg drops almost
    # vertically from an off-centre apex, then kicks out to the foot.
    # A small fill in the apex blunts the top of the counter.
    "A": G(["M 0 0 C 0.85 2.95 2.15 6.3 3.9 9",
            "M 3.9 9 C 4.1 7.4 4.2 5.8 4.6 4.4 C 5 3 5.6 1.4 6 0",
            "M 0.9 2.1 C 2.4 2.2 3.9 2.1 5.3 2"],
           ["M 2.6 5.9 C 2.85 6.8 3.6 6.8 3.9 5.9 L 4.1 7.9 L 3.1 7.9 Z"]),
    "B": G(["M 1 0 L 1 8.2",
            "M 0 7.9 L 2 8.75 C 2.6 9 3.2 9.05 3.8 9.05 C 5.2 9.05 6 8.4 6 7.3 C 6 6.1 5.2 5.2 4 5 "
            "C 5.4 4.9 6 3.8 6 2.6 C 6 1.8 5.8 1.2 5.2 0.8 C 4.6 0.3 4 0.05 3.3 0 L 1 0"]),
    # Slight inward bend at the top-left (as on O and Q), then a straight
    # left side curving tightly into the base.
    "C": G(["M 5 7.3 C 5 8.4 4.2 9 3 9 C 2 9 1.2 8.5 1 7.6 C 0.9 7 0.4 6.6 0.1 6 "
            "C 0 5.6 0 5.2 0 4.8 L 0 2 C 0 0.8 0.8 0 2 0 C 3.4 0 4.6 0.8 5 2.2 L 5 2.9"]),
    "D": G(["M 1 0 L 1 8.3",
            "M 0 7.5 C 0.3 8.6 1 9 2 9 L 3.5 9 C 4.6 9 5 8.2 5 7 L 5 3 C 5 1.2 4 0 2.8 0 L 1 0"]),
    "E": G(["M 0 7.4 C 0.3 8.6 1 9 2 9 L 5.2 9",
            "M 1 8.4 L 1 1 C 1 0.3 1.4 0 2 0 L 6 0",
            "M 1 5 L 4 5"]),
    "F": G(["M 0 7.4 C 0.3 8.6 1 9 2 9 L 5.2 9",
            "M 1 8.4 L 1 0",
            "M 1 5 L 4 5"]),
    # Straight left side with angled (chamfered) top-left and bottom-left
    # corners; a vertical stem drops from the bar to the baseline and the
    # bowl curves round and rises diagonally through the stem to the bar.
    "G": G(["M 5 8 C 4.6 8.7 3.9 9 3 9 L 2.3 9 C 2 9 1.8 8.9 1.6 8.7 L 0.3 7.2 C 0.1 7 0 6.7 0 6.3 "
            "L 0 1.6 C 0 1.3 0.1 1.1 0.3 0.9 L 0.9 0.3 C 1.1 0.1 1.4 0 1.7 0 C 2.7 0 3.4 0.8 3.9 1.8 "
            "C 4.25 2.7 4.65 3.5 5 4",
            "M 4 4 L 4 0",
            "M 3 4 L 6 4"]),
    "H": G(["M 0 9 L 0 0", "M 5 9 L 5 0", "M 0 4.3 C 1.5 4.1 3.5 4 5 4"]),
    "I": G(["M 0 9 L 2 9", "M 1 9 L 1 0", "M 0 0 L 2 0"]),
    # Angled hook: the stem cuts in diagonally near the bottom, a short
    # flattish base, then a tick back up on the left.
    "J": G(["M 4 9 L 4 2.3 C 4 1.8 3.8 1.4 3.4 1.0 L 2.6 0.3 C 2.3 0.05 2.0 0 1.6 0 C 1.0 0 0.4 0.4 0 1.0"],
           rough=dict(EDGE_SEED="1")),  # re-rolled texture: default was lumpy with a bleed at the hook
    "K": G(["M 0 9 L 0 0",
            "M 5.1 9 C 3.6 7.6 2 6 0.4 4.6",
            "M 1.4 4.4 C 2.6 3.2 3.8 1.6 5.1 0"],
           rough=dict(EDGE_SEED="3")),  # re-rolled texture: default bled over the junction
    "L": G(["M 0 9 L 0 1 C 0 0.3 0.4 0 1 0 L 4 0"]),
    # Straight outer sides that bend gently (not kinked) into verticals lower
    # down (the left slants in to the top, the right drops straight); a
    # straight V in the middle.
    "M": G(["M 0 0 L 0 2.4 C 0 3.4 0.35 4.3 0.75 5.3 L 2 9 L 4 3.2 L 7 9 L 7 5.4 C 7 4.4 8 3.6 8 2.4 L 8 0"]),
    "N": G(["M 0 0 L 0 9 C 1.5 7 3.4 4.2 5 2", "M 5 9 L 5 0"], rough=dict(EDGE_SEED="4", bold=dict(EDGE_SEED="2"))),  # re-rolled texture: default pinched the right stem
    # Straight right side; the left side has gentle inward bends at the
    # top-left and bottom-left (toned down from the source's).
    "O": G(["M 3.5 9 C 4.8 9 6 8.2 6 6.6 L 6 3.2 C 6 1.6 5.2 0.6 4.2 0.2 C 3.6 0 3 0 2.6 0 "
            "C 1.6 0 0.9 0.6 0.55 1.6 C 0.3 2.3 0.1 2.9 0.05 3.6 L 0 4.8 C 0 5.5 0.3 6.0 0.5 6.6 "
            "C 0.8 7.6 1.4 8.5 2.4 8.85 C 2.8 9 3.2 9 3.5 9 Z"],
           rough=dict(EDGE_SEED="2")),  # re-rolled texture: default dented the right side
    # The top starts as a straight upward slant from the left spur, then
    # runs flat into the bowl (same for R).
    "P": G(["M 1 0 L 1 8.2",
            "M 0 7 L 1.5 8.4 C 2.2 8.95 3 9.05 3.8 9.05 C 5.2 9.05 6 8.2 6 7 C 6 5.4 5 4.3 3.4 4.3 "
            "C 2.4 4.3 1.6 4.5 1 4.9"]),
    # Bowl sits on row 1 with a slight inward bend at the top-left; short
    # tail from inside the bowl's lower right out past the baseline.
    "Q": G(["M 3 9 C 4.6 9 6 8 6 6.4 L 6 3.6 C 6 2 5 1 3.4 1 C 1.8 1 0.8 1.6 0.4 2.6 "
            "C 0.1 3.2 0 3.8 0 4.4 L 0 5.6 C 0 6.2 0.6 6.6 0.9 7.2 C 1.2 8.2 2 9 3 9 Z",
            "M 3.8 3.1 C 4.6 2.3 5.4 1.2 6.2 0"]),
    "R": G(["M 1 0 L 1 7.5",
            "M 0 6.8 L 2.3 8.35 C 3.1 8.9 4 9.05 4.9 9.05 C 6.3 9.05 7 8.3 7 7.3 C 7 5.8 5.6 4.8 3.2 4.2 "
            "C 4.5 3.3 5.2 2 5.5 1 C 5.6 0.5 5.9 0 6.2 0"]),
    "S": G(["M 5 7.2 C 5 8.4 4.2 9 3.1 9 C 1.9 9 1 8.2 1 7 C 1 5.7 2.2 5.1 3.5 5 "
            "C 4.6 4.8 5 3.8 5 2.5 C 5 1 4.2 0 2.6 0 C 1.5 0 0.5 0.6 0 1.8"]),
    "T": G(["M 0 9 L 5 9", "M 2.5 9 C 2.2 8 2 7 2 6 L 2 0"]),
    "U": G(["M 0 9 L 0 2 C 0 0.7 0.9 0 2 0 C 3.4 0 4.6 1 5 2.6 L 5 9"]),
    # Left arm is one gentle outward bow; the right arm curves in gently with
    # no upturn at the tip; they close in a pointed V.
    "V": G(["M 0 9 C 0 6.6 1.6 3.4 3 0.6",
            "M 6 9 C 5.9 7.6 5.4 6 4.7 4.4 C 4.1 3 3.4 1.6 3 0.6"],
           [tip(3)]),
    # Two forks: outer strokes curve in gently (no upturn at the tips), the
    # inner strokes come down from a low rounded peak, and each pair closes
    # in a pointed V at the baseline.
    "W": G(["M 0 9 C 0.1 7.4 0.6 5.6 1 4 C 1.3 2.6 1.8 1.3 2 0.6",
            "M 8 9 C 7.9 7.4 7.4 5.6 7 4 C 6.7 2.6 6.2 1.3 6 0.6",
            "M 2 0.6 C 2.3 1.4 2.8 2.6 3 3.8 C 3.2 5 3.5 6.5 4 7.2 C 4.5 6.5 4.8 5 5 3.8 C 5.2 2.6 5.7 1.4 6 0.6"],
           [tip(2, bottom=-0.05, blunt=0.45), tip(6, bottom=-0.05, blunt=0.45)]),
    # Strokes cross high, through a short vertical neck; the upper arms are
    # short diagonals, the lower legs longer and steepening towards the feet.
    "X": G(["M 0 9 C 1 8 2.3 6.8 3 5.8 L 3 5.2 C 3.8 4.2 4.8 3.3 5 2.4 C 5.2 1.6 5.8 0.7 6 0",
            "M 6 9 C 5 8 3.7 6.8 3 5.8 L 3 5.2 C 2.2 4.2 1.2 3.3 1 2.4 C 0.8 1.6 0.2 0.7 0 0"]),
    "Y": G(["M 0 9 C 0.2 7 1 5.5 2 5", "M 5 9 C 4.6 7.4 3.5 5.8 2.2 5", "M 2 5.2 L 2 0"]),
    "Z": G(["M 0 9 L 5 9 C 3.5 7.2 1.8 5.4 0.8 3.8 C 0.2 2.8 0 1.8 0 0.6 L 0 0 L 5.2 0"]),
})

# Lowercase -----------------------------------------------------------------

# Lowercase d bowl (single-stroke weight).
_D_BOWL = ("M 4 5.5 C 3.6 5.95 2.9 6.05 2.2 6.0 C 0.9 5.9 0 4.9 0 3.6 C 0 2.8 0 2.2 0.1 1.6 "
           "C 0.25 0.7 0.6 0.1 1.3 0.1 C 2.2 0.1 2.8 0.9 3.3 1.7 C 3.6 2.2 3.85 2.7 4 3.0")
# Lowercase p bowl (narrowing at the top-right), thickened the same way.
_P_BOWL = ("M 0 5.4 L 1.2 6.5 C 1.7 6.95 2.3 7.1 2.9 7.05 C 3.6 7.0 4.2 6.6 4.6 5.9 "
           "C 4.9 5.4 5 5 5 4.4 L 5 3.6 C 5 2.9 4.5 2.2 3.9 1.7 C 3.3 1.2 2.7 1.0 2.0 1.0 C 1.3 1.0 0.7 1.1 0 1.3")

GLYPHS.update({
    # Top hook: a short level stem pointing left, then one smooth arc round
    # into a slightly curved stem; round bowl; short flick.
    "a": G(["M 0.8 7.05 L 1.6 7.05 C 2.9 7.05 3.95 6.2 3.95 4.9 C 3.95 3.6 3.85 2.5 3.8 1.6 "
            "C 3.8 1 4.3 0.6 5 0.4",
            "M 3.85 3.7 C 3.3 4.1 2.6 4.2 1.9 4.1 C 0.8 3.95 0 3.1 0 2 C 0 0.8 0.8 0 1.8 0 C 2.8 0 3.4 0.6 3.8 1.5"],
           rough=dict(EDGE_SEED="10")),  # re-rolled texture
    # Round bowl, curving all the way from the stem (no flat runs), with a
    # slight inward dent along the upper and lower right edges.
    "b": G(["M 0 9 L 0 0",
            "M 0 0.2 C 0.5 0 1.3 -0.05 1.9 0.05 C 2.4 0.15 2.75 0.45 3.0 0.9 C 3.3 1.45 4 1.9 4 2.7 "
            "L 4 3.3 C 4 4.0 3.3 4.4 3.0 5.0 C 2.75 5.5 2.4 5.85 1.9 5.95 C 1.3 6.05 0.5 6 0 5.8"]),
    "c": G(["M 3 6 C 3 6.7 2.6 7 2 7 C 0.8 7 0 5.6 0 3.8 C 0 1.6 0.6 0 1.6 0 C 2.6 0 3.6 1.6 5 3"]),
    "d": G(["M 4 9 L 4 2 C 4 1 4.4 0.3 5 0", _D_BOWL]),
    # Irregular e: angled top-left, small upper bowl over a bar slanting
    # down to the left, straight left side, terminal running diagonally up.
    "e": G([scaled("M 0.3 3.1 C 1.4 3.6 2.5 3.95 3.3 4.25 C 3.85 4.45 4.05 4.85 4.05 5.3 C 4.05 6.3 3.4 7 2.5 7 "
                   "C 2.0 7 1.6 6.8 1.2 6.4 L 0.4 5.4 C 0.1 5.0 0 4.5 0 3.9 L 0 1.8 C 0 0.7 0.7 0 1.6 0 "
                   "C 2.2 0 2.8 0.25 3.2 0.6 L 4 1.5", 0, 0, 0.94, 1)],
           # fills the lower counter's corner under the bar at the left side, and
           # rounds the upper counter's lower-left corner above it
           ["M 0.2 3.3 L 1.8 3.75 L 0.2 1.9 Z",
            "M 0.1 3.2 L 1.3 3.75 C 0.7 3.9 0.3 4.2 0.1 4.7 Z"]),
    "f": G(["M 4 9 C 3 9 2 8.4 2 7 L 2 0", "M 0 6 L 3 6"]),
    # Bowl (rows 2-7) pulled in at the top-left and bottom-right so it is
    # not a perfect oval; vertical stem on the right with a small ear
    # flagging out at the top; short descender hooking back up on the left.
    "g": G(["M 2.3 7 C 3.4 7 4 6.3 4 5.2 L 4 4.4 C 3.9 3.7 3.5 3.0 3.0 2.55 C 2.6 2.2 2.2 2.0 1.7 2.0 "
            "C 0.8 2 0 2.8 0 4 L 0 4.7 C 0 5.1 0.2 5.4 0.5 5.8 L 1.1 6.55 C 1.4 6.9 1.8 7 2.3 7 Z",
            "M 4 6.6 L 4 1.8 C 4 0.8 3.2 -0.6 2.3 -1.45 C 1.9 -1.85 1.4 -2.0 1.0 -1.85 C 0.5 -1.6 0.15 -1.0 0 -0.2",
            "M 4 6.1 C 4.3 6.13 4.6 6.15 4.85 6.12"],
           # fills the corner under the bowl where it sweeps into the stem
           ["M 2.5 2.2 C 2.8 1.5 3.3 0.9 4 0.4 L 4 2.6 Z"], rough=dict(EDGE_SEED="2")),  # re-rolled texture
    "h": G(["M 0 9 L 0 0", "M 0 5.6 C 0.6 6 1.4 6 2.4 6 C 3.4 6 4 5.3 4 4.4 L 4 0"],
           rough=dict(EDGE_SEED="6")),  # re-rolled texture: default was lumpy, pinched right leg
    "i": G(["M 0 6 L 0 0"], [ell(0.1, 8.5, 0.6, 0.85)], adv=3,  # same narrow dot as j
           rough=dict(EDGE_SEED="5")),  # re-rolled texture: default notched the stem
    # Narrow upright dot; the stem curves into a tail that starts steep and
    # bends progressively leftward (no flat hook).
    "j": G(["M 3 6 L 3 3.0 C 3 1.9 2.5 0.7 1.9 -0.3 C 1.4 -1.0 0.9 -1.45 0.3 -1.65"],
           [ell(3.25, 8.5, 0.6, 0.85)], rough=dict(EDGE_SEED="4")),  # re-rolled texture
    "k": G(["M 0 9 L 0 0",
            "M 4 7 C 2.6 6.4 1.8 5 1.5 3.8",
            "M 0.5 3.8 C 2 3.6 3.6 2 5 0"],
           rough=dict(EDGE_SEED="5")),  # re-rolled texture: default blobbed the junction
    "l": G(["M 0.45 8.1 C 0.2 8.25 0 8.55 0 9 L 0 0"], adv=3, rough=dict(EDGE_SEED="3")),  # re-rolled texture
    # m: each arch leaves its stem along a straight diagonal, with the wedge
    # between filled (slanted inner top-left); outer top-left fully rounded.
    "m": G(["M 0 0 L 0 6.0 C 0 6.7 0.45 7.05 1.0 7.05 L 2.0 7.05",
            "M 0 5.0 L 1.1 6.6 C 1.35 6.95 1.7 7.05 2.0 7.05 C 2.6 7.05 3 6.5 3 5.6 L 3 0",
            "M 3 5.0 L 4.1 6.6 C 4.35 6.95 4.7 7.05 5.0 7.05 C 5.6 7.05 6 6.5 6 5.6 L 6 0"],
           ["M 0 5.0 L 1.2 6.75 L 0 6.4 Z", "M 3 5.0 L 4.2 6.75 L 3 6.6 Z"]),
    # n: stem rises to the arch's height; the arch springs from it in one
    # round curve (deliberately rounder than the upscaled target).
    "n": G(["M 0 7.0 L 0 0",
            "M 0 5.4 C 0.4 6.5 1.4 7.05 2.4 7.05 C 3.4 7.05 4 6.3 4 5.3 L 4 0"]),
    "o": G(["M 2.6 7 C 4 7 5 6 5 4.4 L 5 3.2 C 5 1.2 3.8 0 2.2 0 C 0.8 0 0 1.2 0 3 L 0 4.4 C 0 6 1.2 7 2.6 7 Z"]),
    # Like P: the bowl starts with a straight upward slant off the stem, then
    # rounds all the way back to it. Stem tops out at row 6.
    "p": G([_P_BOWL, scaled(_P_BOWL, 4.4, 4.0, 0.9, 0.94), "M 0 6.2 L 0 -1.1"]),
    # Leaning bowl: the top sits right of centre with a straight diagonal
    # down the upper left; the bottom climbs diagonally back to the stem.
    # Short descender.
    "q": G(["M 5 6.6 L 5 -1.0",
            "M 5 6.6 C 4.8 6.95 4.4 7.05 3.8 7.05 C 3.2 7.05 2.7 6.8 2.2 6.3 L 0.6 4.6 C 0.2 4.2 0 3.7 0 3.2 "
            "L 0 2.4 C 0 1.6 0.6 1.0 1.4 1.0 C 2.1 1.0 2.7 1.4 3.3 2.0 L 4.2 2.9 C 4.5 3.2 4.75 3.4 5 3.5"]),
    "r": G(["M 0 7 L 0 0", "M 0 5.4 C 0.6 6.6 1.6 7 2.8 7 C 3.6 7 4 6.6 4 6"]),
    # Irregular s: narrow top bowl, fuller bottom bowl, a near-straight
    # diagonal spine with rounded insides; both terminals flick back against the curve (top tip turns out
    # to the right, bottom tip out to the left).
    "s": G(["M 4.95 6.2 C 4.7 6.2 4.45 6.35 4.25 6.6 C 3.95 6.9 3.4 7.02 2.5 7.02 C 1.0 7.02 0 6.5 0 5.6 "
            "C 0 4.9 0.7 4.5 1.6 4.15 C 2.3 3.85 3.0 3.6 3.6 3.3 C 4.5 2.85 5 2.2 5 1.5 "
            "C 5 0.6 4.2 -0.02 2.7 -0.02 C 1.8 -0.02 1.1 0.35 0.75 0.75 C 0.55 0.95 0.35 1.0 0.05 0.95"],
           rough=dict(EDGE_SEED="8")),  # re-rolled texture
    "t": G(["M 1 9 L 1 1.4 C 1 0.4 1.6 0 2.4 0 C 3.2 0 3.8 0.8 4 2", "M 0 6 L 4 6"],
           rough=dict(EDGE_SEED="1")),  # re-rolled texture: default notched the stem
    "u": G(["M 0 7 L 0 2 C 0 0.8 0.6 0 1.6 0 C 2.8 0 3.6 1 4 2.4",
            "M 4 7 L 4 1 C 4 0.4 4.4 0 5 0"]),
    "v": G(["M 0 7 C 0.4 4.5 1.6 2 3 0 C 4 2 5.2 4.5 6 7"], rough=dict(EDGE_SEED="3")),  # re-rolled texture
    "w": G(["M 0 7 C 0.4 4.5 1.2 2 2 0 C 2.5 2 3 4 3.4 6 C 4 4 4.6 2 5 0 C 5.8 2.2 6.6 4.6 7 7"],
           rough=dict(EDGE_SEED="4")),  # re-rolled texture
    "x": G(["M 0 6.6 C 2 4.6 3 2.4 5 0", "M 5 6.6 C 3 4.6 2 2.4 0 0"]),
    "y": G(["M 0 7 L 0 3 C 0 1.8 0.6 1 1.6 1 C 2.6 1 3.4 1.8 4 3",
            "M 4 7 L 4 1 C 4 -0.4 3.2 -1 2 -1.3"]),
    "z": G(["M 0 7 L 5 7 C 3.4 5.4 1.4 2.8 0 0 L 5 0"]),
})

# Digits --------------------------------------------------------------------

GLYPHS.update({
    "0": G(["M 2 8 C 3.4 8 4 6.8 4 5 L 4 3 C 4 1.2 3.4 0 2 0 C 0.6 0 0 1.2 0 3 L 0 5 C 0 6.8 0.6 8 2 8 Z"]),
    "1": G(["M 0 6.4 C 0.5 7 0.9 7.5 1 8 L 1 0"]),
    "2": G(["M 0 6.2 C 0 7.4 1 8 2.4 8 C 4 8 5 7.2 5 6 C 5 4.4 2.4 2.6 0 0 L 5 0"]),
    "3": G(["M 0 6.3 C 0.2 7.5 1.2 8 2.5 8 C 4 8 5 7.3 5 6 C 5 4.8 4.2 4 3 4",
            "M 3 4 C 4.4 4 5 3.2 5 2 C 5 0.8 4 0 2.5 0 C 1.2 0 0.3 0.6 0 1.8"]),
    # Straight diagonal (not bowed) down into the crossbar.
    "4": G(["M 4.1 8.1 L 0.3 2.9 C 0.1 2.6 0 2.3 0 2 L 5.2 2", "M 4 8 L 4 0"]),
    "5": G(["M 5 8 L 0 8 L 0 5 L 3 5 C 4.4 5 5 4 5 2.6 C 5 1 4 0 2.5 0 C 1.2 0 0.3 0.6 0 1.8"],
           rough=dict(EDGE_SEED="1")),  # re-rolled texture: default was lumpy on the bar and stem
    "6": G(["M 5 6.8 C 4.8 7.6 3.8 8 2.6 8 C 1 8 0 7 0 5 L 0 2.4 C 0 0.8 1 0 2.5 0 C 4 0 5 0.8 5 2.4 "
            "L 5 3 C 5 4.4 4.2 5 3 5 L 0 5"]),
    "7": G(["M 0 8 L 5 8 C 4 6 3 3.5 2.5 0"]),
    "8": G([ell(2.5, 6.2, 2.3, 1.8), ell(2.5, 2.1, 2.5, 2.1)]),
    "9": G(["M 5 4 C 4.6 3.4 3.8 3 2.5 3 C 1 3 0 4 0 5.6 C 0 7 1 8 2.5 8 C 4 8 5 7 5 5.4 L 5 2.4 "
            "C 5 0.8 4 0 2.5 0 C 1.3 0 0.4 0.5 0 1.4"],
           rough=dict(EDGE_SEED="1")),  # re-rolled texture: default was lumpy round the bowl
})

# Punctuation and symbols ---------------------------------------------------

_ql0, _ql0f = quote_l(0)
_ql2, _ql2f = quote_l(2)
_qr0, _qr0f = quote_r(0)
_qr2, _qr2f = quote_r(2)
_qs0, _qs0f = quote_s(0)
_qs2, _qs2f = quote_s(2)
_LBRACE = ("M 2.4 9.2 C 1.4 9.2 1.2 8.6 1.2 7.6 L 1.2 6 C 1.2 5 0.8 4.6 0 4.6 "
           "C 0.8 4.6 1.2 4.2 1.2 3.2 L 1.2 1.6 C 1.2 0.6 1.4 0 2.4 0")

GLYPHS.update({
    ".": G(f=[blob(1, 1, angle=28)]),
    ",": G(["M 2 2 L 2 1 C 2 0 1.2 -0.8 0 -1"], [dot(1.6, 1.4, 0.8)]),
    ":": G(f=[blob(1, 5, 1.4, 1.2, angle=38, flat=(1, 3)), blob(1, 1, 1.4, 1.2, angle=30, flat=(1, 3))]),
    ";": G(["M 1.8 0.6 C 1.8 -0.5 1.5 -1.4 1 -2"], [blob(1, 5, angle=34, flat=(1, 3)), blob(1, 1, angle=26)]),
    # A single filled wedge: widest at the top, tapering unevenly along the
    # slant (left edge swells low, right edge narrows in two stages) to a
    # blunt end, over a blob dot.
    "!": G(f=["M 1.85 8.55 C 2.15 9.05 3.2 9.05 3.45 8.55 C 3.25 7.8 2.95 7.1 2.45 6.4 "
              "C 2.0 5.7 1.75 4.6 1.4 3.9 C 1.25 3.55 0.7 3.55 0.6 3.95 "
              "C 0.45 4.7 0.65 5.5 0.95 6.15 C 1.3 6.95 1.55 7.7 1.85 8.55 Z",
              blob(1, 1, angle=32)]),
    # Hook tops out at row 9 with a heavy right shoulder and diagonal (extra
    # strokes thicken them),
    # then a diagonal tail ending as a short vertical above the dot.
    "?": G(["M 0 7.2 C 0 8.4 0.9 9 2.3 9 C 3.8 9 4.6 8.4 4.6 7.4 C 4.6 6.6 4.0 6.1 3.3 5.6 "
            "C 2.5 5.0 1.6 4.5 1.2 3.9 C 1.05 3.6 1 3.3 1 3.0",
            "M 4.4 8.4 C 5.0 7.8 5.0 6.9 4.3 6.3",
            "M 2.4 8.75 C 3.3 8.7 3.9 8.2 3.95 7.4 C 4.0 6.9 3.7 6.4 3.2 5.9 C 2.7 5.4 2.1 5.0 1.7 4.6"],
           [blob(0.5, 0.5, 1.05, 0.95, angle=25)]),
    "'": G(_qs0, _qs0f),
    '"': G(_qs0 + _qs2, _qs0f + _qs2f),
    "‘": G(_ql0, _ql0f),
    "’": G(_qr0, _qr0f),
    "“": G(_ql0 + _ql2, _ql0f + _ql2f),
    "”": G(_qr0 + _qr2, _qr0f + _qr2f),
    "-": G(["M 0 4 L 3 4"]),
    "–": G(["M 0 4 L 6 4"]),
    "—": G(["M 0 4 L 12 4"]),
    "_": G(["M 0 -1.5 L 6 -1.5"]),
    "/": G(["M 3 8 C 2 5.5 1 3 0 0"]),
    "\\": G(["M 0 8 C 1 5.5 2 3 3 0"]),
    "|": G(["M 0 9.6 L 0 -2"], adv=3),
    "(": G(["M 2 9.2 C 0.7 7.8 0 6 0 4.5 C 0 3 0.7 1.4 2 0"], adv=5),
    ")": G(["M 1 9.2 C 2.3 7.8 3 6 3 4.5 C 3 3 2.3 1.4 1 0"], adv=5),
    "[": G(["M 2 9.2 L 0 9.2 L 0 0 L 2 0"]),
    "]": G(["M 0 9.2 L 2 9.2 L 2 0 L 0 0"]),
    "{": G([_LBRACE]),
    "}": G([mirror_x(_LBRACE, 2.4)]),
    "*": G(["M 3 8 L 3 0",
            "M 0.5 7 C 1.5 6 2 5 3 4 C 4 3 4.5 2 5.5 1.3",
            "M 5.5 7 C 4.5 6 4 5 3 4 C 2 3 1.5 2 0.5 1.3"]),
    "#": G(["M 3.2 8 L 1 0", "M 6.2 8 L 4 0", "M 1 6 L 7 6", "M 0 3 L 6 3"]),
    "%": G([ell(1, 5.5, 1, 1.5), ell(5, 1.5, 1, 1.5), "M 6.2 7.5 C 4.5 5.5 2 2.5 0 0"]),
    "&": G(["M 5.6 3.2 C 4.6 2.2 3.8 1.2 2.6 0.4 C 1 0 0 0.8 0 2.2 C 0 3.4 1.2 4.2 2.4 5",
            "M 2.4 5 C 1.4 5.8 1.1 6.6 1.3 7.4 C 1.5 8 2.2 8.2 3 8.2 C 4 8.2 4.8 7.6 4.6 6.8 C 4.4 6 3.4 5.4 2.6 4.8",
            "M 2.6 4.8 C 3.6 3.6 4.8 2 6 0"]),
    "+": G(["M 3 7 L 3 1", "M 0 4 L 6 4"], rough=dict(EDGE_SEED="4")),  # re-rolled: default notched the crossing
    "=": G(["M 0 5.2 L 5 5.2", "M 0 2.8 L 5 2.8"]),
    "<": G(["M 5 7 L 0 4 L 5 1"]),
    ">": G(["M 0 7 L 5 4 L 0 1"]),
    "^": G(["M 0 6.4 L 2 8.8 L 4 6.4"]),
    "`": G(["M 0 9 L 1 7.6"]),
    "~": G(["M 0 3 C 0.2 4.4 1 5 2 5 C 3 5 3.6 3.6 4.6 3.4 C 5.4 3.4 5.8 4.2 6 5"]),
    "@": G([ell(4, 3.9, 1.6, 2.0),
            "M 5.6 5.8 L 5.6 2.4 C 5.6 1.6 6 1.2 6.6 1.2 C 7.4 1.2 8 2.6 8 4.4 C 8 7 6.2 9 4 9 "
            "C 1.8 9 0 7 0 4.4 C 0 1.6 1.8 -0.2 4.2 -0.2 C 5.2 -0.2 6 0.1 6.8 0.6"]),
    "$": G(["M 4.6 6.6 C 4.4 7.4 3.6 7.8 2.6 7.8 C 1.4 7.8 0.4 7.2 0.4 6 C 0.4 4.8 1.6 4.4 2.6 4 "
            "C 3.8 3.6 4.8 3.2 4.8 1.9 C 4.8 0.7 3.8 0 2.4 0 C 1.2 0 0.4 0.4 0 1.2",
            "M 2.5 9.2 L 2.5 -1.2"]),
    "•": G(f=[blob(1, 3, angle=35, flat=(1, 3))]),
    "×": G(["M 0 7 L 6 1", "M 6 7 L 0 1"]),
    "‥": G(f=[blob(1, 1, 1.25, 1.1, angle=30), blob(4.5, 1, 1.25, 1.1, angle=40, flat=(1, 3))]),
    "…": G(f=[blob(1, 1, 1.25, 1.1, angle=28), blob(4.5, 1, 1.25, 1.1, angle=38, flat=(1, 3)), blob(8, 1, 1.25, 1.1, angle=32)]),
    "←": G(["M 6 3 L 0 3", "M 2 5 L 0 3 L 2 1"]),
    "→": G(["M 0 3 L 6 3", "M 4 5 L 6 3 L 4 1"]),
    "↑": G(["M 2 0 L 2 7", "M 0 5 L 2 7 L 4 5"]),
    "↓": G(["M 2 7 L 2 0", "M 0 2 L 2 0 L 4 2"]),
    "「": G(["M 2 9 L 0 9 L 0 5"]),
    "」": G(["M 2 4 L 2 0 L 0 0"]),
    # U+2661 white heart (outline, as in the game's dialogue) and U+2665
    # black heart (filled).
    "\u2661": G([_HEART]),
    "\u2665": G([_HEART], [_HEART]),
    "♪": G(["M 3 1 L 3 8.6 C 3.6 7.6 5 7.2 5 5.8 C 5 5.2 4.6 4.8 4.4 4.6"], [ell(1.6, 1, 1.5, 1.1)]),
    # U+2606 white star (outline), U+00A9 copyright sign.
    "\u2606": G([star(4.2, 4.3, 4.4, 1.85)]),
    "\u00a9": G([ell(4, 4.5, 4.05, 4.55),
                 "M 5.6 5.7 C 5.3 6.3 4.7 6.6 4 6.6 C 2.9 6.6 2.2 5.7 2.2 4.5 C 2.2 3.3 2.9 2.4 4 2.4 "
                 "C 4.7 2.4 5.3 2.7 5.6 3.3"]),
})

SPACE = 5 * PX

# Extra code points that reuse another glyph's outline (the game's font table
# includes full-width slash and digits).
ALIASES = {0xFF0F: "/", **{0xFF10 + i: str(i) for i in range(10)}}
