"""The tools of the MCP server (mrpg_mcp.py loads this file again whenever it changes).

They talk to the game's control port (runtime/control.c, MRPG_CONTROL=<port>): one connection per command, one line
each way. The game is its own process, started detached by game_start, so it outlives a reload of this file and a
restart of the server; nothing is kept here between calls but what is on disk under build/mcp.

Every tool takes `instance` (default "main"). The main instance runs build/<version>/mrpg.exe with the default profile.
Any other name is a game of its own in build/<name>/: a copy of the build made by game_start (again with
refresh_build), its own saves in build/<name>/profile, its own mrpg.ini and caches beside the exe, and its own control
port, so it keeps running while the main build is rebuilt.

Every game_start begins a session, a folder build/mcp/<instance>/sessions/<time>/ that makes the run repeatable:
  save-start/   the committed save data as it was before the game started (and mrpg.ini, when there is one)
  input.txt     every input the game saw, written by the game itself as it plays (MRPG_INPUT_RECORD: lines of
                "<tick> <button> <hold>", ticks being frames of game time, so pauses between turns leave no trace)
  log.jsonl     every tool call with its arguments and what it answered, cheats included, in order
  session.json  the build, the arguments and settings of the start
game_start with `replay` set to such a folder puts save-start back and plays input.txt (MRPG_INPUT_SCRIPT).
"""
import base64
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

class ToolError(Exception):
    """A failure the caller can act on: shown as the message alone."""


ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / 'build' / 'mcp'
BASE_PORT = int(os.environ.get('MRPG_MCP_PORT', '47800'))
# The instance of the call being answered (call() sets the three): its name, its folder for frames, the game's log
# and process id, and its port. A reload of this file while a call waits on the game (the server's watcher does that)
# runs these lines again in the same module, so they keep what is set: reset to main, a long turn of another instance
# came back with main's port and picture.
INSTANCE = globals().get('INSTANCE', 'main')
WORK = globals().get('WORK', MCP / 'main')
PORT = globals().get('PORT', BASE_PORT)


def use_instance(name):
    """Makes `name` the instance the helpers below talk to. Ports are handed out once and kept in instances.json."""
    global INSTANCE, WORK, PORT
    if not re.fullmatch(r'[a-z0-9_-]{1,32}', name) or name in ('mcp', 'xlate', 'extracted', 'profile', 'logs'):
        raise ToolError('instance is a short lower-case name (letters, digits, - and _)')
    reg = MCP / 'instances.json'
    ports = json.loads(reg.read_text()) if reg.exists() else {}
    if name != 'main' and name not in ports:
        ports[name] = max([BASE_PORT] + list(ports.values())) + 1
        MCP.mkdir(parents=True, exist_ok=True)
        reg.write_text(json.dumps(ports, indent=1))
    INSTANCE, WORK, PORT = name, MCP / name, BASE_PORT if name == 'main' else ports[name]


def instance_dir(version):
    return ROOT / 'build' / (version if INSTANCE == 'main' else INSTANCE)


def profile_dir(version):
    """Where the instance's saves are: the runtime's default for main, a folder of its own for the others."""
    return ROOT / 'build' / 'profile' if INSTANCE == 'main' else instance_dir(version) / 'profile'


def session_dir():
    p = WORK / 'session.txt'
    d = Path(p.read_text().strip()) if p.exists() else None
    return d if d and d.is_dir() else None


def session_log(name, args, content):
    d = session_dir()
    if not d or name in ('game_log', 'game_frames'):
        return
    said = ' | '.join(c['text'] for c in content if c.get('type') == 'text')
    with open(d / 'log.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'time': time.strftime('%H:%M:%S'), 'tool': name, 'args': args, 'result': said[:600]}) + '\n')


def session_begin(version, exe, args, extra_env, replay):
    """A new session folder with the save as it is now; the settings that record (or replay) the input."""
    d = WORK / 'sessions' / time.strftime('%Y%m%d-%H%M%S')
    d.mkdir(parents=True)
    prof = profile_dir(version)
    if replay:
        src = Path(replay)
        if not (src / 'input.txt').exists():
            raise ToolError(f'{src} has no input.txt: not a session folder')
        if (prof / 'save').exists():   # the save in use is kept, then replaced by the session's
            shutil.copytree(prof / 'save', d / 'save-before-replay')
            shutil.rmtree(prof / 'save')
        for tx in ('save-tx',):        # an unfinished commit would win over the restored save
            shutil.rmtree(prof / tx, ignore_errors=True)
        if (src / 'save-start' / 'save').exists():
            shutil.copytree(src / 'save-start' / 'save', prof / 'save')
    (d / 'save-start').mkdir()
    if (prof / 'save').exists():
        shutil.copytree(prof / 'save', d / 'save-start' / 'save')
    if (exe.parent / 'mrpg.ini').exists():
        shutil.copy2(exe.parent / 'mrpg.ini', d / 'save-start' / 'mrpg.ini')
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    (d / 'session.json').write_text(json.dumps({
        'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'instance': INSTANCE, 'exe': str(exe),
        'exe_modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exe.stat().st_mtime)), 'commit': head,
        'args': args, 'env': extra_env, 'replay_of': str(replay) if replay else None}, indent=1))
    (WORK / 'session.txt').write_text(str(d))
    env = {'MRPG_INPUT_RECORD': str(d / 'input.txt')}
    if replay:
        env['MRPG_INPUT_SCRIPT'] = str(Path(replay) / 'input.txt')
    return d, env


def copy_build(version):
    """The build's exe, libraries and caches into the instance's folder; its saves and mrpg.ini are left alone."""
    src, dst = ROOT / 'build' / version, ROOT / 'build' / INSTANCE
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and (f.suffix in ('.exe', '.dll', '.bin', '.map') or f.name == 'mrpg') and not f.name.startswith('totk'):
            shutil.copy2(f, dst / f.name)
    if (src / 'shader-cache').is_dir():
        shutil.copytree(src / 'shader-cache', dst / 'shader-cache', dirs_exist_ok=True)
BUTTONS = ['A', 'B', 'X', 'Y', 'LCLICK', 'RCLICK', 'L', 'R', 'ZL', 'ZR', 'PLUS', 'MINUS', 'LEFT', 'UP', 'RIGHT',
           'DOWN']                      # bit numbers: runtime/input_map.h B_A..B_DOWN


def command(line, timeout=5.0):
    try:
        s = socket.create_connection(('127.0.0.1', PORT), timeout=3)
    except OSError:   # refused, or on Windows no answer at all from a closed port
        raise ToolError(f'no game is listening on port {PORT}: start one with game_start') from None
    try:
        with s:
            s.settimeout(timeout)
            s.sendall((line + '\n').encode())
            data = b''
            while not data.endswith(b'\n'):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
    except socket.timeout:
        raise ToolError(f'the game did not answer "{line.split()[0]}" within {timeout:.0f} s') from None
    r = json.loads(data.decode() or '{"ok":0,"error":"empty reply"}')
    if not r.get('ok'):
        raise ToolError(r.get('error', 'the game refused the command'))
    return r


def running():
    try:
        socket.create_connection(('127.0.0.1', PORT), timeout=0.3).close()
        return True
    except OSError:
        return False


def text(s):
    return {'type': 'text', 'text': s}


def image(path):
    """A PNG file as MCP image content. The game writes PNGs uncompressed; with Pillow they are packed first."""
    data = Path(path).read_bytes()
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert('RGB').save(buf, 'PNG', optimize=True)
        data = buf.getvalue()
    except ImportError:
        pass
    return {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode()}


def describe(r):
    s = f"{r['state']} at frame {r['frame']}"
    if r['state'] == 'turn':
        s += f" (step {r['step'] + 1} of {r['steps']}, {r['frames_left']} frames left in it)"
    if r.get('forced'):
        s += '; paused without a present (the game was not presenting), so there is no new picture'
    if r.get('record_every'):
        s += f"; recording every {r['record_every']} frame(s), {r['recorded']} written"
    return s


def height(width):
    return width * 9 // 16


def shot(width):
    """The frame kept at the last pause (or the next present while running), as an image."""
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / 'shot.png'
    r = command(f'shot {width} {height(width)} {path.as_posix()}', timeout=10)
    return r, image(path)


def sheet(files, max_images, columns):
    """Recorded frames as contact sheets with the frame number on each tile; plain images without Pillow."""
    if not files:
        return []
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        step = max(1, -(-len(files) // max_images))
        return [image(f) for f in files[::step]]
    per = columns * columns
    if len(files) > per * max_images:   # too many for the sheets: an even sample, always with the last frame
        step = -(-len(files) // (per * max_images))
        files = files[::step] + ([files[-1]] if (len(files) - 1) % step else [])
    out = []
    for i in range(0, len(files), per):
        tiles = [Image.open(f).convert('RGB') for f in files[i:i + per]]
        w, h = tiles[0].size
        rows = -(-len(tiles) // columns)
        im = Image.new('RGB', (w * min(columns, len(tiles)), h * rows))
        d = ImageDraw.Draw(im)
        for k, t in enumerate(tiles):
            x, y = k % columns * w, k // columns * h
            im.paste(t, (x, y))
            label = str(int(Path(files[i + k]).stem[1:]))
            d.rectangle((x, y, x + 8 * len(label) + 6, y + 14), fill=(0, 0, 0))
            d.text((x + 3, y + 1), label, fill=(255, 255, 0))
        buf = io.BytesIO()
        im.save(buf, 'PNG')
        out.append({'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(buf.getvalue()).decode()})
    return out


def recorded(directory, first=None, last=None):
    files = sorted(Path(directory).glob('f*.png'))
    return [f for f in files if (first is None or int(f.stem[1:]) >= first) and (last is None or int(f.stem[1:]) <= last)]


# ---- tools

def game_start(a):
    if running():
        raise ToolError(f'a game is already listening on port {PORT}: ' + describe(command('status')))
    version = a.get('version', 'v101')
    exe = instance_dir(version) / ('mrpg.exe' if os.name == 'nt' else 'mrpg')
    if a.get('rebuild'):
        py = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        b = subprocess.run([str(py), 'tools/build_game.py', '--version', version], cwd=ROOT, capture_output=True, text=True)
        if b.returncode:
            raise ToolError('the build failed:\n' + (b.stdout + b.stderr)[-3000:])
    if INSTANCE != 'main' and (a.get('refresh_build') or not exe.exists()):
        copy_build(version)
    if not exe.exists():
        raise ToolError(f'{exe} does not exist: build it first (rebuild: true)')
    args = list(a.get('args') or [])
    if INSTANCE != 'main':
        args = ['--profile', str(exe.parent / 'profile')] + args
    WORK.mkdir(parents=True, exist_ok=True)
    session, session_env = session_begin(version, exe, args, a.get('env') or {}, a.get('replay'))
    env = dict(os.environ, MRPG_CONTROL=str(PORT), MRPG_ASSUME_FOCUS='1', **session_env)
    if a.get('background', True):
        env['MRPG_BACKGROUND_WINDOW'] = '1'
    if not a.get('real_input', False):
        env['MRPG_INPUT'] = 'none'
    env.update({k: str(v) for k, v in (a.get('env') or {}).items()})
    log = open(WORK / 'game.log', 'wb')
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
    p = subprocess.Popen([str(exe)] + args, cwd=exe.parent, env=env, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != 'nt')
    (WORK / 'game.pid').write_text(str(p.pid))
    end = time.time() + 60
    while not running():
        if p.poll() is not None:
            raise ToolError(f'the game ended with code {p.returncode} before its control port opened; see game_log')
        if time.time() > end:
            raise ToolError('the control port did not open within 60 s; see game_log')
        time.sleep(0.2)
    r = command('pause 100') if a.get('paused') else command('status')
    return [text(f'started {exe} (process {p.pid}, log {WORK / "game.log"}, session {session}'
                 + (f', replaying {a["replay"]}' if a.get('replay') else '') + '): ' + describe(r))]


def game_stop(a):
    if running():
        try:
            command('quit', timeout=5)
        except (ToolError, OSError, ValueError):
            pass   # the process ends before it answers
    pid = WORK / 'game.pid'
    time.sleep(0.5)
    if running() and pid.exists():
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/PID', pid.read_text().strip()], capture_output=True)
        else:
            os.kill(int(pid.read_text()), 9)
    return [text('stopped' if not running() else 'the game is still listening: it was not started by this server')]


def game_status(a):
    return [text(describe(command('status')))]


def game_pause(a):
    r = command('pause 2000', timeout=10)
    out = [text(describe(r))]
    if a.get('screenshot', True) and not r.get('forced'):
        out.append(shot(a.get('width', 640))[1])
    return out


def game_resume(a):
    return [text(describe(command('resume')))]


def game_screenshot(a):
    r, im = shot(a.get('width', 640))
    return [text(f"frame {r['shot_frame']} ({describe(r)})"), im]


def game_wait(a):
    t = float(a.get('timeout_s', 30))
    r = command(f'wait {int(t * 1000)}', timeout=t + 5)
    out = [text(describe(r))]
    if r['state'] == 'paused' and a.get('screenshot', True) and not r.get('forced'):
        out.append(shot(a.get('width', 640))[1])
    return out


def step_line(s):
    bits = 0
    for b in s.get('buttons') or []:
        if b.upper() not in BUTTONS:
            raise ToolError(f'unknown button {b}: one of {" ".join(BUTTONS)}')
        bits |= 1 << BUTTONS.index(b.upper())
    axes = [max(-32767, min(32767, round(float(v) * 32767))) for v in (s.get('lstick') or [0, 0]) + (s.get('rstick') or [0, 0])]
    frames = int(s.get('frames', 1))
    if frames < 1 or len(axes) != 4:
        raise ToolError('a step needs frames of 1 or more and sticks as [x, y]')
    return f'{frames} {bits:x} ' + ' '.join(map(str, axes))


def game_turn(a):
    steps = a.get('steps') or []
    if not steps:
        raise ToolError('steps is empty')
    every = int(a.get('record_every', 0))
    rec_dir = None
    if every:
        before = command('status')
        rec_dir = WORK / 'rec' / f"turn-{before['turns'] + 1:04d}"
        rec_dir.mkdir(parents=True, exist_ok=True)
        for f in rec_dir.glob('f*.png'):
            f.unlink()
        w = int(a.get('record_width', 320))
        command(f'record {every} {w} {height(w)} {rec_dir.as_posix()}')
    t = float(a.get('timeout_s', 60))
    try:
        r = command(f'turn {int(t * 1000)} {len(steps)} ' + ' '.join(step_line(s) for s in steps), timeout=t + 5)
    finally:
        if every and command('status')['state'] == 'paused':
            command('record 0')
    total = sum(int(s.get('frames', 1)) for s in steps)
    if not r.get('done'):
        return [text(f'the turn of {total} frames has not ended after {t:.0f} s: {describe(r)}. It goes on and pauses '
                     'when done (game_wait); recording, if any, stays on until then (game_record every 0 ends it).')]
    out = [text(f'turn of {total} frames done: ' + describe(r))]
    if rec_dir:
        files = recorded(rec_dir)
        out.append(text(f'{len(files)} frames recorded in {rec_dir} (every {every}); numbers on the tiles are frames'))
        out += sheet(files, int(a.get('max_sheets', 2)), int(a.get('sheet_columns', 4)))
    if a.get('screenshot', True) and not r.get('forced'):
        out.append(shot(a.get('width', 640))[1])
    return out


def game_record(a):
    every = int(a.get('every', 1))
    if not every:
        return [text(describe(command('record 0')))]
    d = Path(a['dir']) if a.get('dir') else WORK / 'rec' / time.strftime('run-%H%M%S')
    d.mkdir(parents=True, exist_ok=True)
    w = int(a.get('width', 320))
    r = command(f'record {every} {w} {height(w)} {d.as_posix()}')
    return [text(f'recording into {d}: ' + describe(r))]


def game_frames(a):
    d = Path(a['dir'])
    files = recorded(d, a.get('first'), a.get('last'))
    if not files:
        raise ToolError(f'no recorded frames in {d} in that range')
    return [text(f'{len(files)} frames, {int(files[0].stem[1:])} to {int(files[-1].stem[1:])}')] + \
        sheet(files, int(a.get('max_sheets', 2)), int(a.get('sheet_columns', 4)))


def game_log(a):
    p = WORK / 'game.log'
    if not p.exists():
        raise ToolError(f'{p} does not exist: no game was started by this server')
    lines = p.read_text(errors='replace').splitlines()
    if a.get('grep'):
        lines = [x for x in lines if a['grep'].lower() in x.lower()]
    return [text('\n'.join(x[:300] for x in lines[-int(a.get('lines', 40)):]) or '(nothing)')]


def game_command(a):
    return [text(json.dumps(command(a['command'], timeout=float(a.get('timeout_s', 10)))))]


INSTANCE_ARG = {'type': 'string', 'description': 'Which game: "main" (default) is build/<version>; any other name is '
                'a separate copy in build/<name> with its own saves, settings and control port.'}


# ---- cheats: the game's own state, read and written through the control port's peek and poke
#
# Where the state lives in version 1.0.1, read off the game's code (tools/il2cpp_bin.py gives the methods' places):
# GlobalWork.get_inst (main+0x1886a00) loads the class through the pointer at main+0x3a58048, its static fields at
# class+0xb8, and the instance from the first of them. GlobalWork.change_coin, heal_at_inn and player_recovery
# (main+0x188af30, +0x188be90, +0x188bd80) show the rest: the save data object at instance+0x130; in it the player
# array at +0x38 (count at array+0x18, elements from +0x20), flower points and their maximum at +0x50 and +0x54, coins
# at +0x58 with 9999 as the most. A player's hit points are at +0x24 and are healed to the sum of the two ints at +0x28
# and +0x2c (the routine at main+0x1c18a60).
MAIN_BASE = 0x7000000000
GLOBAL_WORK_CLASS_REF = 0x3a58048
COIN_MAX = 9999
NAMES = ['', 'Mario', 'Mallow', 'Geno', 'Bowser', 'Peach']   # the player array's order; entry 0 is an unused player
# (Mario's place checked against the screen; the others by their starting hit points 20, 45, 80, 50)


def peek(addr, n):
    return bytes.fromhex(command(f'peek {addr:x} {n}')['hex'])


def u64(addr):
    return int.from_bytes(peek(addr, 8), 'little')


def i32s(addr, n):
    d = peek(addr, 4 * n)
    return [int.from_bytes(d[4 * i:4 * i + 4], 'little', signed=True) for i in range(n)]


def poke_i32(addr, v):
    command(f'poke {addr:x} {int(v).to_bytes(4, "little", signed=True).hex()}')


def game_state():
    """(save data address, [(player address, hp, max hp)]) or a ToolError while the game has no state yet."""
    def follow(addr, what):
        try:
            p = u64(addr)
        except ToolError:
            p = 0
        if p < 0x10000 or p & 7:   # not set up yet: null, or the metadata token IL2CPP keeps there until first use
            raise ToolError(f'the game has not set up its state yet ({what}): cheats work once a game is loaded')
        return p
    klass = follow(follow(MAIN_BASE + GLOBAL_WORK_CLASS_REF, 'class reference'), 'class')
    save = follow(follow(follow(klass + 0xb8, 'static fields'), 'instance') + 0x130, 'save data')
    arr = follow(save + 0x38, 'players')
    count = i32s(arr + 0x18, 1)[0]
    if not 0 < count <= 16:
        raise ToolError(f'the player array has {count} entries: not the layout this tool knows (version 1.0.1)')
    players = []
    for i in range(count):
        p = u64(arr + 0x20 + 8 * i)
        hp, base, bonus = i32s(p + 0x24, 3) if p else (0, 0, 0)
        if p and base + bonus > 0:
            players.append((p, hp, base + bonus))
        else:
            players.append((0, 0, 0))
    return save, players


def party_text(save, players):
    fp, fp_max, coins = i32s(save + 0x50, 3)
    rows = [f'{i} {NAMES[i] if i < len(NAMES) else "?"}: HP {hp}/{mx}' for i, (p, hp, mx) in enumerate(players) if p]
    return f'coins {coins}, FP {fp}/{fp_max}\n' + '\n'.join(rows)


def game_party(a):
    return [text(party_text(*game_state()))]


def game_heal(a):
    save, players = game_state()
    who = a.get('character', 'all')
    if who == 'all':
        idx = [i for i, (p, _, _) in enumerate(players) if p]
    else:
        names = [n.lower() for n in NAMES]
        i = names.index(str(who).lower()) if who and str(who).lower() in names else int(who) if str(who).isdigit() else -1
        if not 0 <= i < len(players) or not players[i][0]:
            raise ToolError(f'no character {who}: one of {", ".join(NAMES[1:len(players)])}, an index, or "all"')
        idx = [i]
    for i in idx:
        p, _, mx = players[i]
        if not 0 < mx <= 9999:
            raise ToolError(f'character {i} has a maximum of {mx} hit points: not the layout this tool knows')
        poke_i32(p + 0x24, mx)
    if a.get('fp', True):
        fp_max = i32s(save + 0x54, 1)[0]
        if 0 < fp_max <= 999:
            poke_i32(save + 0x50, fp_max)
    return [text('healed ' + ', '.join(NAMES[i] if i < len(NAMES) else str(i) for i in idx) + '\n' + party_text(*game_state()))]


def game_coins(a):
    save, players = game_state()
    now = i32s(save + 0x58, 1)[0]
    if not 0 <= now <= COIN_MAX:
        raise ToolError(f'the coin count reads {now}: not the layout this tool knows')
    new = int(a['set']) if 'set' in a else now + int(a.get('add', 100))
    poke_i32(save + 0x58, max(0, min(COIN_MAX, new)))
    return [text(f'coins {now} -> {max(0, min(COIN_MAX, new))}')]


def tool(name, description, properties=None, required=()):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': dict(properties or {}, instance=INSTANCE_ARG),
                            'required': list(required)}}


WIDTH = {'type': 'integer', 'description': 'Picture width in pixels, 16:9 (default 640; the game renders 1920).'}
STEP = {'type': 'object', 'properties': {
    'frames': {'type': 'integer', 'description': 'How many presented frames this input is held (60 a second).'},
    'buttons': {'type': 'array', 'items': {'type': 'string', 'enum': BUTTONS}, 'description': 'Buttons held; none to wait.'},
    'lstick': {'type': 'array', 'items': {'type': 'number'}, 'description': '[x, y], each -1..1, up is +y.'},
    'rstick': {'type': 'array', 'items': {'type': 'number'}, 'description': '[x, y], each -1..1, up is +y.'}},
    'required': ['frames']}

TOOLS = [
    tool('game_start', 'Start the game with its control port open. One game per instance. Begins a session folder with the starting save and, as the game plays, a script of all its input.', {
        'paused': {'type': 'boolean', 'description': 'Pause as soon as the port is up (default false).'},
        'rebuild': {'type': 'boolean', 'description': 'Run tools/build_game.py first (default false).'},
        'refresh_build': {'type': 'boolean', 'description': 'For an instance other than main: copy the current build '
                          'into its folder again before starting (default: only when it has none yet).'},
        'background': {'type': 'boolean', 'description': 'Keep the window behind other windows (default true).'},
        'real_input': {'type': 'boolean', 'description': 'Also read the keyboard, mouse and gamepad (default false).'},
        'env': {'type': 'object', 'description': 'Extra MRPG_* settings, for example {"MRPG_TRACE": "fs"}.'},
        'args': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Extra arguments for mrpg.exe.'},
        'replay': {'type': 'string', 'description': 'A session folder (build/mcp/<instance>/sessions/<time>): put its '
                   'starting save back and play its recorded input. The save in use is kept in the new session folder.'},
        'version': {'type': 'string', 'description': 'Build folder under build/ (default v101).'}}),
    tool('game_stop', 'Save and end the game this server started.'),
    tool('game_status', 'Whether the game runs, plays a turn or is paused, and its frame number.'),
    tool('game_pause', 'Freeze the game after its next frame: all game threads and the game clock stop. Returns that frame.',
         {'screenshot': {'type': 'boolean'}, 'width': WIDTH}),
    tool('game_resume', 'Let a paused game run freely; ends a turn in progress.'),
    tool('game_turn', 'From any state: play the steps in order, each holding its buttons and sticks for a number of '
         'frames, then pause again. Returns the last frame, and with record_every the frames in between as contact sheets.', {
             'steps': {'type': 'array', 'items': STEP, 'description': 'At most 256. A step without input just waits.'},
             'record_every': {'type': 'integer', 'description': 'Record every Nth frame of the turn (1: every frame; default 0: none).'},
             'record_width': {'type': 'integer', 'description': 'Width of recorded frames (default 320).'},
             'max_sheets': {'type': 'integer', 'description': 'Contact sheets returned at most (default 2); more frames than fit are sampled evenly. All frames stay on disk.'},
             'sheet_columns': {'type': 'integer', 'description': 'Tiles per row and column of a sheet (default 4).'},
             'timeout_s': {'type': 'number', 'description': 'Give up waiting after this long (default 60); the turn itself goes on.'},
             'screenshot': {'type': 'boolean'}, 'width': WIDTH}, ['steps']),
    tool('game_wait', 'Wait until the game is paused (a turn that outlived its timeout).',
         {'timeout_s': {'type': 'number'}, 'screenshot': {'type': 'boolean'}, 'width': WIDTH}),
    tool('game_screenshot', 'The frame at the last pause, or the next frame while the game runs.', {'width': WIDTH}),
    tool('game_record', 'Record every Nth presented frame as PNG files from now on, across turns and free running, '
         'until called with every 0. For one turn only, use record_every of game_turn.', {
             'every': {'type': 'integer', 'description': '1: every frame; 0: stop recording.'},
             'width': {'type': 'integer', 'description': 'Width of the files (default 320).'},
             'dir': {'type': 'string', 'description': 'Folder; default a new one under build/mcp/rec.'}}, ['every']),
    tool('game_frames', 'Show recorded frames from a folder as contact sheets, optionally a range of frame numbers.', {
        'dir': {'type': 'string'}, 'first': {'type': 'integer'}, 'last': {'type': 'integer'},
        'max_sheets': {'type': 'integer'}, 'sheet_columns': {'type': 'integer'}}, ['dir']),
    tool('game_party', 'Cheat helper: the coins, flower points and each character\'s hit points, read from the game\'s memory.'),
    tool('game_heal', 'Cheat: set a character\'s hit points to the maximum (it does not revive anyone mid-battle animation; '
         'the screen shows it at the next update). Works paused or running, once a game is loaded.', {
             'character': {'type': 'string', 'description': '"all" (default), a name (Mario, Mallow, Geno, Bowser, Peach) or an index from game_party.'},
             'fp': {'type': 'boolean', 'description': 'Also refill the flower points (default true).'}}),
    tool('game_coins', 'Cheat: give coins (the game allows 0 to 9999).', {
        'add': {'type': 'integer', 'description': 'Coins to add, negative to take (default 100).'},
        'set': {'type': 'integer', 'description': 'Set the count instead.'}}),
    tool('game_log', 'The end of the log of the game this server started.',
         {'lines': {'type': 'integer'}, 'grep': {'type': 'string', 'description': 'Only lines containing this text.'}}),
    tool('game_command', 'Send one raw line to the control port (runtime/control.c lists the commands).',
         {'command': {'type': 'string'}, 'timeout_s': {'type': 'number'}}, ['command']),
]


def call(name, args):
    fn = globals().get(name)
    if not fn or name not in {t['name'] for t in TOOLS}:
        raise ToolError(f'unknown tool {name}')
    use_instance(args.get('instance') or 'main')
    try:
        content = fn(args)
    except ToolError as e:
        session_log(name, args, [text('ERROR: ' + str(e))])
        raise
    session_log(name, args, content)
    return content
