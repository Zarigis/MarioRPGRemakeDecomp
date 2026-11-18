"""Recolours the dialogue box (the "message window") towards the orange of the Super Nintendo original, as a RomFS mod.

The remake draws its dialogue box from one sprite, MsgWindow01, in the Addressables bundle
Data/StreamingAssets/aa/Switch/d_assets_/misc-textures.bundle. The sprite covers the whole of its own texture (also
named MsgWindow01: 1104x290, RGBA32, no mipmaps, no 9-slice borders): a pale yellow parchment with an orange vignette
towards the edges and a dark outline with cut corners. The catalog stores no CRC for this bundle (m_Crc 0 in its
AssetBundleRequestOptions), so a rewritten bundle loads in place of the game's.

The SNES box was orange (about #EBB769) with soft, broad brown blotches drawn out sideways and a darker, scorched
rim, and its dark text carried a cream outline that shows against that orange but not against the remake's pale
parchment. Two styles:
- parchment (default): the inside of the box is drawn anew in that manner: a lighter band through the middle and
  darker top and bottom, as on the SNES, with blotches from smooth value noise (random grids
  upsampled bicubically, summed over octaves; the cells about twice as wide as tall), mapped onto a ramp from a light
  orange through the base orange to brown, with an irregular darker rim towards the frame. The frame (the dark
  outline with its cut corners: the pixels much darker than the parchment) and the alpha stay the game's, or with
  --corners square (the default) the box is a rectangle whose edges wander in by up to --ragged pixels, with a
  few nicks, like the uneven edge of the SNES box, and the frame follows them.
  --seed picks another pattern.
- recolour: the game's own parchment keeps its light and dark pattern and takes the colour: each pixel's luminance
  relative to the parchment's median becomes the target colour scaled by that ratio.
The texture is stored back in its own format (RGBA32) with no mipmaps, as the game's is.

The name tag above the box (MsgName01) and every other window are left alone. The output is derived from the game's
files: it stays in the ignored build folder (the default mods folder is build/<version>/mods), where the port's mod
loader (runtime/mods.c) serves it in place of the game's file.

  python tools/dialog_box_mod.py [--style parchment|recolour] [--seed 7] [--corners square|cut] [--ragged 6] [--color e8b060] [--name dialog-box] [--mods build/v101/mods] [--romfs <extracted romfs>]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import UnityPy
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'Data/StreamingAssets/aa/Switch/d_assets_/misc-textures.bundle'
TEXTURES = ('MsgWindow01',)


def romfs_file(base, path):
    """A file of the extracted RomFS in base (romfs.bin plus index.json), read through its index."""
    idx = json.loads((base / 'index.json').read_text())
    for e in idx['files']:
        if e['path'] == path:
            with open(base / 'romfs.bin', 'rb') as f:
                f.seek(e['offset'])
                return f.read(e['size'])
    raise SystemExit(f'{path} is not in {base}/index.json: extract the game first (tools/extract.py)')


def recolour(img, color):
    """img (PIL RGBA) with every pixel's luminance mapped onto color (r, g, b in 0..255); alpha unchanged."""
    a = np.asarray(img.convert('RGBA')).astype(np.float64)
    rgb, alpha = a[..., :3], a[..., 3]
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    ref = np.median(lum[alpha > 250])
    out = np.clip(np.asarray(color, np.float64) * (lum / ref)[..., None], 0, 255)
    return Image.fromarray(np.dstack([out + 0.5, alpha]).astype(np.uint8), 'RGBA'), ref


def noise(rng, w, h, cw, ch):
    """Smooth value noise over w x h in -1..1: a random grid of cw x ch cells, upsampled bicubically."""
    g = (rng.random((ch + 3, cw + 3)) * 255).astype(np.uint8)
    im = Image.fromarray(g).resize(((cw + 3) * w // cw, (ch + 3) * h // ch), Image.BICUBIC)
    return np.asarray(im, np.float32)[:h, :w] / 127.5 - 1


def fbm(rng, w, h, cw, ch, octaves):
    """Octaves of noise, each with twice the cells and half the weight, normalised to about -1..1."""
    return sum(0.5 ** i * noise(rng, w, h, cw * 2 ** i, ch * 2 ** i) for i in range(octaves)) / (2 - 0.5 ** (octaves - 1))


def wobble(rng, n, depth):
    """How far an edge of n pixels lies inside its straight line, per pixel, 0..depth: a slow wave (a control point
    every ~60 px, smoothly joined), a faster one (~12 px) at a third of the weight, and a few nicks (narrow dents
    a little deeper), like the torn, uneven edge of the SNES box."""
    def wave(step):
        xs = np.arange(0, n + step, step)
        return np.interp(np.arange(n), xs, rng.random(len(xs)))
    w = (0.75 * wave(60) + 0.25 * wave(12)) * depth
    for c in rng.integers(0, n, max(1, n // 250)):   # nicks: about one per 250 px
        w = np.maximum(w, depth * 1.4 * np.exp(-((np.arange(n) - c) / rng.uniform(2, 5)) ** 2))
    return w.astype(np.float32)


def square_box(a, inside, rng, ragged):
    """The box as a rectangle: the opaque area's bounding box, its edges moved inwards by up to ragged pixels (wobble)
    and drawn with soft (one pixel) edges, the frame along them in the game's frame colour and thickness (both measured
    halfway down the left edge). a's colour and alpha are set to the frame's; returns the parchment's coverage (0..1
    per pixel) for the caller to draw the parchment with."""
    rows, cols = np.nonzero(a[..., 3] > 250)
    y0, y1, x0, x1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    t = int(np.argmax(inside[(y0 + y1) // 2, x0:x1]))   # the frame's width: the first inside pixel of that row
    frame_rgb = a[(y0 + y1) // 2, x0:x0 + max(t, 1), :3].mean(0)
    h, w = a.shape[:2]
    y = np.arange(h, dtype=np.float32)[:, None] + 0.5
    x = np.arange(w, dtype=np.float32)[None, :] + 0.5
    top, bottom = wobble(rng, w, ragged)[None, :], wobble(rng, w, ragged)[None, :]
    left, right = wobble(rng, h, ragged)[:, None], wobble(rng, h, ragged)[:, None]
    # signed distance (in pixels, roughly) inside the ragged outline: the nearest of the four edges
    m = np.minimum(np.minimum(y - y0 - top, y1 - y - bottom), np.minimum(x - x0 - left, x1 - x - right))
    a[..., 3] = np.clip(m, 0, 1) * 255
    a[..., :3] = frame_rgb
    return np.clip(m - t, 0, 1)


def parchment(img, color, seed, square, ragged):
    """img (PIL RGBA) with the inside of the box drawn as SNES-style mottled parchment around color; frame and alpha
    kept, or with square, a rectangle with uneven edges (square_box). The ramp's other stops are fixed offsets from
    the SNES palette, scaled with color."""
    a = np.asarray(img.convert('RGBA')).astype(np.float32)
    h, w = a.shape[:2]
    alpha = a[..., 3]
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    ref = np.median(lum[alpha > 250])
    inside = (alpha > 250) & (lum > 0.4 * ref)   # the frame is the dark outline
    rng = np.random.default_rng(seed)
    cover = square_box(a, inside, np.random.default_rng(seed + 1), ragged) if square else inside.astype(np.float32)
    inside = cover > 0.5
    blot = fbm(rng, w, h, 7, 6, 4)        # broad blotches, about 2.5x as wide as tall at this aspect
    blot2 = fbm(rng, w, h, 20, 22, 3)     # smaller ones
    fibre = fbm(rng, w, h, 60, 140, 2)    # a faint sideways grain
    rim_noise = fbm(rng, w, h, 10, 4, 3)
    grain = rng.normal(0, 1, (h, w)).astype(np.float32)
    grain = np.asarray(Image.fromarray(np.clip(grain * 40 + 128, 0, 255).astype(np.uint8))
                       .filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 128 - 1
    # nearness to the frame: 1 minus the blurred inside mask, 0 deep inside and 1 at the frame
    near = 1 - np.asarray(Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(26)),
                          np.float32) / 255
    near = np.clip(near * 2, 0, 1)
    rim = np.clip(near * 1.3 + 0.35 * rim_noise * near - 0.1, 0, 1)
    # the SNES box's layout: darker at the top and the bottom, a lighter band through the middle (a cosine across the
    # inside's height), with the blotches over it
    rows = np.nonzero(inside.any(1))[0]
    v = np.clip((np.arange(h, dtype=np.float32) - rows[0]) / max(1, rows[-1] - rows[0]), 0, 1)
    band = np.cos(np.pi * (v - 0.5) * 2) * 0.5 + 0.5   # 1 in the middle, 0 at the top and the bottom
    band = (0.9 * band - 0.45)[:, None]                # +0.45 in the middle, -0.45 at the top and the bottom
    tone = band + 0.3 * blot + 0.15 * blot2 + 0.05 * fibre + 0.04 * grain   # 0 base, below darker, above lighter
    tone = (np.sign(tone) * np.abs(tone) ** 0.9)[..., None]
    k = np.asarray(color, np.float32) / np.array([232, 176, 96], np.float32)
    base, light = np.array([232, 176, 96]) * k, np.array([242, 196, 116]) * k
    dark, darker = np.array([176, 112, 44]) * k, np.array([128, 78, 30]) * k
    col = np.where(tone > 0, base + (light - base) * np.clip(tone * 2.2, 0, 1),
                   base + (dark - base) * np.clip(-tone * 2.6, 0, 1))
    col = col + (darker - col) * (rim[..., None] * 0.85)
    a[..., :3] += (col - a[..., :3]) * cover[..., None]
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), 'RGBA'), ref


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--color', default='e8b060', help='the box colour, sRGB hex (default the SNES orange)')
    ap.add_argument('--style', default='parchment', choices=('parchment', 'recolour'))
    ap.add_argument('--seed', type=int, default=7, help='the parchment pattern')
    ap.add_argument('--corners', default='square', choices=('square', 'cut'),
                    help='parchment style: a plain rectangle (default) or the game\'s cut corners')
    ap.add_argument('--ragged', type=float, default=6,
                    help='square corners: how far the uneven edges reach in, in texture pixels (0 straight)')
    ap.add_argument('--version', default='v101')
    ap.add_argument('--romfs', help='the extracted RomFS (default build/extracted/<version>/romfs)')
    ap.add_argument('--name', default='dialog-box', help='the mod folder name')
    ap.add_argument('--mods', help='the mods folder (default build/<version>/mods, next to mrpg.exe)')
    a = ap.parse_args()
    color = [int(a.color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]

    env = UnityPy.load(romfs_file(Path(a.romfs) if a.romfs else ROOT / 'build' / 'extracted' / a.version / 'romfs', BUNDLE))
    texs = {o.path_id: o for o in env.objects if o.type.name == 'Texture2D' and o.peek_name() in TEXTURES}
    if len(texs) != len(TEXTURES):
        raise SystemExit(f'{BUNDLE}: expected one Texture2D each of {TEXTURES}, found {len(texs)}')
    # which sprites draw from these textures: a texture shared with other UI would turn that UI orange too
    for o in env.objects:
        if o.type.name == 'Sprite':
            tt = o.read_typetree()
            pid = tt['m_RD']['texture']['m_PathID']
            if pid in texs:
                print(f'sprite {tt["m_Name"]} uses texture {texs[pid].peek_name()}')

    mods = Path(a.mods) if a.mods else ROOT / 'build' / a.version / 'mods'
    for o in texs.values():
        tex = o.read()
        fmt, mips = tex.m_TextureFormat, tex.m_MipCount
        img, ref = parchment(tex.image, color, a.seed, a.corners == 'square', a.ragged) if a.style == 'parchment' else recolour(tex.image, color)
        (mods / a.name).mkdir(parents=True, exist_ok=True)
        img.save(mods / a.name / f'{tex.m_Name}.png')   # a look at the result (outside romfs)
        tex.set_image(img, target_format=fmt, mipmap_count=mips)
        tex.save()
        print(f'{tex.m_Name}: {tex.m_Width}x{tex.m_Height} format {fmt} mips {mips}, '
              f'parchment luminance {ref:.0f} -> #{a.color.lstrip("#")}')

    out = mods / a.name / 'romfs' / BUNDLE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(env.file.save())
    print(f'{out}: {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
