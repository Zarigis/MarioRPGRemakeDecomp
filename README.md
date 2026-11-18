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

## Enhancements and mods

Changes the port makes to the game, beyond running it. F1 or Esc (Minus and Plus together on a controller) opens the
settings menu; the rest are `mrpg.ini` keys, documented in [mrpg.ini.example](mrpg.ini.example).

**Picture**

- **Resolution up to 8K.** The game draws at the size you choose, from 1280 × 720 through 1440p and 4K (3840 × 2160) to
  7680 × 4320. A size above your screen's is scaled down to it, which smooths jagged edges.
- **Scaling and shape.** When the window is larger than the game's picture, AMD FSR 1 (with a sharpness setting) or
  bilinear scaling; when its shape differs, black bars or stretching.
- **Sharper shadows**, with shadow maps up to 4 times the game's size on each side.
- **FXAA** anti-aliasing and **anisotropic filtering**.
- **HDR output**, its brightest highlights capped at what Windows reports for the display, and a **colour profile**
  (brightness, contrast, saturation, gamma) that applies in SDR and HDR.
- **Sharper enlarged UI sprites** above 1080p.

**Frame rate**

- **A frame limit from 30 to 240 fps**, or the display's refresh rate. The game's battles and the mini games that count
  frames (the world map, the Yoshi race, the barrel and mine cart rides, ...) stay at 60 fps so they keep their speed;
  Melody Bay at Tadpole Pond steps by time and runs at the limit.

**Mods tab**

- **Camera on the right stick.** Orbit around Mario, raise and lower the camera, or zoom with ZL held; clicking the
  stick puts it back. The fog moves back with the zoom. Battles and the world map keep the game's camera.
- **No gauge moves.** Battles as in the original game: no gauge, no gauge moves, no chain counter or chain bonuses, and
  the Party page without its Ally Buffs and Gauge Move panels. The Bowyer battle's scripted gauge move still works.
- **Free movement direction:** Mario walks the way the stick points, instead of the game turning a direction near
  either of the room's axes onto that axis.
- **Background around rooms** in the Super Nintendo version's blue instead of the remake's grey, where the camera sees
  past a room's edge.
- **Text colours** for a font mod with outlines (below): the dialogue's text and outline, and the menus' light blue text
  with its dark blue outline, as on the Super Nintendo.
- **Installed mods:** each folder in the `mods` folder next to `mrpg.exe` (one folder per mod, holding its `romfs`
  folder, as emulators take them) can be switched on and off and ordered.

**Controls**

- **Walking speed follows the stick's tilt**, with an adjustable movement dead zone.

**Optional mods built from your game files** (written into the `mods` folder; nothing of the game is in this
repository)

- **A font in the Super Nintendo's spirit:** [Parchment Hand](tools/parchment_font/), an original hand-lettered font
  (its own source and BSD 3-Clause licence in that folder), put into the game's three text fonts by
  [tools/font_mod.py](tools/font_mod.py), which takes any TrueType font. With `--outline` the letters get an outline
  that the port colours by the text: light around dark text, dark around light text.
- **A parchment dialogue box:** [tools/dialog_box_mod.py](tools/dialog_box_mod.py) redraws the box as Super
  Nintendo-style mottled parchment, with square corners and uneven edges, or recolours the game's own.

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
