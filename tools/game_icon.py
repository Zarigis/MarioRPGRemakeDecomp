"""mrpg.exe's icon, made from the game's own title icon (the picture the console shows for the game).

tools/extract.py unpacks the RomFS of the update's Control NCA into extracted/<version>/control: control.nacp and one
icon_<language>.dat per language, each a 256x256 JPEG (the characters and the logo on white). tools/build_game.py calls
make_ico on the American English one and embeds the result in mrpg.exe in place of runtime/mrpg.ico. The output is
derived from the game's files, so it stays in the build folder.

Two changes make it an icon:
- The white around the picture, and the grey shadows the characters cast on it, become transparent: the pixels that are
  light and nearly grey and are joined to the picture's border (a flood fill from the border), so white inside the
  picture stays. The edge of what stays is grown by a pixel and blurred a little against the JPEG's ringing.
- At 32x32 and smaller the whole group is a blur, so those sizes take a square around Mario's face (FACE) instead.

  python tools/game_icon.py <icon_AmericanEnglish.dat> <out.ico>
"""
import sys
from collections import deque
from pathlib import Path

ICON = 'icon_AmericanEnglish.dat'
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL = 32   # this size and below show FACE
FACE = (88, 92, 168, 172)   # Mario's face in the 256x256 title icon: left, top, right, bottom
# Background: a pixel no darker than LIGHT in any channel whose channels differ by GREY at most (white and the shadows;
# the characters' cream and pale colours differ by more).
LIGHT, GREY = 140, 22


def cut_out(image):
    """image (RGB) as RGBA with its background, as found from the border, transparent."""
    from PIL import ImageFilter
    w, h = image.size
    px = image.load()
    seen = bytearray(w * h)
    todo = deque([(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)])
    while todo:
        x, y = todo.popleft()
        if not (0 <= x < w and 0 <= y < h) or seen[y * w + x]:
            continue
        p = px[x, y]
        if min(p) < LIGHT or max(p) - min(p) > GREY:
            continue
        seen[y * w + x] = 1
        todo.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    from PIL import Image
    alpha = Image.frombytes('L', (w, h), bytes(0 if s else 255 for s in seen))
    alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    out = image.convert('RGBA')
    out.putalpha(alpha)
    return out


def make_ico(src, dst):
    """Writes dst (.ico, every size of SIZES) from the title icon src."""
    from PIL import Image
    with Image.open(src) as im:
        picture = cut_out(im.convert('RGB').resize((256, 256), Image.LANCZOS))
    face = picture.crop(FACE)
    images = [(face if s <= SMALL else picture).resize((s, s), Image.LANCZOS) for s in SIZES]
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes each size of sizes from the image it is given, or from append_images when one has that size
    images[-1].save(dst, format='ICO', sizes=[(s, s) for s in SIZES], append_images=images[:-1])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    make_ico(sys.argv[1], sys.argv[2])
