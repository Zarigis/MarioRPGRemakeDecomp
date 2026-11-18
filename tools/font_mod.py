"""Replaces one of the game's TextMeshPro fonts with a TrueType or OpenType font, as a RomFS mod.

The remake keeps its fonts in Addressables bundles (Data/StreamingAssets/aa/Switch/fonts_assets_/font_tmpro_*.bundle).
Each holds one TextMeshPro font asset: a signed-distance-field atlas (a 512x512 Alpha8 Texture2D: 0.5 on a glyph's
edge, rising inside and falling outside over the material's _GradientScale, the atlas padding + 1, in atlas pixels)
and a MonoBehaviour with the face metrics, the glyph table (metrics in points at the face's point size, and the glyph's
rectangle in the atlas, measured from the atlas's bottom left, padding outside it) and the character table (Unicode to
glyph index). The catalog stores no CRC for these bundles, so a bundle with another atlas and other tables loads in
place of the game's.

This tool reads the bundle from the extracted RomFS (build/extracted/<version>/romfs), renders every character of the
font asset's character table from the given font, packs the glyphs into a new atlas of the same size, rewrites the
glyph table and the line metrics, and writes the bundle into <mods>/<name>/romfs/... where the port's mod loader
(runtime/mods.c) serves it in place of the game's. The new font is scaled so its capital height matches the game
font's (the dialogue boxes are laid out for that), and the game font's line height, ascent and descent are kept.
Characters the font asset does not list keep coming from its fallback fonts; characters the new font has no glyph
for (the game's stars, heart and note, its full-width digits) keep the game font's glyph. The output is derived from the game's
files: it stays in the ignored build folder (the default mods folder is build/<version>/mods).

--outline turns on the outline of the bundle's material (outline); with --outline-color auto, the default, the port
draws it light around dark text and dark around light text (runtime/text_outline.c).

  python tools/font_mod.py --font C:/Windows/Fonts/Gabriola.ttf [--bundle regular] [--name font-test] [--outline 0.07]
"""
import argparse
import json
from pathlib import Path

import numpy as np
import UnityPy
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = 'Data/StreamingAssets/aa/Switch/fonts_assets_'
SUPER = 8   # glyphs are rendered this many times the atlas resolution, and the distances measured there


def romfs_file(version, path):
    """A file of the extracted RomFS, read through its index (romfs.bin plus index.json)."""
    base = ROOT / 'build' / 'extracted' / version / 'romfs'
    idx = json.loads((base / 'index.json').read_text())
    for e in idx['files']:
        if e['path'] == path:
            with open(base / 'romfs.bin', 'rb') as f:
                f.seek(e['offset'])
                return f.read(e['size'])
    raise SystemExit(f'{path} is not in {base}/index.json: extract the game first (tools/extract.py)')


def sdf_glyph(font, ch, pad, grad):
    """(alpha image as uint8 array with pad pixels around the ink, metrics dict) for one character at atlas scale.
    The ink is rendered SUPER times larger; each atlas pixel takes the signed distance from its centre to the nearest
    edge pixel there, encoded as 0.5 + d / (2 * grad), clamped."""
    x0, y0, x1, y1 = font.getbbox(ch, anchor='ls')   # at SUPER scale, relative to the pen on the baseline
    adv = font.getlength(ch) / SUPER
    if x1 <= x0 or y1 <= y0:   # a space
        return None, {'w': 0.0, 'h': 0.0, 'bx': 0.0, 'by': 0.0, 'adv': adv}
    # the atlas cell: the ink box at atlas scale, rounded out, plus the padding
    ax0, ay0 = int(np.floor(x0 / SUPER)), int(np.floor(y0 / SUPER))
    ax1, ay1 = int(np.ceil(x1 / SUPER)), int(np.ceil(y1 / SUPER))
    w, h = ax1 - ax0, ay1 - ay0
    cw, ch_ = w + 2 * pad, h + 2 * pad
    hi = Image.new('L', (cw * SUPER, ch_ * SUPER), 0)
    ImageDraw.Draw(hi).text(((pad - ax0) * SUPER, (pad - ay0) * SUPER), ch, font=font, fill=255, anchor='ls')
    m = np.asarray(hi) >= 128
    # edge pixels: inside pixels with an outside neighbour, and the reverse
    edge = np.zeros_like(m)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        edge |= m != np.roll(np.roll(m, dy, 0), dx, 1)
    ey, ex = np.nonzero(edge)
    pts = np.stack([ey + 0.5, ex + 0.5], 1) / SUPER
    gy, gx = np.mgrid[0:ch_, 0:cw]
    cen = np.stack([gy.ravel() + 0.5, gx.ravel() + 0.5], 1)
    d = np.full(len(cen), 1e9)
    for i in range(0, len(pts), 4096):   # nearest edge point, in chunks to bound the memory
        p = pts[i:i + 4096]
        d = np.minimum(d, np.sqrt(((cen[:, None, :] - p[None, :, :]) ** 2).sum(2)).min(1))
    inside = m[(gy.ravel() + 0.5).astype(int) * SUPER + SUPER // 2, (gx.ravel() + 0.5).astype(int) * SUPER + SUPER // 2]
    sd = np.where(inside, d, -d)
    a = np.clip(0.5 + sd / (2 * grad), 0, 1).reshape(ch_, cw)
    met = {'w': (x1 - x0) / SUPER, 'h': (y1 - y0) / SUPER, 'bx': x0 / SUPER, 'by': -y0 / SUPER, 'adv': adv,
           'cw': w, 'ch': h}
    return (a * 255 + 0.5).astype(np.uint8), met


def has_glyph(font, ch, notdef):
    """0 when the font draws ch as its missing-glyph box (the same ink as a code point no font has)."""
    box = font.getbbox(ch, anchor='ls')
    if box != notdef[0]:
        return 1
    im = Image.new('L', (box[2] - box[0] + 2, box[3] - box[1] + 2), 0)
    ImageDraw.Draw(im).text((1 - box[0], 1 - box[1]), ch, font=font, fill=255, anchor='ls')
    return im.tobytes() != notdef[1]


def outline(env, em, px_per_em, color):
    """Turns on the outline of the bundle's material (TextMeshPro's Distance Field shader, which the font asset draws
    with unless a text picks another material). The shader (TMPro_Properties.cginc GetColor) centres an outline band of
    _OutlineWidth * _ScaleRatioA distance units on the glyph's edge, and the vertex shader moves that edge out by
    _FaceDilate * _ScaleRatioA / 2 units; with the dilation equal to the width, the letters keep their weight and the
    whole band lies outside them. A distance unit is 2 * _GradientScale atlas pixels, so the band reaches
    width * _ScaleRatioA * 2 * _GradientScale atlas pixels out, which has to stay inside the padding. The width asked
    for is em, a fraction of the em, so fonts with other paddings (the bold and ultra bundles have wider ones, so a
    distance unit spans more pixels) get the same outline: em * px_per_em atlas pixels. _ScaleRatioA is recomputed
    as TextMeshPro's ShaderUtilities.UpdateShaderRatios does (the editor does it there; the player does not); it
    depends on the width, so the two are solved together."""
    # auto: magenta, the marker for the port's shader (runtime/text_outline.c) to pick the outline from the text's colour
    rgb = [1, 0, 1] if color == 'auto' else [int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    for o in env.objects:
        if o.type.name != 'Material':
            continue
        m = o.read_typetree()
        fl, co = dict(m['m_SavedProperties']['m_Floats']), dict(m['m_SavedProperties']['m_Colors'])
        if '_OutlineWidth' not in fl:
            continue
        grad, px = fl['_GradientScale'], em * px_per_em
        weight = max(fl['_WeightNormal'], fl['_WeightBold']) / 4
        width = 0.0
        for _ in range(8):   # width from the ratio, the ratio from the width: settles in a step or two
            t = max(1.0, weight + 2 * width + fl['_OutlineSoftness'])
            ratio = (grad - 1) / (grad * t)
            width = px / (ratio * 2 * grad)
        if px > grad - 1:
            raise SystemExit(f'an outline of {px:.1f} atlas px does not fit the padding of {grad - 1:.0f}')
        fl['_OutlineWidth'], fl['_FaceDilate'], fl['_ScaleRatioA'] = width, width, ratio
        co['_OutlineColor'] = {'r': rgb[0], 'g': rgb[1], 'b': rgb[2], 'a': 1.0}
        m['m_SavedProperties']['m_Floats'] = list(fl.items())
        m['m_SavedProperties']['m_Colors'] = list(co.items())
        o.save_typetree(m)
        print(f'{m["m_Name"]}: outline {em} em, {px:.1f} atlas px past the letters (_OutlineWidth {width:.3f}), '
              f'#{color.lstrip("#")}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--font', required=True, help='TrueType or OpenType font file')
    ap.add_argument('--bundle', default='regular', help='which font_tmpro_<name>.bundle (regular, bold, ultra)')
    ap.add_argument('--version', default='v101')
    ap.add_argument('--name', default='font-test', help='the mod folder name')
    ap.add_argument('--mods', help='the mods folder (default build/<version>/mods, next to mrpg.exe)')
    ap.add_argument('--scale', type=float, default=1.0, help='size factor on top of the capital-height match')
    ap.add_argument('--outline', type=float, default=0.0,
                    help='outline width as a fraction of the em (0 none; 0.07 is about 1 SNES pixel at the dialogue '
                         'size; the most the regular font\'s padding holds is about 0.13)')
    ap.add_argument('--outline-color', default='auto',
                    help='outline colour, sRGB hex; auto (default): light around dark text and dark around light text, '
                         'drawn by the port (runtime/text_outline.c, settings text_outline_light and _dark)')
    a = ap.parse_args()

    rel = f'{BUNDLE_DIR}/font_tmpro_{a.bundle}.bundle'
    env = UnityPy.load(romfs_file(a.version, rel))
    tex_obj = mono_obj = None
    for o in env.objects:
        if o.type.name == 'Texture2D':
            tex_obj = o
        elif o.type.name == 'MonoBehaviour' and 'm_GlyphTable' in (o.read_typetree() or {}):
            mono_obj = o
    if not tex_obj or not mono_obj:
        raise SystemExit(f'{rel}: no TextMeshPro font asset in it')
    fa = mono_obj.read_typetree()
    tex = tex_obj.read()
    W, H, pad = fa['m_AtlasWidth'], fa['m_AtlasHeight'], fa['m_AtlasPadding']
    grad = pad + 1   # the materials' _GradientScale (font_mtl.bundle: 6 with padding 5)
    face = fa['m_FaceInfo']

    # scale: the new font's capital height to the game font's cap line, at SUPER times the atlas resolution
    probe = ImageFont.truetype(a.font, 1000)
    cap = -probe.getbbox('H', anchor='ls')[1]
    size = face['m_CapLine'] / cap * 1000 * a.scale
    font = ImageFont.truetype(a.font, max(1, round(size * SUPER)))

    by_index = {g['m_Index']: g for g in fa['m_GlyphTable']}
    orig_atlas = np.asarray(tex.image.split()[-1])   # top-down, as PIL gives it
    nb = font.getbbox('\U0010fffd', anchor='ls')
    nim = Image.new('L', (nb[2] - nb[0] + 2, nb[3] - nb[1] + 2), 0)
    ImageDraw.Draw(nim).text((1 - nb[0], 1 - nb[1]), '\U0010fffd', font=font, fill=255, anchor='ls')
    notdef = (nb, nim.tobytes())
    kept = []
    atlas = np.zeros((H, W), np.uint8)
    x = y = row = 0
    used = []
    for c in fa['m_CharacterTable']:
        g = by_index.get(c['m_GlyphIndex'])
        if not g:
            continue
        ch = chr(c['m_Unicode'])
        if has_glyph(font, ch, notdef):
            img, met = sdf_glyph(font, ch, pad, grad)
            g['m_Metrics'] = {'m_Width': met['w'], 'm_Height': met['h'], 'm_HorizontalBearingX': met['bx'],
                              'm_HorizontalBearingY': met['by'], 'm_HorizontalAdvance': met['adv']}
        else:   # the game font's glyph: its cell of the old atlas, its metrics as they are
            r0 = g['m_GlyphRect']
            kept.append(f'U+{c["m_Unicode"]:04X}')
            if not r0['m_Width']:
                continue
            top = H - (r0['m_Y'] + r0['m_Height']) - pad
            img = orig_atlas[top:top + r0['m_Height'] + 2 * pad, r0['m_X'] - pad:r0['m_X'] + r0['m_Width'] + pad]
            met = {'cw': r0['m_Width'], 'ch': r0['m_Height']}
        if img is None:
            g['m_GlyphRect'] = {'m_X': 0, 'm_Y': 0, 'm_Width': 0, 'm_Height': 0}
            continue
        hh, ww = img.shape
        if x + ww > W:
            x, y, row = 0, y + row, 0
        if y + hh > H:
            raise SystemExit('the glyphs do not fit the atlas: try --scale below 1')
        atlas[y:y + hh, x:x + ww] = img   # top-down here; flipped to Unity's bottom-up order when stored
        # the rectangle without the padding, its y from the atlas's bottom
        r = {'m_X': x + pad, 'm_Y': H - (y + hh) + pad, 'm_Width': met['cw'], 'm_Height': met['ch']}
        g['m_GlyphRect'] = r
        used.append({'m_X': x, 'm_Y': H - (y + hh), 'm_Width': ww, 'm_Height': hh})
        x += ww
        row = max(row, hh)
    fa['m_UsedGlyphRects'] = used
    fa['m_FreeGlyphRects'] = []
    fa['m_FontFeatureTable']['m_GlyphPairAdjustmentRecords'] = []   # the game font's kerning pairs do not apply
    face['m_FamilyName'] = f'{face["m_FamilyName"]} ({Path(a.font).stem})'
    mono_obj.save_typetree(fa)
    if a.outline:
        outline(env, a.outline, size, a.outline_color)

    rgba = Image.merge('RGBA', [Image.new('L', (W, H), 255)] * 3 + [Image.fromarray(atlas)])
    tex.image = rgba
    tex.save()

    mods = Path(a.mods) if a.mods else ROOT / 'build' / a.version / 'mods'
    out = mods / a.name / 'romfs' / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(env.file.save())
    Image.fromarray(atlas).save(mods / a.name / f'atlas-{a.bundle}.png')   # a look at the atlas (outside romfs)
    print(f'{out}: {len(used)} glyphs from {Path(a.font).name} at {size:.1f} px per em; the game font\'s kept for '
          f'{len(kept)} it lacks ({" ".join(kept)})')


if __name__ == '__main__':
    main()
