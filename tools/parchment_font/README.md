# Parchment Hand

An original hand-lettered font in the spirit of the Super Nintendo game's dialogue lettering, for the port's font mod.
Each glyph is a set of centreline strokes drawn with an elliptical nib (`glyphs.py`); `build.py` turns them into
TrueType outlines, Regular and Bold. These two files are under the BSD 3-Clause licence in `LICENSE` here, not the
repository's MIT licence.

Build the fonts (they land in `build/font`, which git ignores):

    .venv\Scripts\python tools\parchment_font\build.py

It needs `fonttools`, `skia-pathops` and `Pillow` (all in `tools/requirements.txt`). The result is
`ParchmentHand.ttf`, `ParchmentHand-Bold.ttf` and a specimen image, `specimen.png`.

Install them into the game as a mod, with the outline the port colours by the text (`runtime/text_outline.c`):

    .venv\Scripts\python tools\font_mod.py --font build\font\ParchmentHand.ttf --name parchment-hand --outline 0.07
    .venv\Scripts\python tools\font_mod.py --font build\font\ParchmentHand-Bold.ttf --bundle bold --name parchment-hand --outline 0.04
    .venv\Scripts\python tools\font_mod.py --font build\font\ParchmentHand-Bold.ttf --bundle ultra --name parchment-hand --outline 0.04

To change a letter, edit its strokes in `glyphs.py` (coordinates in source pixels: caps are rows 0 to 9, one pixel is
70 font units) and build again. `build.py` holds the nib, the edge texture and the Bold's settings at its top.
