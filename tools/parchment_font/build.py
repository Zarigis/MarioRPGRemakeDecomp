"""Build Parchment Hand: stroke centreline glyphs with an elliptical nib and
write a TrueType font (Regular and Bold) plus a PNG specimen into build/font.

    .venv/Scripts/python tools/parchment_font/build.py
"""
import math
import random
import sys
from pathlib import Path

import pathops
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.transform import Transform
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path

sys.path.insert(0, str(Path(__file__).parent))
from glyphs import ALIASES, GLYPHS, SPACE  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "font"   # ignored by git, as every build output
FAMILY = "Parchment Hand"
PS_NAME = "ParchmentHand-Regular"

UPM = 1000
NIB_W, NIB_H, NIB_ANGLE = 76, 64, 35  # elliptical pen: major, minor, degrees
WOBBLE = 8          # amplitude of smooth per-glyph deformation, font units
WOBBLE_WAVE = 260   # wavelength of that deformation
TILT = 1.0          # max per-glyph rotation, degrees
BOUNCE = 5          # max per-glyph baseline shift
TRACKING = 0        # extra advance per glyph, font units (keep a multiple of PX for pixel fidelity)
FACET = 0           # >0: flatten centreline curves into straight facets this long (font units)
FACET_JITTER = 0.35 # relative randomness of facet lengths
EDGE_ROUGH = 9      # >0: amplitude of fine noise along outline edges (font units); 0 = smooth
EDGE_WAVE = 45      # typical wavelength of that edge noise (font units)
EDGE_STYLE = "noise"  # "sine": even scallops; "noise": irregular bumps, patchy, with outward bleeds
EDGE_BLEED = 1.4    # strength of the occasional outward ink bleeds ("noise" style)
EDGE_SEED = ""      # extra seed text; override per glyph to re-roll an unlucky texture
AMP_LOG = None      # debug: a list to collect per-point outward displacement of the edge texture
EMBOLDEN = 0        # >0: grow every outline outward by this much (font units) - the Bold style
STYLE = "Regular"   # style name written into the font ("Regular" or "Bold")
# Settings applied on top of the defaults when building the Bold.
BOLD = dict(EMBOLDEN=20, STYLE="Bold", EDGE_ROUGH=6, EDGE_BLEED=1.0)
# Per-glyph overrides: G(..., rough=dict(EDGE_ROUGH=5)) in glyphs.py changes
# any of the EDGE_* settings for that glyph only.


# Geometry helpers ------------------------------------------------------------

class WarpPen:
    """Pen filter applying a smooth, glyph-seeded wobble to every point."""

    def __init__(self, out, seed):
        rng = random.Random(seed)
        self.out = out
        self.p = [rng.uniform(0, 2 * math.pi) for _ in range(4)]
        self.f = [WOBBLE_WAVE * rng.uniform(0.8, 1.25) for _ in range(4)]
        a = math.radians(rng.uniform(-TILT, TILT))
        self.ca, self.sa = math.cos(a), math.sin(a)
        self.dy = rng.uniform(-BOUNCE, BOUNCE)

    def w(self, pt):
        x, y = pt
        dx = WOBBLE * math.sin(x / self.f[0] + self.p[0]) * math.cos(y / self.f[1] + self.p[1])
        dy = WOBBLE * math.sin(x / self.f[2] + self.p[2]) * math.cos(y / self.f[3] + self.p[3])
        x, y = x + dx, y + dy
        # rotate about a point near the glyph's middle
        cx, cy = 200, 300
        x, y = x - cx, y - cy
        x, y = x * self.ca - y * self.sa, x * self.sa + y * self.ca
        return (x + cx, y + cy + self.dy)

    def moveTo(self, pt): self.out.moveTo(self.w(pt))
    def lineTo(self, pt): self.out.lineTo(self.w(pt))
    def curveTo(self, *pts): self.out.curveTo(*[self.w(p) for p in pts])
    def qCurveTo(self, *pts): self.out.qCurveTo(*[self.w(p) if p else p for p in pts])
    def closePath(self): self.out.closePath()
    def endPath(self): self.out.endPath()


class FacetPen:
    """Pen filter turning curves into chains of slightly uneven straight
    segments (about FACET units long), for a faceted, less smooth line."""

    def __init__(self, out, seed):
        self.out, self.rng, self.cur = out, random.Random(f"facet-{seed}"), None

    def moveTo(self, pt):
        self.cur = pt
        self.out.moveTo(pt)

    def lineTo(self, pt):
        self.cur = pt
        self.out.lineTo(pt)

    def curveTo(self, *pts):
        if len(pts) != 3:
            raise ValueError("FacetPen expects cubic segments")
        p0, c1, c2, p3 = self.cur, *pts
        bez = lambda t: tuple((1 - t) ** 3 * p0[i] + 3 * (1 - t) ** 2 * t * c1[i] + 3 * (1 - t) * t * t * c2[i] + t ** 3 * p3[i]
                              for i in range(2))
        length = sum(math.dist(bez(i / 20), bez((i + 1) / 20)) for i in range(20))
        t = 0.0
        while True:
            step = FACET * (1 + self.rng.uniform(-FACET_JITTER, FACET_JITTER)) / max(length, 1e-6)
            t += step
            if t >= 1 - step * 0.3:
                break
            self.out.lineTo(bez(t))
        self.out.lineTo(p3)
        self.cur = p3

    def qCurveTo(self, *pts):
        raise ValueError("FacetPen expects cubic segments")

    def closePath(self): self.out.closePath()
    def endPath(self): self.out.endPath()


def _knot_noise(rng, length, wave, lo, hi):
    """Smooth 1-D noise along a closed curve of the given length: random
    values at randomly spaced knots (spacing wave*lo..wave*hi), eased between,
    wrapping round. Returns f(t) in roughly [-1.5, 1.5]."""
    knots, t = [], 0.0
    while t < length:
        knots.append((t, rng.gauss(0, 0.8)))
        t += wave * rng.uniform(lo, hi)
    if len(knots) < 2:
        knots.append((length / 2, rng.gauss(0, 0.8)))
    ks = knots + [(length + knots[0][0], knots[0][1])]

    def f(x):
        x %= length
        for (t0, v0), (t1, v1) in zip(ks, ks[1:]):
            if t0 <= x <= t1:
                u = (x - t0) / (t1 - t0) if t1 > t0 else 0
                u = u * u * (3 - 2 * u)
                return v0 + (v1 - v0) * u
        return ks[0][1]
    return f


def roughen(path, seed):
    """Displace the outline along its normals by smooth fine noise (EDGE_ROUGH
    units, EDGE_WAVE wavelength), like ink bleeding into paper."""
    from fontTools.pens.basePen import decomposeQuadraticSegment
    from fontTools.pens.recordingPen import RecordingPen as _Rec
    rng = random.Random(f"rough-{seed}{EDGE_SEED}")
    rec = _Rec()
    path.draw(rec)
    contours, cur = [], []
    last = None
    for op, args in rec.value:
        if op == "moveTo":
            cur = [args[0]]
            last = args[0]
        elif op == "lineTo":
            cur.append(args[0])
            last = args[0]
        elif op == "qCurveTo":
            segs = decomposeQuadraticSegment(args) if len(args) > 2 else [args]
            for c, e in segs:
                for i in range(1, 7):
                    t = i / 6
                    cur.append(tuple((1 - t) ** 2 * last[k] + 2 * (1 - t) * t * c[k] + t * t * e[k] for k in range(2)))
                last = e
        elif op == "curveTo":
            c1, c2, e = args
            for i in range(1, 9):
                t = i / 8
                cur.append(tuple((1 - t) ** 3 * last[k] + 3 * (1 - t) ** 2 * t * c1[k] + 3 * (1 - t) * t * t * c2[k]
                                 + t ** 3 * e[k] for k in range(2)))
            last = e
        elif op in ("closePath", "endPath"):
            if len(cur) > 2:
                contours.append(cur)
            cur = []
    out = pathops.Path()
    pen = out.getPen()
    step = max(4.0, EDGE_WAVE / 8)
    for pts in contours:
        # resample at roughly even spacing along the outline
        res = []
        for a, b in zip(pts, pts[1:] + pts[:1]):
            n = max(1, int(math.dist(a, b) / step))
            res += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
        if len(res) < 3:
            continue
        ph = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
        dist, total = [0.0], 0.0
        for a, b in zip(res, res[1:]):
            total += math.dist(a, b)
            dist.append(total)
        perimeter = total + math.dist(res[-1], res[0])
        if EDGE_STYLE == "noise":
            fine = _knot_noise(rng, perimeter, EDGE_WAVE, 0.45, 1.7)
            env = _knot_noise(rng, perimeter, EDGE_WAVE * 4, 0.6, 1.6)
            # a few outward bleeds: (position, width, height)
            nb = rng.randint(0, max(1, int(perimeter / (EDGE_WAVE * 5))))
            bleeds = [(rng.uniform(0, perimeter), EDGE_WAVE * rng.uniform(0.35, 0.8), rng.uniform(0.8, 1.8))
                      for _ in range(nb)]
        moved = []
        for i, (x, y) in enumerate(res):
            a, b = res[i - 1], res[(i + 1) % len(res)]
            tx, ty = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(tx, ty) or 1
            nx, ny = -ty / ln, tx / ln
            t = dist[i]
            if EDGE_STYLE == "noise":
                # outward = away from the ink; probe which side of the edge is ink
                sign = -1 if path.contains((x + nx * 3, y + ny * 3)) else 1
                e = max(0.0, 0.55 + 0.45 * env(t))  # patchy: some stretches nearly clean
                amp = EDGE_ROUGH * e * fine(t)
                for pos, wid, hgt in bleeds:
                    dd = min(abs(t - pos), perimeter - abs(t - pos))
                    amp += sign * EDGE_ROUGH * EDGE_BLEED * hgt * math.exp(-(dd / wid) ** 2)
            else:
                amp = EDGE_ROUGH * (math.sin(t / EDGE_WAVE * 2 * math.pi + ph[0]) * 0.55
                                    + math.sin(t / (EDGE_WAVE * 0.53) * 2 * math.pi + ph[1]) * 0.3
                                    + math.sin(t / (EDGE_WAVE * 0.29) * 2 * math.pi + ph[2]) * 0.15)
            if AMP_LOG is not None:
                AMP_LOG.append(amp * (sign if EDGE_STYLE == "noise" else 1))
            moved.append((x + nx * amp, y + ny * amp))
        pen.moveTo(moved[0])
        for q in moved[1:]:
            pen.lineTo(q)
        pen.closePath()
    out.simplify()
    return out


def to_nib_space():
    a = math.radians(NIB_ANGLE)
    # rotate so nib major axis lies on x, then squash x so the nib is round
    return Transform().scale(NIB_H / NIB_W, 1).rotate(-a)


def stroke(d, seed):
    """Stroke one centreline with the elliptical nib, return a pathops Path."""
    fwd = to_nib_space()
    src = pathops.Path()
    target = WarpPen(TransformPen(src.getPen(), fwd), seed)
    parse_path(d, FacetPen(target, seed + d) if FACET > 0 else target)
    src.stroke(NIB_H, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    src.convertConicsToQuads()
    out = pathops.Path()
    src.draw(TransformPen(out.getPen(), fwd.inverse()))
    out.simplify()
    return out


def fill(d, seed):
    p = pathops.Path()
    parse_path(d, WarpPen(p.getPen(), seed))
    p.simplify()
    return p


def embolden(path, amount):
    """Grow an outline outward by `amount` units on every side (union with a
    stroke of its own contour), shifted right by `amount` so the left
    sidebearing is unchanged; the caller widens the advance by 2*amount."""
    edge = pathops.Path()
    path.draw(edge.getPen())
    edge.stroke(2 * amount, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    edge.convertConicsToQuads()
    comb = pathops.Path()
    path.draw(TransformPen(comb.getPen(), Transform().translate(amount, 0)))
    edge.draw(TransformPen(comb.getPen(), Transform().translate(amount, 0)))
    try:
        comb.simplify()
        return comb
    except pathops.PathOpsError:
        b = pathops.OpBuilder()
        for q in (path, edge):
            t = pathops.Path()
            q.draw(TransformPen(t.getPen(), Transform().translate(amount, 0)))
            b.add(t, pathops.PathOp.UNION)
        return b.resolve()


def build_outline(name, g):
    path = _build_outline(name, g)
    if EMBOLDEN > 0:
        path = embolden(path, EMBOLDEN)
    over = dict(g.get("rough") or {})
    style_over = over.pop("bold", None)  # per-glyph settings for the Bold only
    if STYLE == "Bold" and style_over:
        over.update(style_over)
    saved = {k: globals()[k] for k in over}
    globals().update(over)
    try:
        return roughen(path, name) if EDGE_ROUGH > 0 else path
    finally:
        globals().update(saved)


def _build_outline(name, g):
    seed = f"ph-{name}"
    pieces = [stroke(d, seed) for d in g["s"]] + [fill(d, seed) for d in g["f"]]
    # Each piece is already simplified (outer/hole windings consistent), so
    # concatenating them and simplifying with the winding rule is a union.
    # pathops can fail on near-coincident geometry (e.g. a fill meeting a
    # stroke end exactly), so fall back to OpBuilder, then to nudged pieces.
    # (OpBuilder alone occasionally drops counters, e.g. on "0".)
    for attempt in range(4):
        comb = pathops.Path()
        for i, p in enumerate(pieces):
            if attempt >= 2:  # tiny per-piece offset breaks exact coincidences
                q = pathops.Path()
                p.draw(TransformPen(q.getPen(), Transform().translate(0.01 * (i + 1) * (attempt - 1), 0)))
                p = q
            comb.addPath(p)
        try:
            if attempt % 2 == 0:
                comb.simplify()
                return comb
            builder = pathops.OpBuilder()
            for p in pieces:
                builder.add(p, pathops.PathOp.UNION)
            return builder.resolve()
        except pathops.PathOpsError:
            continue
    raise RuntimeError(f"could not build outline for {name}")


# Font assembly ---------------------------------------------------------------

def glyph_name(ch):
    from fontTools.agl import UV2AGL
    return UV2AGL.get(ord(ch), f"uni{ord(ch):04X}")


def make_glyph(path):
    rec = RecordingPen()
    path.draw(rec)
    bp = BoundsPen(None)
    rec.replay(bp)
    ap = AreaPen()
    rec.replay(ap)
    pen = TTGlyphPen(None)
    target = Cu2QuPen(pen, max_err=0.8)
    # TrueType wants clockwise outer contours (negative area in AreaPen terms)
    rec.replay(ReverseContourPen(target) if ap.value > 0 else target)
    return pen.glyph()


def notdef():
    pen = TTGlyphPen(None)
    for (x0, y0, x1, y1), cw in (((50, 0, 450, 700), True), ((110, 60, 390, 640), False)):
        pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if not cw:
            pts.reverse()
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()
    return pen.glyph()




def main(out_path=None, do_specimen=True):
    OUT.mkdir(parents=True, exist_ok=True)
    order, cmap, glyf, hmtx = [".notdef", "space"], {32: "space", 0xA0: "space"}, {}, {}
    glyf[".notdef"] = notdef()
    hmtx[".notdef"] = (500, 50)
    glyf["space"] = TTGlyphPen(None).glyph()
    hmtx["space"] = (SPACE + round(EMBOLDEN), 0)

    for ch, g in GLYPHS.items():
        name = glyph_name(ch)
        glyph = make_glyph(build_outline(name, g))
        adv, l = g["adv"] + TRACKING + 2 * round(EMBOLDEN), 0
        order.append(name)
        cmap[ord(ch)] = name
        glyf[name] = glyph
        hmtx[name] = (adv, l)
    for cp, src in ALIASES.items():  # extra code points sharing an outline
        cmap[cp] = glyph_name(src)

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    # recompute lsb from the real glyph bounds
    gt = fb.font["glyf"]
    metrics = {}
    for n in order:
        gl = gt[n]
        gl.recalcBounds(gt)
        metrics[n] = (hmtx[n][0], getattr(gl, "xMin", 0))
    fb.setupHorizontalMetrics(metrics)
    asc, desc = 900, -300
    fb.setupHorizontalHeader(ascent=asc, descent=desc, lineGap=0)
    bold = STYLE == "Bold"
    ps_name = PS_NAME.replace("Regular", STYLE)
    fb.setupNameTable({
        "familyName": FAMILY,
        "styleName": STYLE,
        "uniqueFontIdentifier": f"{ps_name};1.000",
        "fullName": f"{FAMILY} {STYLE}",
        "psName": ps_name,
        "version": "Version 1.000",
    })
    fb.setupOS2(sTypoAscender=asc, sTypoDescender=desc, sTypoLineGap=0,
                usWinAscent=asc, usWinDescent=-desc, sxHeight=480, sCapHeight=700,
                fsSelection=(0x20 if bold else 0x40) | 0x80, usWeightClass=700 if bold else 400,
                achVendID="NONE", version=4)
    if bold:
        fb.font["head"].macStyle |= 1
    fb.setupPost()
    path = Path(out_path) if out_path else OUT / "ParchmentHand.ttf"
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(path)
    print("wrote", path, len(order), "glyphs")
    if do_specimen:
        specimen(path)


def specimen(font_path):
    from PIL import Image, ImageDraw, ImageFont
    lines = [
        (34, "Parchment Hand"),
        (60, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        (60, "abcdefghijklmnopqrstuvwxyz"),
        (60, "0123456789 .,:;!?'\"‘’“”-–—…"),
        (60, "()[]{}<>/\\|_*#%&+=@$^`~ •×←↑→↓♥♪"),
        (60, "The quick brown fox jumps over the lazy dog!"),
        (60, "Pack my box with five dozen liquor jugs."),
        (60, "“Wait!” she said. “It’s 3:45 — we’re LATE!”"),
        (60, "TOWER, AVAY, Type, Lymph, Fjord, quiz #7 (50%)"),
    ]
    W, pad = 1900, 40
    H = pad * 2 + sum(int(s * 1.45) for s, _ in lines)
    im = Image.new("RGB", (W, H), (236, 196, 120))
    dr = ImageDraw.Draw(im)
    y = pad
    for size, text in lines:
        f = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.RAQM
                               if ImageFont.core.HAVE_RAQM else ImageFont.Layout.BASIC)
        dr.text((pad, y), text, font=f, fill=(52, 44, 20))
        y += int(size * 1.45)
    out = OUT / "specimen.png"
    im.save(out)
    print("wrote", out)


def use_style(bold):
    """Switch the module settings to the Bold (or back to the Regular)."""
    global _REGULAR
    if "_REGULAR" not in globals():
        _REGULAR = {k: globals()[k] for k in BOLD}
    globals().update(BOLD if bold else _REGULAR)


def build_all():
    use_style(False)
    main()
    use_style(True)
    main(out_path=OUT / "ParchmentHand-Bold.ttf", do_specimen=False)
    use_style(False)


if __name__ == "__main__":
    build_all()
