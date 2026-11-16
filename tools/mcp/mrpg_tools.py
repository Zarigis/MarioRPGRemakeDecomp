"""The tools of the MCP server (mrpg_mcp.py loads this file again whenever it changes).

They talk to the game's control port (runtime/control.c, MRPG_CONTROL=<port>): one connection per command, one line
each way. The game is its own process, started detached by game_start, so it outlives a reload of this file and a
restart of the server; nothing is kept here between calls but what is on disk under build/mcp.

Every tool takes `instance` (default "main"). The main instance runs build/<version>/mrpg.exe with the default profile.
Any other name is a game of its own in build/<name>/: a copy of the build made by game_start (again with
refresh_build), its own saves in build/<name>/profile, its own mrpg.ini and caches beside the exe, and its own control
port, so it keeps running while the main build is rebuilt.
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
INSTANCE = 'main'                       # the instance of the call being answered (call() sets the three)
WORK = MCP / 'main'                     # its frames, the log of its game, its process id
PORT = BASE_PORT


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
        s = socket.create_connection(('127.0.0.1', PORT), timeout=1)
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
    env = dict(os.environ, MRPG_CONTROL=str(PORT), MRPG_ASSUME_FOCUS='1')
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
    return [text(f'started {exe} (process {p.pid}, log {WORK / "game.log"}): ' + describe(r))]


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
    tool('game_start', 'Start the game with its control port open. One game per instance.', {
        'paused': {'type': 'boolean', 'description': 'Pause as soon as the port is up (default false).'},
        'rebuild': {'type': 'boolean', 'description': 'Run tools/build_game.py first (default false).'},
        'refresh_build': {'type': 'boolean', 'description': 'For an instance other than main: copy the current build '
                          'into its folder again before starting (default: only when it has none yet).'},
        'background': {'type': 'boolean', 'description': 'Keep the window behind other windows (default true).'},
        'real_input': {'type': 'boolean', 'description': 'Also read the keyboard, mouse and gamepad (default false).'},
        'env': {'type': 'object', 'description': 'Extra MRPG_* settings, for example {"MRPG_TRACE": "fs"}.'},
        'args': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Extra arguments for mrpg.exe.'},
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
    return fn(args)
