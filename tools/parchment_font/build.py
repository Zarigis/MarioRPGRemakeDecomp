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
EDGE_STYLE = "width"  # "sine": even scallops; "noise": irregular bumps, patchy, with outward bleeds;
                      # "width": smooth stroke-width variation only (EDGE_ROUGH = max change per side)
WIDTH_WAVE = 170    # "width" style: wavelength of the 2-D width field (font units)
WIDTH_STEP = 40     # "width" style: longest outline piece moved as one (font units)
EDGE_BLEED = 1.4    # strength of the occasional outward ink bleeds ("noise" style)
EDGE_SEED = ""      # extra seed text; override per glyph to re-roll an unlucky texture
EDGE_LIMIT_OUT = 2.0  # soft ceiling on outward displacement, in EDGE_ROUGH units (0 = no limit)
EDGE_LIMIT_IN = 1.5   # same for inward displacement
EDGE_BLEED_GAP = 2.5  # bleeds: min gap between bleed centres, in EDGE_WAVE units (0 = old placement)
EDGE_BLEED_MAX = 1.5  # bleeds: max height factor (was 1.8)
AMP_LOG = None      # debug: a list to collect per-point outward displacement of the edge texture
EMBOLDEN = 0        # >0: grow every outline outward by this much (font units) - the Bold style
THICKEN = 4         # grow every outline in place by this much per side (font units); unlike
                    # EMBOLDEN it leaves advances and sidebearings alone
STYLE = "Regular"   # style name written into the font ("Regular" or "Bold")
# Settings applied on top of the defaults when building the Bold.
# Fixed-width digits: the game's Regular font has tabular 0-9 (HP counters, coin
# count, play time), so these get one shared advance, are centred in it, and skip
# the edge-noise pass so counters read cleanly. "" turns it off (the Bold's
# original digits are proportional). Advance ~0.8 of the 700-unit cap height.
TABULAR_DIGITS = "0123456789"
TABULAR_ADV = 560
BOLD = dict(EMBOLDEN=20, STYLE="Bold", TABULAR_DIGITS="")
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


def _value_noise_2d(seed, wave):
    """Smooth 2-D noise in about [-1, 1]: random lattice values every `wave`
    units, eased between, plus a weaker octave at half the wavelength."""
    cache = {}

    def lattice(o, i, j):
        k = (o, i, j)
        if k not in cache:
            cache[k] = random.Random(f"{seed}-{o}-{i}-{j}").uniform(-1, 1)
        return cache[k]

    def octave(o, w, x, y):
        fx, fy = x / w, y / w
        i, j = math.floor(fx), math.floor(fy)
        u, v = fx - i, fy - j
        u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
        a = lattice(o, i, j) + (lattice(o, i + 1, j) - lattice(o, i, j)) * u
        b = lattice(o, i, j + 1) + (lattice(o, i + 1, j + 1) - lattice(o, i, j + 1)) * u
        return a + (b - a) * v

    return lambda x, y: 0.75 * octave(0, wave, x, y) + 0.25 * octave(1, wave / 2, x, y)


def vary_width(path, seed):
    """EDGE_STYLE "width": swell and thin the strokes by up to EDGE_ROUGH units
    per side, following a smooth 2-D field (WIDTH_WAVE wavelength). Both edges of
    a stroke sit close together in that field, so they move out or in together.

    Works on the outline's own segments rather than a dense polyline: each one is
    split into pieces of at most WIDTH_STEP units, the piece ends move along the
    outline normal and each quadratic control point moves by the average of its
    ends. That keeps the outline smooth and sparse - a dense outline turns into a
    staircase wherever a renderer rounds points to whole pixels (hinting)."""
    from fontTools.pens.basePen import decomposeQuadraticSegment
    from fontTools.pens.recordingPen import RecordingPen as _Rec
    field = _value_noise_2d(f"width-{seed}{EDGE_SEED}", WIDTH_WAVE)
    rec = _Rec()
    path.draw(rec)
    # contours as lists of segments: ("L", p0, p1) or ("Q", p0, c, p1)
    contours, segs, start, last = [], [], None, None
    for op, args in rec.value:
        if op == "moveTo":
            segs, start, last = [], args[0], args[0]
        elif op == "lineTo":
            segs.append(("L", last, args[0]))
            last = args[0]
        elif op == "qCurveTo":
            for c, e in (decomposeQuadraticSegment(args) if len(args) > 2 else [args]):
                segs.append(("Q", last, c, e))
                last = e
        elif op == "curveTo":  # rare (fills): approximate each cubic by two quadratics
            c1, c2, e = args
            m = tuple((last[k] + 3 * c1[k] + 3 * c2[k] + e[k]) / 8 for k in (0, 1))
            qa = tuple((last[k] + 3 * c1[k]) / 4 for k in (0, 1))
            qb = tuple((3 * c2[k] + e[k]) / 4 for k in (0, 1))
            segs += [("Q", last, qa, m), ("Q", m, qb, e)]
            last = e
        elif op in ("closePath", "endPath"):
            if last is not None and start is not None and math.dist(last, start) > 1e-6:
                segs.append(("L", last, start))
            if segs:
                contours.append(segs)
            segs, start, last = [], None, None

    def lerp(a, b, t):
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def pieces(seg):
        """Split a segment into pieces no longer than about WIDTH_STEP."""
        if seg[0] == "L":
            _, p0, p1 = seg
            n = max(1, math.ceil(math.dist(p0, p1) / WIDTH_STEP))
            return [("L", lerp(p0, p1, i / n), lerp(p0, p1, (i + 1) / n)) for i in range(n)]
        _, p0, c, p1 = seg
        n = max(1, math.ceil((math.dist(p0, c) + math.dist(c, p1)) / WIDTH_STEP))

        def q(t):
            return lerp(lerp(p0, c, t), lerp(c, p1, t), t)
        out = []
        for i in range(n):  # sub-curve on [t0, t1]; its control point by de Casteljau
            t0, t1 = i / n, (i + 1) / n
            out.append(("Q", q(t0), lerp(lerp(p0, c, t0), lerp(c, p1, t0), t1), q(t1)))
        return out

    def tangent(seg, at_end):
        a, b = (seg[-2], seg[-1]) if at_end else (seg[1], seg[2])
        tx, ty = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(tx, ty)
        return (tx / ln, ty / ln) if ln else (0.0, 0.0)

    def shift(q, v):
        return (q[0] + v[0], q[1] + v[1])

    out = pathops.Path()
    pen = out.getPen()
    for segs in contours:
        ps = [p for sg in segs for p in pieces(sg)]
        n = len(ps)
        # one normal per piece start, averaged across the join with the previous piece
        normals = []
        for i in range(n):
            ta, tb = tangent(ps[i - 1], True), tangent(ps[i], False)
            tx, ty = ta[0] + tb[0], ta[1] + tb[1]
            ln = math.hypot(tx, ty) or 1
            normals.append((-ty / ln, tx / ln))
        # outward side: the same all round a contour, decided by majority vote
        votes = sum(1 if path.contains((p[1][0] + nx * 3, p[1][1] + ny * 3)) else -1
                    for p, (nx, ny) in zip(ps, normals))
        sign = -1 if votes > 0 else 1
        moves = []
        for p, (nx, ny) in zip(ps, normals):
            d = sign * EDGE_ROUGH * field(*p[1])
            if AMP_LOG is not None:
                AMP_LOG.append(d * sign)
            moves.append((nx * d, ny * d))
        pen.moveTo(shift(ps[0][1], moves[0]))
        for i, p in enumerate(ps):
            v0, v1 = moves[i], moves[(i + 1) % n]
            end = shift(p[-1], v1)
            if p[0] == "L":
                pen.lineTo(end)
            else:
                pen.qCurveTo(shift(p[2], ((v0[0] + v1[0]) / 2, (v0[1] + v1[1]) / 2)), end)
        pen.closePath()
    out.simplify()
    return out


def roughen(path, seed):
    """Displace the outline along its normals by smooth fine noise (EDGE_ROUGH
    units, EDGE_WAVE wavelength), like ink bleeding into paper."""
    from fontTools.pens.basePen import decomposeQuadraticSegment
    from fontTools.pens.recordingPen import RecordingPen as _Rec
    if EDGE_STYLE == "width":
        return vary_width(path, seed)
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
    for ci, pts in enumerate(contours):
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
            if EDGE_BLEED_GAP > 0:
                # own generator (fine/env noise above stays as it was for every seed),
                # bleeds kept apart so they never stack into one big lump
                brng = random.Random(f"bleed-{seed}{EDGE_SEED}-{ci}")
                nb = brng.randint(0, max(1, int(perimeter / (EDGE_WAVE * 5))))
                gap = EDGE_WAVE * EDGE_BLEED_GAP
                bleeds = []
                for _ in range(nb * 4):
                    if len(bleeds) == nb:
                        break
                    pos = brng.uniform(0, perimeter)
                    if all(min(abs(pos - p), perimeter - abs(pos - p)) >= gap for p, _, _ in bleeds):
                        bleeds.append((pos, EDGE_WAVE * brng.uniform(0.35, 0.8), brng.uniform(0.8, EDGE_BLEED_MAX)))
            else:
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
                # soft limit: small displacements pass unchanged, big ones squeeze towards the ceiling
                out_amp = amp * sign
                lim = (EDGE_LIMIT_OUT if out_amp > 0 else EDGE_LIMIT_IN) * EDGE_ROUGH
                if lim > 0:
                    out_amp = lim * math.tanh(out_amp / lim)
                amp = out_amp * sign
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


def stroke(d, seed, k=1.0):
    """Stroke one centreline with the elliptical nib (scaled by k), return a pathops Path."""
    fwd = to_nib_space()
    src = pathops.Path()
    target = WarpPen(TransformPen(src.getPen(), fwd), seed)
    parse_path(d, FacetPen(target, seed + d) if FACET > 0 else target)
    src.stroke(NIB_H * k, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
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


def embolden(path, amount, shift=True):
    """Grow an outline outward by `amount` units on every side (union with a
    stroke of its own contour). With `shift`, it also moves right by `amount`
    so the left sidebearing is unchanged; the caller widens the advance by
    2*amount."""
    if not shift:
        amount_x = 0
    else:
        amount_x = amount
    edge = pathops.Path()
    path.draw(edge.getPen())
    edge.stroke(2 * amount, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    edge.convertConicsToQuads()
    comb = pathops.Path()
    path.draw(TransformPen(comb.getPen(), Transform().translate(amount_x, 0)))
    edge.draw(TransformPen(comb.getPen(), Transform().translate(amount_x, 0)))
    try:
        comb.simplify()
        return comb
    except pathops.PathOpsError:
        b = pathops.OpBuilder()
        for q in (path, edge):
            t = pathops.Path()
            q.draw(TransformPen(t.getPen(), Transform().translate(amount_x, 0)))
            b.add(t, pathops.PathOp.UNION)
        return b.resolve()


def build_outline(name, g):
    path = _build_outline(name, g)
    if EMBOLDEN > 0:
        path = embolden(path, EMBOLDEN)
    if THICKEN > 0:
        path = embolden(path, THICKEN, shift=False)
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
    nibs = g.get("nib") or [1.0] * len(g["s"])
    pieces = [stroke(d, seed, k) for d, k in zip(g["s"], nibs)] + [fill(d, seed) for d in g["f"]]
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




def tabular_outline(name, g):
    """A digit without edge noise, centred on its ink in a TABULAR_ADV cell."""
    path = build_outline(name, dict(g, rough={"EDGE_ROUGH": 0}))
    adv = max(TABULAR_ADV, g["adv"] + 2 * round(EMBOLDEN))
    x0, _, x1, _ = path.bounds
    dx = round((adv - (x1 - x0)) / 2 - x0)
    out = pathops.Path()
    path.draw(TransformPen(out.getPen(), Transform().translate(dx, 0)))
    return out, adv


def main(out_path=None, do_specimen=True):
    OUT.mkdir(parents=True, exist_ok=True)
    order, cmap, glyf, hmtx = [".notdef", "space"], {32: "space", 0xA0: "space"}, {}, {}
    glyf[".notdef"] = notdef()
    hmtx[".notdef"] = (500, 50)
    glyf["space"] = TTGlyphPen(None).glyph()
    hmtx["space"] = (SPACE + round(EMBOLDEN), 0)

    for ch, g in GLYPHS.items():
        name = glyph_name(ch)
        if ch in TABULAR_DIGITS:
            path, adv = tabular_outline(name, g)
            glyph, l = make_glyph(path), 0
        else:
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
