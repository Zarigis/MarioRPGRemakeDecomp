"""Reads an IL2CPP global-metadata.dat (version 29, Unity 2021.3): the names of the game's managed types, fields and
methods. With --dump it writes one text file listing them, for finding where the game keeps something.

    python tools/il2cpp_meta.py build/re/global-metadata.dat --dump build/re/types.txt

The metadata is game content: its copies and dumps stay under build/ (AGENTS.md, "Game content boundary").
As a module: Metadata(path) gives .types (TypeDef), each with its fields and methods; il2cpp_bin.py joins them with the
field offsets and method addresses in the executable.
"""
import argparse
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC, VERSION = 0xFAB11BAF, 29
# (offset, size) pairs of the header after magic and version, in this order (libil2cpp il2cpp-metadata.h,
# Il2CppGlobalMetadataHeader); only the ones read here are named
SECTIONS = ['string_literal', 'string_literal_data', 'string', 'events', 'properties', 'methods',
            'parameter_default_values', 'field_default_values', 'field_and_parameter_default_value_data',
            'field_marshaled_sizes', 'parameters', 'fields', 'generic_parameters', 'generic_parameter_constraints',
            'generic_containers', 'nested_types', 'interfaces', 'vtable_methods', 'interface_offsets',
            'type_definitions', 'images', 'assemblies']
TYPE_DEF = struct.Struct('<7iI8i8HII')    # Il2CppTypeDefinition, 88 bytes
METHOD_DEF = struct.Struct('<5iI4H')      # Il2CppMethodDefinition, 32 bytes
FIELD_DEF = struct.Struct('<iiI')         # Il2CppFieldDefinition, 12 bytes
IMAGE_DEF = struct.Struct('<iiiiiiiIii')  # Il2CppImageDefinition, 40 bytes


@dataclass
class Method:
    name: str
    token: int        # 0x06xxxxxx: the row is the index into its module's method pointers, from 1
    flags: int
    params: int

    @property
    def static(self):
        return bool(self.flags & 0x10)


@dataclass
class Field:
    name: str
    type_index: int   # into the executable's Il2CppType table
    token: int


@dataclass
class TypeDef:
    index: int
    name: str
    namespace: str
    image: str = ''
    parent_type: int = -1      # an Il2CppType index, not a type definition index
    declaring_type: int = -1
    byval_type: int = -1
    flags: int = 0
    fields: list = field(default_factory=list)
    methods: list = field(default_factory=list)

    @property
    def full(self):
        return f'{self.namespace}.{self.name}' if self.namespace else self.name


class Metadata:
    def __init__(self, path):
        d = self.data = Path(path).read_bytes()
        magic, version = struct.unpack_from('<Ii', d, 0)
        if magic != MAGIC or version != VERSION:
            raise ValueError(f'{path}: magic {magic:#x} version {version}, expected {MAGIC:#x} version {VERSION}')
        pairs = struct.unpack_from(f'<{2 * len(SECTIONS)}i', d, 8)
        self.sec = {n: (pairs[2 * i], pairs[2 * i + 1]) for i, n in enumerate(SECTIONS)}
        self._str0 = self.sec['string'][0]
        methods = self._rows('methods', METHOD_DEF)
        fields = self._rows('fields', FIELD_DEF)
        self.types = []
        for i, t in enumerate(self._rows('type_definitions', TYPE_DEF)):
            (name, ns, byval, declaring, parent, _elem, _gc, flags, f0, m0, _e0, _p0, _n0, _i0, _v0, _o0,
             nm, _np, nf, *_rest) = t
            td = TypeDef(i, self.string(name), self.string(ns), parent_type=parent, declaring_type=declaring,
                         byval_type=byval, flags=flags)
            td.fields = [Field(self.string(fields[k][0]), fields[k][1], fields[k][2]) for k in range(f0, f0 + nf)]
            td.methods = [Method(self.string(methods[k][0]), methods[k][5], methods[k][6], methods[k][9])
                          for k in range(m0, m0 + nm)]
            self.types.append(td)
        self.images = []
        for im in self._rows('images', IMAGE_DEF):
            name = self.string(im[0])
            self.images.append((name, im[2], im[3]))
            for t in self.types[im[2]:im[2] + im[3]]:
                t.image = name

    def _rows(self, section, st):
        off, size = self.sec[section]
        return [st.unpack_from(self.data, off + i * st.size) for i in range(size // st.size)]

    def string(self, index):
        a = self._str0 + index
        return self.data[a:self.data.index(b'\0', a)].decode('utf-8', 'replace')

    def find(self, full_name):
        """The type definitions with this full name (several images may define one)."""
        return [t for t in self.types if t.full == full_name]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('metadata', type=Path)
    ap.add_argument('--dump', type=Path, help='write every type with its fields and methods to this text file')
    a = ap.parse_args()
    m = Metadata(a.metadata)
    print(f'{len(m.types)} types in {len(m.images)} images')
    if a.dump:
        with open(a.dump, 'w', encoding='utf-8') as f:
            for t in m.types:
                f.write(f'type {t.index} {t.image} {t.full} parent_type={t.parent_type}\n')
                for x in t.fields:
                    f.write(f'  field {x.name} type={x.type_index}\n')
                for x in t.methods:
                    f.write(f'  method {x.name}/{x.params} token={x.token:#x}{" static" if x.static else ""}\n')
        print(f'wrote {a.dump}')


if __name__ == '__main__':
    main()
