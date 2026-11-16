"""Where a managed method's code is in the game's `main` module: joins the metadata names (il2cpp_meta.py) with the
method pointer tables IL2CPP compiled into the executable.

    .venv/Scripts/python tools/il2cpp_bin.py build/extracted/v101/exefs/main build/re/global-metadata.dat \
        GlobalWork.change_coin GlobalWork.get_inst

prints each method's offset in `main` (add the module base, 0x7000000000 for main, for its address in the running
game). A name is `Type.method` or `Type.method/<parameter count>` when overloads differ in it; Type is the full name
with its namespace. Only methods of Assembly-CSharp.dll, the game's own code, unless --image names another module.

How it finds them: every IL2CPP module has an Il2CppCodeGenModule {name, method count, method pointers, ...} whose
pointers are indexed by the row of the method's metadata token, from 1. The module is the structure whose first word
points at its file name.
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recomp'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from il2cpp_meta import Metadata  # noqa: E402
from nso import Nso  # noqa: E402

R_AARCH64_RELATIVE = 1027


class Il2CppBinary:
    def __init__(self, main_path, metadata_path):
        self.nso = Nso(str(main_path))
        self.meta = Metadata(metadata_path)
        # image offset -> the offset it points to, for every pointer the loader relocates
        self.ptr = {r[0]: r[3] for r in self.nso.relocs if r[1] == R_AARCH64_RELATIVE}
        self._modules = {}

    def module(self, image):
        """(method count, offset of the method pointer table) of the code generation module named image."""
        if image not in self._modules:
            img = self.nso.image
            name = img.find(image.encode() + b'\0')
            while name >= 0 and img[name - 1] != 0:   # a longer name ending the same way
                name = img.find(image.encode() + b'\0', name + 1)
            if name < 0:
                raise LookupError(f'no module named {image}')
            at = [o for o, t in self.ptr.items() if t == name and o + 16 in self.ptr]
            if len(at) != 1:
                raise LookupError(f'{len(at)} candidates for the code generation module of {image}')
            self._modules[image] = (struct.unpack_from('<Q', img, at[0] + 8)[0], self.ptr[at[0] + 16])
        return self._modules[image]

    def method(self, spec, image='Assembly-CSharp.dll'):
        """The offset in main of `Type.method[/params]`."""
        type_name, _, rest = spec.rpartition('.')
        name, _, params = rest.partition('/')
        found = [(t, m) for t in self.meta.find(type_name) if t.image == image for m in t.methods
                 if m.name == name and (not params or m.params == int(params))]
        if len(found) != 1:
            raise LookupError(f'{spec}: {len(found)} methods match'
                              + (': ' + ', '.join(f'{m.name}/{m.params}' for _, m in found) if found else ''))
        count, table = self.module(image)
        row = found[0][1].token & 0xFFFFFF
        if not 1 <= row <= count:
            raise LookupError(f'{spec}: token row {row} outside the module\'s {count} methods')
        return self.ptr.get(table + 8 * (row - 1), 0)   # 0: no code (abstract, or removed by the linker)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('main', type=Path)
    ap.add_argument('metadata', type=Path)
    ap.add_argument('methods', nargs='+')
    ap.add_argument('--image', default='Assembly-CSharp.dll')
    a = ap.parse_args()
    b = Il2CppBinary(a.main, a.metadata)
    for spec in a.methods:
        print(f'{spec} main+{b.method(spec, a.image):#x}')


if __name__ == '__main__':
    main()
