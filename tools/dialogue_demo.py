"""A picture of the dialogue box mod with the Parchment Hand font, for the README, drawn from neither the game's files
nor a screenshot: the box comes from tools/dialog_box_mod.py (parchment style, square corners, seed 7, as installed by
default) and the text from the font, laid out the way the game lays out its dialogue at 1920x1080.

The layout was measured on a 1920x1080 screenshot of the port with both mods, on a one-line dialogue:
- the box's frame spans x 410..1510, y 771..1044: the texture's opaque area (1096x283 of its 1104x290) at 1.0 across
  and 0.965 down;
- the line's capital height is 25 px (cap top 820, baseline 845) and its ink starts at x 511;
- the letters stand 1.8 px further apart than the font's advances give (TRACK): the line was 563 px wide, against
  507 px with the font's own spacing.
The game font's cap line is 26 of its 32-unit em (font_tmpro_regular's m_FaceInfo), so the em is 30.8 px there.
tools/font_mod.py scales a replacement font to the game font's capital height, and so does this script. The outline is
0.07 em (as tools/parchment_font/README.md installs it) in the port's default colours (runtime/cfg.c: TEXT_DARK 361a0c,
TEXT_OUTLINE_LIGHT f2e0c0). The line pitch was not measured (one line): LINE_PITCH = 1.6 em puts four baselines in the
box with the same margin above the first capital and below the last baseline.

  python tools/dialogue_demo.py [--font build/font/ParchmentHand.ttf] [--out docs/images/dialogue_demo.png] [--scale 2]
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dialog_box_mod import parchment

ROOT = Path(__file__).resolve().parents[1]
BOX = (410, 771, 1510, 1044)   # the frame on a 1920x1080 screen: left, top, right, bottom
CAP, BASE0, INK_X = 25, 845, 511
EM = CAP * 32 / 26
TRACK = 1.8                    # px between letters beyond the font's advances
LINE_PITCH = 1.6 * EM
OUTLINE = 0.07 * EM
TEXT, OUTLINE_COLOUR = (0x36, 0x1a, 0x0c), (0xf2, 0xe0, 0xc0)
VIEW = (370, 730, 1550, 1080)  # the part of the screen the picture shows
BACKGROUND = (24, 52, 56)
LINES = ('the quick brown fox jumps over the lazy dog.',
         'THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG.')
# the box texture: its size, and the opaque area and frame colour and width of the game's MsgWindow01
TEX_W, TEX_H, OPAQUE, FRAME_RGB, FRAME_W = 1104, 290, (4, 3, 1101, 287), (59, 46, 37), 5
SUPER = 4   # the text is drawn at this many times the output size and shrunk, for smooth edges


def box_texture():
    """The box as tools/dialog_box_mod.py draws it, from a plain stand-in for the game's texture: the parchment style
    with square corners keeps only the stand-in's opaque area and its frame's colour and width."""
    a = np.zeros((TEX_H, TEX_W, 4), np.uint8)
    x0, y0, x1, y1 = OPAQUE
    a[y0:y1, x0:x1] = FRAME_RGB + (255,)
    a[y0 + FRAME_W:y1 - FRAME_W, x0 + FRAME_W:x1 - FRAME_W, :3] = (240, 220, 170)
    return parchment(Image.fromarray(a, 'RGBA'), [0xe8, 0xb0, 0x60], 7, True, 6)[0]


def draw_line(d, font, x, y, text, track, **kw):
    """text with its first letter's pen at x, each letter where the font puts it after the text before it (so kerning
    stays), plus track per letter."""
    for i, ch in enumerate(text):
        d.text((x + font.getlength(text[:i]) + i * track, y), ch, font=font, anchor='ls', **kw)


def render(font_path, k):
    """The picture at k times the 1080p size."""
    w, h = round((VIEW[2] - VIEW[0]) * k), round((VIEW[3] - VIEW[1]) * k)
    img = Image.new('RGBA', (w, h), BACKGROUND + (255,))
    sx = (BOX[2] - BOX[0]) / (OPAQUE[2] - OPAQUE[0])
    sy = (BOX[3] - BOX[1]) / (OPAQUE[3] - OPAQUE[1])
    tex = box_texture().resize((round(TEX_W * sx * k), round(TEX_H * sy * k)), Image.LANCZOS)
    img.alpha_composite(tex, (round((BOX[0] - OPAQUE[0] * sx - VIEW[0]) * k),
                              round((BOX[1] - OPAQUE[1] * sy - VIEW[1]) * k)))

    probe = ImageFont.truetype(str(font_path), 1000)
    size = CAP / -probe.getbbox('H', anchor='ls')[1] * 1000   # the font size whose capitals are CAP px tall
    s = k * SUPER
    font = ImageFont.truetype(str(font_path), round(size * s))
    text = Image.new('RGBA', (w * SUPER, h * SUPER), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    for i, line in enumerate(LINES):
        x = (INK_X - VIEW[0]) * s - font.getbbox(line[0], anchor='ls')[0]   # the ink, not the pen, starts at INK_X
        y = (BASE0 + i * LINE_PITCH - VIEW[1]) * s
        # every outline before the letters, as the game draws it beneath them, so none covers the next letter
        draw_line(d, font, x, y, line, TRACK * s, fill=OUTLINE_COLOUR, stroke_width=round(OUTLINE * s),
                  stroke_fill=OUTLINE_COLOUR)
        draw_line(d, font, x, y, line, TRACK * s, fill=TEXT)
    img.alpha_composite(text.resize((w, h), Image.LANCZOS))
    return img.convert('RGB')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--font', default=str(ROOT / 'build' / 'font' / 'ParchmentHand.ttf'),
                    help='the font (default the build of tools/parchment_font/build.py)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'images' / 'dialogue_demo.png'))
    ap.add_argument('--scale', type=float, default=2, help='size over the 1080p layout (default 2)')
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    render(a.font, a.scale).save(out, optimize=True)
    print(f'{out}: {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
