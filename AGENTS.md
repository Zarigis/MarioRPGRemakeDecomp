# Super Mario RPG Recomp

Static recompilation of *Super Mario RPG* (Switch, ARM64, Unity 2021.3 IL2CPP, title `0100BC0018138000`, version 1.0.1
= `v101`) into a native Windows x86-64 exe with a Vulkan renderer. The repository started as a copy of TotK Recomp
(README, "Origin"): `docs/` and the comments that say TotK still describe that game. Design of the shared parts:
[docs/architecture.md](docs/architecture.md). Toolchain, build commands and tests: [docs/building.md](docs/building.md),
with `v101` as the version.

What differs from the TotK code base, and why:

- The game is a Unity player. The SDK boundary is wider (`runtime/ov_unity.c`, the additions at the end of
  `runtime/ov_input.c` and `runtime/fs_host.c`): one offline console, one user, no network.
- `main` defines `malloc`, `free` and `operator new`/`delete`; the loader binds names in Horizon's load order so they
  replace the SDK's (`runtime/loader.c`, `resolve`).
- IL2CPP's garbage collector pauses threads and reads their registers (SVC 0x32, 0x33 in `runtime/kernel.c`). A paused
  thread stops only where its guest registers are all in the `Cpu`.
- IL2CPP throws C++ exceptions. The lifted SDK unwinder does the work; its final jump is a non-local exit
  (`rt_nonlocal`, `c->unwind`, and `unwound()` in `recomp/gen.py`).
- No patch sets, no TotK-specific addresses: files such as `runtime/frame_rate.c`, `runtime/resolution.c`,
  `runtime/mouse_direct.c` and `recomp/patches-*.txt` are inert leftovers until they are ported or removed.

## Game content boundary

This repository is public. Game data lives outside it and every derived file stays in ignored folders.

- The user's game and key paths are in `config.local.toml` (ignored). Pass the keys file path to tools; the tools read it themselves. Key values stay out of your output, logs, commands and files.
- Everything extracted or generated goes under `build/` or `generated/`.
- Every file the code generator emits carries the marker defined as `GENERATED_MARKER` in `tools/check_content.py`.
- Run `python tools/check_content.py --staged` before proposing a commit. It is the same check CI runs.

## Reusing code

`refs/` holds the upstream checkouts (`tools/fetch_refs.sh` recreates it). Read-only.

- Copy only MIT, BSD, ISC, zlib or Apache-2.0 code, keep its header, and add a row to `THIRD_PARTY_NOTICES.md`.
- yuzu, suyu, OpenSmash-Ultimate and other GPL code: read for behaviour, write our own.
- `tools/vendor/` stays byte-identical to upstream, with one exception: the title IDs in `tools/vendor/macnativegames/extract_exefs.py` are this game's. Windows changes go in `tools/extract.py`.

## Code

- Build C with MSYS2 UCRT64 Clang (`C:\msys64\ucrt64\bin`). Generated C uses GNU extensions, so `cl.exe` is out. Call Ninja from that directory by full path or put it first on PATH.
- Two Python environments: `.venv` (3.12) for the lifter and the build, `.venv-py314` for the extraction and shader scripts, which need `compression.zstd`.
- Generated C is never edited by hand: change the generator (`recomp/`).
- Every lifter change passes the differential tests against Unicorn ([docs/building.md](docs/building.md), "Checks"). After changing `recomp/jumptables.py`, `tests\jumptables_check.py` reports 0 disagreements on 1.2.1 and 1.4.3.
- `recomp/layout.py` alone decides module bases.
- Graphics bugs: [docs/maxwell.md](docs/maxwell.md) lists the Maxwell behaviour the Vulkan path must match and the TotK bugs other ports fixed.
- Comments say what the code does and why, in words that stand on their own. Cite our code by file plus function (a line number may follow as a hint) and upstream code by project, file and function: `refs/` moves, so its line numbers rot. Commit hashes belong to the attribution of copied code.

## Running and debugging

- Running the game, screenshots, frame dumps, timings: [docs/agents/running.md](docs/agents/running.md).
- Investigating a bug, glitch or crash: search [docs/agents/symptoms.md](docs/agents/symptoms.md) by the player's words first, then follow [docs/agents/debugging.md](docs/agents/debugging.md). Read the code before running the game.

## Pull requests

Preparing a pull request: target `dev`; the checks by changed area, the proof and the performance runs it carries are in [CONTRIBUTING.md](CONTRIBUTING.md), "Pull requests". Reviewing one: [docs/pr-review-kit/](docs/pr-review-kit/).

## Writing

Code, comments, docs and commit messages are in English. Commit messages are plain sentences without type prefixes.
