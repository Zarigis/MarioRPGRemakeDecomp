"""MCP server for driving a running game: the part that stays connected.

It speaks MCP over stdin and stdout (JSON-RPC 2.0, one message per line) and holds no knowledge of the game. The tools
are in mrpg_tools.py next to this file, which is loaded again whenever it changes on disk: before every request, and
by a watcher every two seconds, which then tells the client that the tool list changed. So the tools can be edited
while a client stays connected; only a change to this file needs a reconnect. A version of mrpg_tools.py that does not
load is reported in the next tool result and the last good one keeps serving.

Python standard library only. Register it with the client as: python tools/mcp/mrpg_mcp.py
"""
import importlib
import json
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
IMPL = HERE / 'mrpg_tools.py'

out_lock = threading.Lock()
impl_lock = threading.Lock()
impl = None          # the loaded mrpg_tools module
impl_mtime = None
impl_error = ''      # why the newest mrpg_tools.py did not load
listed = None        # the tool list the client was last given, as JSON
notified = None      # the tool list the client was last told about with list_changed


def send(msg):
    with out_lock:
        sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))
        sys.stdout.buffer.flush()


def refresh():
    """Loads mrpg_tools.py if it changed. True when the tool list differs from the one the client has and the client
    was not told about this list yet."""
    global impl, impl_mtime, impl_error, notified
    with impl_lock:
        try:
            m = IMPL.stat().st_mtime_ns
        except OSError as e:
            impl_error = str(e)
            return False
        if m != impl_mtime:
            impl_mtime = m
            try:
                impl = importlib.reload(impl) if impl else importlib.import_module('mrpg_tools')
                impl_error = ''
            except Exception:
                impl_error = traceback.format_exc()
        if impl is None or listed is None:
            return False
        now = json.dumps(impl.TOOLS, sort_keys=True)
        if now == listed or now == notified:
            return False
        notified = now
        return True


def watch():
    while True:
        time.sleep(2)
        if refresh():
            send({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})


def handle(req):
    global listed
    method, params = req.get('method'), req.get('params') or {}
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {'listChanged': True}},
                'serverInfo': {'name': 'mrpg', 'version': '1'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        refresh()
        tools = impl.TOOLS if impl else []
        listed = json.dumps(tools, sort_keys=True)   # refresh() compares under impl_lock; a stale read only repeats a notice
        return {'tools': tools}
    if method == 'tools/call':
        changed = refresh()
        note = [{'type': 'text', 'text': 'mrpg_tools.py did not load, the previous version answered:\n' + impl_error}] \
            if impl_error else []
        if not impl:
            return {'content': note, 'isError': True}
        try:
            content = impl.call(params.get('name'), params.get('arguments') or {})
            result = {'content': note + content}
        except Exception as e:
            text = str(e) if isinstance(e, getattr(impl, 'ToolError', ())) else traceback.format_exc()
            result = {'content': note + [{'type': 'text', 'text': text}], 'isError': True}
        if changed:
            send({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})
        return result
    raise LookupError(method)


def main():
    refresh()
    threading.Thread(target=watch, daemon=True).start()
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if 'id' not in req:   # a notification
            continue
        try:
            send({'jsonrpc': '2.0', 'id': req['id'], 'result': handle(req)})
        except LookupError as e:
            send({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32601, 'message': f'unknown method {e}'}})
        except Exception:
            send({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32603, 'message': traceback.format_exc()}})


if __name__ == '__main__':
    main()
