"""Bounded local bridge for Work transcripts; never creates/archives a thread.

This is an explicit fallback transport, NOT proof that native hooks executed.
No prompts, arguments, results or transcript text are persisted by the bridge.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import handoff as h

LIMIT = 1024 * 1024


def background_unknown(value, depth=0):
    # Work wraps tool results in text blocks and JSON more than once. Keep a
    # finite bound, but allow the normal nested MCP -> text -> JSON envelope.
    if depth > 16:
        return True
    if isinstance(value, str):
        if re.search(r'(?m)^(?:Script running with cell ID|Process running with session ID)\b', value):
            return True
        try:
            return background_unknown(json.loads(value), depth + 1)
        except ValueError:
            return False
    if isinstance(value, list):
        return any(background_unknown(part, depth + 1) for part in value)
    if isinstance(value, dict):
        if 'exit_code' in value and type(value['exit_code']) is int:
            return False  # A completed tool result; its stdout is user data.
        if value.get('session_id') is not None or value.get('cell_id') is not None:
            return True
        return any(background_unknown(value[key], depth + 1)
                   for key in ('content', 'text', 'output', 'result', 'results') if key in value)
    return False


class BridgeStopped(Exception):
    reason = 'stopped'


class NativeAvailable(BridgeStopped):
    reason = 'native_transport_available'


class OwnerChanged(BridgeStopped):
    reason = 'ownership_changed'


class ProjectDisabled(BridgeStopped):
    reason = 'project_disabled'


def block_if_owned(directory, owner):
    with h.lock(directory):
        state = h.read_state(directory)
        if state.get('owner_session') != owner:
            return
        state['untracked_tool'] = True
        state.pop('checkpoint', None)
        h.atomic_json(directory / 'state.json', state)
        h.atomic_json(directory / 'report.json', {'eligible': False, 'mode': 'observe',
                      'reasons': ['bridge_unavailable'], 'would_create': False, 'would_archive': False})


class Bridge:
    def __init__(self, root, transcript, sessions_root=None, idle_reader=None):
        self.root = root.resolve()
        self.config = h.load_config(self.root)
        self.idle_reader = idle_reader or h.probe_idle
        if not self.config:
            raise ValueError('Project must opt in')
        self.directory = h.state_dir(self.root)
        self.local = self.directory / 'bridge'
        self.local.mkdir(parents=True, exist_ok=True)
        self.owner = h.read_state(self.directory).get('owner_session')
        self.path = transcript.resolve()
        self.sessions_root = (sessions_root or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions').resolve()
        if not self.path.is_relative_to(self.sessions_root) or self.path.suffix != '.jsonl':
            raise ValueError('Unapproved transcript path')
        with self.path.open('rb') as source:
            if h.header_session(source.read(4096).decode('utf-8', errors='ignore')) != self.owner:
                raise ValueError('Transcript owner mismatch')
        stat = self.path.stat()
        self.identity = [stat.st_dev, stat.st_ino]
        self.offset = 0
        self.turn = None
        self.count = 0
        self.events = {}
        cursor_path = self.local / 'cursor.json'
        if cursor_path.exists():
            cursor = json.loads(cursor_path.read_text(encoding='utf-8'))
            if cursor['identity'] != self.identity or cursor['owner'] != self.owner or cursor['offset'] > stat.st_size:
                raise ValueError('Source rotation/truncation needs review')
            self.offset, self.turn = cursor['offset'], cursor.get('turn')
        else:
            self.bootstrap(stat.st_size)

    def bootstrap(self, size):
        start = max(0, size - LIMIT)
        with self.path.open('rb') as source:
            source.seek(start)
            data = source.read(LIMIT)
        position = start
        if start:
            first = data.find(b'\n')
            if first < 0:
                raise ValueError('No bounded turn boundary')
            position += first + 1
            data = data[first + 1:]
        found = None
        for line in data.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                break
            row = json.loads(line)
            payload = row.get('payload') or {}
            if row.get('type') == 'event_msg' and payload.get('type') == 'task_started':
                found = position
            position += len(line)
        if found is None:
            raise ValueError('No current turn boundary in bounded lookback')
        self.offset = found

    def dispatch(self, name, row, **extra):
        event = dict(session_id=self.owner, cwd=str(self.root), hook_event_name=name,
                     turn_id=self.turn, transcript_path=str(self.path),
                     _transport='transcript_bridge', **extra)
        h.handle(self.root, event, self.sessions_root, self.idle_reader)
        self.count += 1
        self.events[name] = self.events.get(name, 0) + 1

    def process(self, row):
        payload = row.get('payload') or {}
        kind = payload.get('type')
        if row.get('type') == 'event_msg':
            if kind == 'task_started':
                self.turn = payload.get('turn_id') or payload.get('root_turn_id')
                if not self.turn:
                    raise ValueError('Turn identity unavailable')
                self.dispatch('UserPromptSubmit', row)
            elif kind == 'task_complete':
                if (payload.get('turn_id') or payload.get('root_turn_id')) != self.turn:
                    raise ValueError('Completion belongs to another turn')
                self.dispatch('Stop', row)
            elif kind == 'turn_aborted':
                self.dispatch('Interrupt', row)
            elif kind == 'token_count':
                usage = h.read_usage(self.path, self.owner, self.sessions_root)
                with h.lock(self.directory):
                    state = h.read_state(self.directory)
                    if state.get('owner_session') != self.owner:
                        raise ValueError('Ownership changed')
                    state['usage'] = usage
                    h.atomic_json(self.directory / 'state.json', state)
                    h.record_usage(self.directory, usage)
                    snapshot = h.workspace(self.root, self.config['card'])
                    card = h.read_card(self.root / self.config['card'])
                    report = h.readiness(self.config, state, snapshot, card,
                                         self.idle_reader(self.config['idle_probe_url']))
                    h.atomic_json(self.directory / 'report.json', report)
        elif row.get('type') == 'compacted':
            self.dispatch('PreCompact', row)
        elif row.get('type') == 'response_item':
            if kind in ('function_call', 'custom_tool_call'):
                call = payload.get('call_id')
                if not call or not self.turn:
                    raise ValueError('Unidentifiable tool call')
                if 'spawn_agent' in str(payload.get('name', '')):
                    with h.lock(self.directory):
                        state = h.read_state(self.directory)
                        state['untracked_subagent'] = True
                        h.atomic_json(self.directory / 'state.json', state)
                self.dispatch('PreToolUse', row, tool_use_id=call)
            elif kind in ('function_call_output', 'custom_tool_call_output'):
                call = payload.get('call_id')
                if not call:
                    raise ValueError('Unidentifiable tool completion')
                # Preserve uncertainty about detached/async work instead of
                # treating an initial tool response as process completion.
                asynchronous = background_unknown(payload.get('output', ''))
                if call not in h.read_state(self.directory).get('active_tools', {}):
                    asynchronous = True
                self.dispatch('PostToolUse', row, tool_use_id=call, _background_unknown=asynchronous)

    def step(self):
        if not h.load_config(self.root):
            raise ProjectDisabled()
        if h.read_state(self.directory).get('owner_session') != self.owner:
            raise OwnerChanged()
        receipt = self.directory / 'last-dispatch.json'
        if receipt.exists():
            value = json.loads(receipt.read_text(encoding='utf-8'))
            if value.get('transport') == 'native':
                raise NativeAvailable('Native transport observed; bridge stands down')
        stat = self.path.stat()
        if [stat.st_dev, stat.st_ino] != self.identity or stat.st_size < self.offset:
            raise ValueError('Source rotated/truncated')
        with self.path.open('rb') as source:
            source.seek(self.offset)
            data = source.read(LIMIT + 1)
        if len(data) > LIMIT and b'\n' not in data[:LIMIT]:
            raise ValueError('Record exceeds safe bound')
        for line in data.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                break
            row = json.loads(line)
            self.process(row)
            self.offset += len(line)
            h.atomic_json(self.local / 'cursor.json', {'identity': self.identity, 'owner': self.owner,
                                                     'offset': self.offset, 'turn': self.turn})
        return self.count


def watch(root, transcript, nonce):
    directory = h.state_dir(root)
    local = directory / 'bridge'
    status = local / 'status.json'
    owner = h.read_state(directory).get('owner_session')
    try:
        with h.lock(local):
            bridge = Bridge(root, transcript)
            h.atomic_json(status, {'running': True, 'pid': os.getpid(), 'nonce': nonce,
                                  'heartbeat': h.now(), 'transport': 'transcript_bridge', 'phase': 'catching_up'})
            conflicts = 0
            while not (local / 'stop.request').exists():
                try:
                    bridge.step()
                    conflicts = 0
                except FileExistsError:
                    conflicts += 1
                    if conflicts > 5:
                        raise TimeoutError('Observer lock contention')
                    time.sleep(.2)
                    continue
                h.atomic_json(status, {'running': True, 'pid': os.getpid(), 'nonce': nonce,
                                      'heartbeat': h.now(), 'transport': 'transcript_bridge',
                                      'offset': bridge.offset, 'events': bridge.events,
                                      'session_created': False, 'session_archived': False})
                time.sleep(1)
            h.atomic_json(status, {'running': False, 'nonce': nonce, 'heartbeat': h.now(), 'reason': 'stop_requested'})
    except BridgeStopped as stopped:
        try:
            with h.lock(local):
                if status.exists() and json.loads(status.read_text(encoding='utf-8')).get('nonce') == nonce:
                    h.atomic_json(status, {'running': False, 'nonce': nonce, 'heartbeat': h.now(), 'reason': stopped.reason})
        except FileExistsError:
            pass  # A replacement watcher already owns the status.
        return 0
    except Exception as error:
        # A second watcher must not overwrite the first watcher's status.
        if isinstance(error, FileExistsError):
            return 1
        block_if_owned(directory, owner)
        h.atomic_json(status, {'running': False, 'nonce': nonce, 'heartbeat': h.now(),
                              'error_type': type(error).__name__})
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'watch', 'stop', 'status'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--transcript', type=Path)
    parser.add_argument('--nonce', default='direct')
    args = parser.parse_args()
    root = args.root.resolve()
    if not h.load_config(root):
        raise SystemExit('Project must opt in')
    local = h.state_dir(root) / 'bridge'
    local.mkdir(parents=True, exist_ok=True)
    if args.action == 'stop':
        (local / 'stop.request').touch()
    elif args.action == 'status':
        path = local / 'status.json'
        print(path.read_text(encoding='utf-8') if path.exists() else '{"running": false}')
    elif args.action == 'watch':
        if not args.transcript:
            parser.error('--transcript is required')
        raise SystemExit(watch(root, args.transcript, args.nonce))
    else:
        if not args.transcript:
            parser.error('--transcript is required')
        if (local / 'observer.lock').exists():
            raise SystemExit('Bridge already running or stale lock needs review')
        (local / 'stop.request').unlink(missing_ok=True)
        nonce = uuid.uuid4().hex
        subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), 'watch',
                          '--root', str(root), '--transcript', str(args.transcript.resolve()), '--nonce', nonce],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), close_fds=True)
        for _ in range(100):
            path = local / 'status.json'
            if path.exists():
                value = json.loads(path.read_text(encoding='utf-8'))
                if value.get('nonce') == nonce:
                    print(json.dumps(value))
                    raise SystemExit(0 if value['running'] else 1)
            time.sleep(.1)
        raise SystemExit('Bridge startup not confirmed; inspect local status')


if __name__ == '__main__':
    main()
