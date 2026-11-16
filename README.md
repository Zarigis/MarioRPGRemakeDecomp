# Super Mario RPG Recomp

A static recompilation of *Super Mario RPG* (Nintendo Switch, 2023; title `0100BC0018138000`, update 1.0.1) into a
native x86-64 Windows program: the game's ARM64 code is lifted to C, compiled, and linked with a host runtime that
stands in for the Switch's system software and translates its NVN graphics calls to Vulkan.

> [!IMPORTANT]
> **No game files are included.** You need your own legally obtained copy of the game, dumped from your own console
> (base game and the 1.0.1 update), and your console's keys. The game is built from your files on your machine, so the
> result contains the game. It is for your own use. Do not share it.

## Status

Work in progress; not playable yet. What works:

- Extraction of the code modules and the RomFS from the base NSP and the update NSP (`tools/extract.py` pieces).
- Lifting `main` (Unity 2021.3.15f1 player and the IL2CPP game code), `subsdk0` and `sdk` (NintendoSDK 14.3.1) to C:
  207,215 functions, no unsupported instruction.
- Loading, linking and running the result: the SDK starts, the module constructors run, `nnMain` starts the Unity
  player, which creates its threads, mounts the RomFS, and brings up NVN on the Vulkan back end.
- C++ exceptions and `longjmp` in lifted code, which IL2CPP needs and the code base this started from did not have.

`docs/` still describes the project this repository started from; see below.

## Origin

This repository started as a copy of [TotK Recomp](https://github.com/valentderah/totk-pc-recomp) (MIT), a static
recompilation of *Tears of the Kingdom*, at commit `d6ac995`. Its lifter, runtime, graphics back end, tools and
documentation are used here and are being adapted from a Nintendo first-party engine to a Unity game. The program and
its settings are renamed (`mrpg.exe`, `MRPG_*`, `mrpg.ini`); most of `docs/` and many code comments still describe
*Tears of the Kingdom*, which they call TotK.
What was taken from which upstream project, with its licence, is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Building

The toolchain is the one [docs/building.md](docs/building.md) lists (MSYS2 UCRT64 Clang, two Python environments,
hactool). With `config.local.toml` pointing at your files:

```powershell
.venv\Scripts\python recomp\gen.py --exefs build\extracted\v101\exefs --out generated\v101
.venv\Scripts\python tools\build_game.py --version v101
build\v101\mrpg.exe --boot     # runs the game to its first graphics call
build\v101\mrpg.exe            # runs the game
```

## License

The project's own code is under the [MIT License](LICENSE); third-party code keeps its own license
([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). The license grants nothing for Nintendo's game.

This is an independent, non-commercial fan project, not affiliated with or endorsed by Nintendo. *Super Mario RPG* and
*Nintendo Switch* are trademarks of Nintendo.
