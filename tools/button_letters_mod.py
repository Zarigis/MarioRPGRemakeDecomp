"""Keeps the game's own lettering on the UI's button icons when a font mod replaces the bold font, as a RomFS mod.

The pause menu, battle, shop, mini game and other UI layouts draw the letter on a button icon (the A, B, X or Y on its
coloured circle) as a TextMeshPro text of its own, one letter long, in the bold font (font_tmpro_bold.bundle): objects
named ButtonTex or BTex in the prefab bundles. A font mod that replaces the bold font (tools/font_mod.py) would draw
those letters in the new font too. tools/font_mod.py --button-glyphs keeps the game font's A, B, X and Y as extra
characters at U+E000..U+E003; this tool rewrites each button letter text to its extra character, so the buttons keep
the game's lettering and every other text takes the new font.

Most button letters are not in the layouts but in the menu's text tables, one per language
(Data/StreamingAssets/data_tbl/lang/menu_text_<lang>.tbl), which the UI writes into those texts: "A" before "Enter",
"B" before "Back", "X" before "Items", and so on. The tables are .NET BinaryFormatter data, its strings
BinaryObjectString records (0x06, a 32-bit object id, a 7-bit encoded byte length, UTF-8) one after another with nothing
pointing into them, so a one-letter string can grow to the three UTF-8 bytes of its extra character. Each table's
one-letter A, B, X or Y strings are rewritten, except those next to other one-letter strings: the European tables also
hold letter sequences (E S Y A R, a puzzle's letters), which are not buttons.

In the layouts it finds the texts by what they are, not by a list: every MonoBehaviour with an m_text of one button letter (spaces
around it allowed), drawn in the bold font asset, on a GameObject named ButtonTex or BTex. The bundles it changes are
written into <mods>/<name>/romfs/..., the mod folder of the font mod (default parchment-hand): the extra characters
exist only in that font, so the two belong together. The output is derived from the game's files and stays in the
ignored build folder.

  python tools/button_letters_mod.py [--name parchment-hand] [--mods build/v101/mods]

Build the bold font with --button-glyphs first, into the same mod folder. Takes a few minutes: it reads every UI
bundle.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import UnityPy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from font_mod import BUNDLE_DIR, BUTTON_GLYPHS, ROOT, romfs_file  # noqa: E402

NAMES = ('ButtonTex', 'BTex')   # the button letters' GameObjects


def bold_font_id(version):
    """The path id of the bold font asset (the MonoBehaviour holding the glyph table) in font_tmpro_bold.bundle."""
    env = UnityPy.load(romfs_file(version, f'{BUNDLE_DIR}/font_tmpro_bold.bundle'))
    for o in env.objects:
        if o.type.name == 'MonoBehaviour' and 'm_GlyphTable' in (o.read_typetree() or {}):
            return o.path_id
    raise SystemExit('font_tmpro_bold.bundle: no font asset')


STRING = re.compile(rb'\x06(.{4})([\x00-\x7f])', re.S)   # BinaryObjectString with a length under 128


def tables(data):
    """data (a menu text table) with its button letter strings rewritten to the kept glyphs, and how many."""
    strs = []   # (offset, length byte offset, text) of every string record
    for m in STRING.finditer(data):
        i, n = m.start(), data[m.start() + 5]
        try:
            strs.append((i, data[i + 6:i + 6 + n].decode()))
        except UnicodeDecodeError:   # not a string record: the pattern matched inside other data
            continue
    out, last, count = bytearray(), 0, 0
    for k, (i, t) in enumerate(strs):
        if t not in BUTTON_GLYPHS:
            continue
        near = [strs[j][1] for j in (k - 1, k + 1) if 0 <= j < len(strs)]
        if any(len(x) == 1 and x.isalpha() for x in near):   # a letter sequence, not a button
            continue
        new = chr(BUTTON_GLYPHS[t]).encode()
        out += data[last:i + 5] + bytes([len(new)]) + new
        last = i + 6 + 1
        count += 1
    return bytes(out + data[last:]), count


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--version', default='v101')
    ap.add_argument('--name', default='parchment-hand', help='the font mod\'s folder name')
    ap.add_argument('--mods', help='the mods folder (default build/<version>/mods, next to mrpg.exe)')
    a = ap.parse_args()
    mods = Path(a.mods) if a.mods else ROOT / 'build' / a.version / 'mods'
    bold = bold_font_id(a.version)
    base = ROOT / 'build' / 'extracted' / a.version / 'romfs'
    files = json.loads((base / 'index.json').read_text())['files']
    total = 0
    for e in files:   # the menu text tables
        p = e['path']
        if '/data_tbl/lang/menu_text_' not in p:
            continue
        data, n = tables(romfs_file(a.version, p))
        if n:
            out = mods / a.name / 'romfs' / p
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            print(f'{p}: {n} button letters')
            total += n
    for e in files:   # the layouts
        p = e['path']
        name = p.rsplit('/', 1)[-1]
        if not p.endswith('.bundle') or 'fonts_assets_' in p or name.startswith(('d_assets', 'misc-textures')):
            continue
        env = UnityPy.load(romfs_file(a.version, p))
        objs = {o.path_id: o for o in env.objects}
        changed = 0
        for o in env.objects:
            if o.type.name != 'MonoBehaviour':
                continue
            try:
                t = o.read_typetree()
            except Exception:   # a script type UnityPy cannot read: not a text
                continue
            if not isinstance(t, dict) or not isinstance(t.get('m_text'), str):
                continue
            letter = t['m_text'].strip()
            if letter not in BUTTON_GLYPHS or t.get('m_fontAsset', {}).get('m_PathID') != bold:
                continue
            go = objs.get(t.get('m_GameObject', {}).get('m_PathID'))
            if not go or go.read_typetree().get('m_Name') not in NAMES:
                continue
            t['m_text'] = t['m_text'].replace(letter, chr(BUTTON_GLYPHS[letter]))
            o.save_typetree(t)
            changed += 1
        if changed:
            out = mods / a.name / 'romfs' / p
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(env.file.save())
            print(f'{p}: {changed} button letters')
            total += changed
    print(f'{total} button letters point at the kept game glyphs (U+E000..U+E003)')


if __name__ == '__main__':
    main()
