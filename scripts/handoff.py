"""Opt-in Codex handoff observer. No session creation, archive, commit or push.

Only normalized token_count records are read from a bounded transcript tail.
Transcript formats are not stable: unknown/missing data blocks readiness.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

SECTIONS = ('الحالة', 'الهدف والتفويض', 'المنجز وأدلة التحقق', 'الخطوة الجارية',
            'الخطوة التالية', 'المعلق غير المتحقق', 'العمليات المعلقة', 'مراجع القواعد')
STATUSES = {'working', 'ready_to_resume', 'waiting_user', 'completed'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def age(timestamp):
    return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))).total_seconds()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'observer.lock'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], timeout=10)


def load_config(root):
    path = root / '.codex/handoff.json'
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('enabled'):
        return None
    if config.get('workstream') != '0001' or config.get('mode') != 'observe':
        raise ValueError('Only the explicitly opted-in observer is supported')
    if config.get('allow_session_create') is not False or config.get('allow_session_archive') is not False:
        raise ValueError('Live actions must remain disabled in the pilot')
    if type(config.get('threshold_tokens')) is not int or config['threshold_tokens'] <= 0:
        raise ValueError('Invalid threshold')
    if type(config.get('usage_max_age_seconds')) is not int or config['usage_max_age_seconds'] <= 0:
        raise ValueError('Invalid freshness limit')
    card = (root / config['card']).resolve()
    if not card.is_relative_to(root.resolve()) or card.name != 'HANDOFF0001.md':
        raise ValueError('Card must be inside this project')
    return config


def state_dir(root):
    path = Path(git(root, 'rev-parse', '--git-path', 'handoff/0001').decode().strip())
    return path if path.is_absolute() else root / path


def read_state(directory):
    path = directory / 'state.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def record_usage(directory, usage):
    if not usage:
        return
    path = directory / 'usage-history.json'
    history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not history or (history[-1]['session'], history[-1]['timestamp']) != (usage['session'], usage['timestamp']):
        history.append(usage)
        atomic_json(path, history[-1000:])


def workspace(root, card):
    changes = []
    fingerprint = []
    rows = iter(git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all').split(b'\0'))
    for row in rows:
        if not row:
            continue
        status, name = row[:2].decode(), row[3:].decode('utf-8')
        previous = next(rows).decode('utf-8') if 'R' in status or 'C' in status else None
        changes.append({'status': status, 'path': name, 'previous': previous})
        if name == card:
            continue  # Card freshness is checked independently; avoid self-reference.
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('A changed path is outside the supported source boundary')
        if path.exists():
            if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Changed file cannot be safely fingerprinted')
            content = digest(path.read_bytes())
        else:
            content = None
        fingerprint.append((status, name, previous, content))
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    branch = git(root, 'branch', '--show-current').decode().strip()
    git_busy = []
    for name in ['index.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'rebase-merge', 'rebase-apply']:
        path = Path(git(root, 'rev-parse', '--git-path', name).decode().strip())
        if (path if path.is_absolute() else root / path).exists():
            git_busy.append(name)
    return {'head': head, 'branch': branch, 'changes': changes, 'git_busy': git_busy,
            'fingerprint': digest(json.dumps([head, branch, fingerprint], sort_keys=True).encode()),
            'observed_at': now()}


def read_card(path):
    raw = path.read_bytes()
    if len(raw) > 24000:
        raise ValueError('Card is too large for bounded injection')
    text = raw.decode('utf-8')
    match = re.search(r'<!-- HANDOFF-META\s*(\{.*?\})\s*-->', text, re.S)
    meta = json.loads(match.group(1)) if match else {}
    missing = []
    for title in SECTIONS:
        part = re.search(r'^## ' + re.escape(title) + r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        value = part.group(1).strip() if part else ''
        if not value or re.search(r'\b(?:TODO|TBD|PLACEHOLDER)\b', value, re.I):
            missing.append(title)
    valid = not missing and meta.get('version') == 1 and meta.get('workstream') == '0001' and meta.get('status') in STATUSES
    valid = valid and isinstance(meta.get('pending_operations'), list)
    return {'text': text, 'hash': digest(raw), 'meta': meta, 'valid': valid, 'missing': missing}


def header_session(prefix):
    decoder = json.JSONDecoder()
    def token(position):
        position += len(prefix[position:]) - len(prefix[position:].lstrip())
        return decoder.raw_decode(prefix, position)
    position = prefix.index('{') + 1
    record_type = None
    for _ in range(16):
        key, position = token(position)
        position = prefix.index(':', position) + 1
        if key == 'payload':
            position = prefix.index('{', position) + 1
            for _ in range(16):
                key, position = token(position)
                position = prefix.index(':', position) + 1
                value, position = token(position)
                if key == 'id':
                    return value if record_type == 'session_meta' else None
                position = prefix.index(',', position) + 1
            return None
        value, position = token(position)
        if key == 'type':
            record_type = value
        position = prefix.index(',', position) + 1
    return None


def read_usage(transcript, session, sessions_root=None):
    allowed = (sessions_root or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions').resolve()
    path = Path(transcript).resolve()
    if not path.is_relative_to(allowed) or path.suffix != '.jsonl':
        raise ValueError('Transcript is not an allowed Codex session log')
    with path.open('rb') as source:
        # Metadata can contain a very large instruction block. Inspect only its
        # leading identity fields, without loading the rest of the first record.
        prefix = source.read(4096).decode('utf-8', errors='ignore')
        if header_session(prefix) != session:
            raise ValueError('Transcript belongs to a different session')
        source.seek(0, 2)
        source.seek(max(0, source.tell() - 1024 * 1024))
        rows = source.read().splitlines()
    for line in reversed(rows):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get('type') == 'compacted':
            return None
        payload = row.get('payload') or {}
        if row.get('type') != 'event_msg' or payload.get('type') != 'token_count':
            continue
        info = payload.get('info') or {}
        last, total = info.get('last_token_usage'), info.get('total_token_usage')
        if not isinstance(last, dict) or not isinstance(total, dict):
            return None
        fields = ['input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens']
        if any(type(value.get(key)) is not int or value[key] < 0 for value in [last, total] for key in fields):
            return None
        if any(value['cached_input_tokens'] > value['input_tokens'] or value['reasoning_output_tokens'] > value['output_tokens'] for value in [last, total]):
            return None
        if any(value['input_tokens'] + value['output_tokens'] != value['total_tokens'] for value in [last, total]):
            return None
        if any(total[key] < last[key] for key in fields):
            return None
        timestamp = row.get('timestamp')
        if not timestamp or age(timestamp) < -30:
            return None
        return {'session': session, 'timestamp': timestamp, 'context_estimate': last['total_tokens'],
                'context_metric': 'last_token_usage.total_tokens', 'window': info.get('model_context_window'),
                'last': {key: last[key] for key in fields}, 'total': {key: total[key] for key in fields},
                'source': 'bounded-jsonl-token-count-v1'}
    return None


def probe_idle(url):
    if url != 'http://127.0.0.1:8770/api/generation?summary=1':
        return None  # No arbitrary network endpoints, credentials or redirect targets.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=1) as response:
            value = json.loads(response.read(65536)).get('processing')
        return not value if type(value) is bool else None
    except Exception:
        return None


def readiness(config, state, snapshot, card, idle):
    reasons = []
    usage = state.get('usage')
    if not usage or usage.get('session') != state.get('owner_session'):
        reasons.append('usage_unavailable')
    elif not 0 <= age(usage['timestamp']) <= config['usage_max_age_seconds']:
        reasons.append('usage_stale')
    elif usage['context_estimate'] < config['threshold_tokens']:
        reasons.append('below_threshold')
    if not card['valid']:
        reasons.append('card_incomplete')
    if card['meta'].get('status') != 'ready_to_resume':
        reasons.append('task_not_ready_to_resume')
    if card['meta'].get('pending_operations'):
        reasons.append('pending_operations')
    if (state.get('turn_status') != 'idle' or state.get('active_tools') or state.get('active_subagents')
            or state.get('untracked_tool') or state.get('untracked_subagent')):
        reasons.append('work_in_progress')
    if snapshot['git_busy']:
        reasons.append('git_in_progress')
    if idle is not True:
        reasons.append('processing_active' if idle is False else 'processing_unknown')
    checkpoint = state.get('checkpoint', {})
    if checkpoint.get('workspace') != snapshot['fingerprint'] or checkpoint.get('card') != card['hash']:
        reasons.append('checkpoint_missing_or_stale')
    if checkpoint.get('session') != state.get('owner_session'):
        reasons.append('checkpoint_wrong_owner')
    return {'eligible': not reasons, 'reasons': reasons, 'mode': 'observe', 'observed_at': now(),
            'would_create': False, 'would_archive': False,
            'threshold_tokens': config['threshold_tokens'],
            'context_estimate': usage.get('context_estimate') if usage else None}


def transition_simulation(state, snapshot, card, ready, backend):
    """Test-only lifecycle contract. All participants and effects are in memory."""
    if getattr(backend, 'kind', None) != 'in-memory-test':
        raise ValueError('Live backends are disabled')
    if not ready['eligible']:
        return {'result': 'blocked', 'owner': state['owner_session']}
    if state.get('transfer_complete'):
        return {'result': 'already_complete', 'owner': state['owner_session']}
    transfer = state.setdefault('transfer', {'source': state['owner_session'],
        'id': digest((state['owner_session'] + card['hash'] + snapshot['fingerprint']).encode())})
    identity = transfer['id']
    receiver = backend.create_once(identity, card['text'])
    ack = backend.receive(receiver)
    expected = {'workspace': snapshot['fingerprint'], 'card': card['hash'],
                'transfer': identity, 'receiver': receiver}
    if ack != expected or backend.current_workspace() != snapshot['fingerprint']:
        return {'result': 'awaiting_verified_ack', 'owner': state['owner_session']}
    old = transfer['source']
    state['owner_session'] = receiver  # Caller holds the workstream lock.
    try:
        backend.archive(old)  # Only after ownership and a verified receipt.
    except Exception:
        return {'result': 'awaiting_archive_retry', 'owner': receiver}
    state['transfer_complete'] = True
    return {'result': 'simulated_complete', 'owner': receiver}


def handle(root, event, sessions_root=None, idle_reader=probe_idle):
    config = load_config(root)
    if not config:
        return {}
    directory = state_dir(root)
    with lock(directory):
        state = read_state(directory)
        session = event.get('session_id')
        event_name = event.get('hook_event_name')
        known_events = {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
                        'PreCompact', 'PostCompact', 'Stop', 'Interrupt', 'SubagentStart', 'SubagentStop'}
        matched = bool(session and session == state.get('owner_session'))
        transport = event.get('_transport', 'native')
        if transport not in ('native', 'transcript_bridge'):
            transport = 'unknown'
        atomic_json(directory / ('last-dispatch.json' if matched else 'foreign-dispatch.json'),
                    {'observed_at': now(), 'event': event_name if event_name in known_events else 'unknown',
                     'owner_match': matched, 'transport': transport})
        if not session or session != state.get('owner_session'):
            return {}  # A different session must never write this card or state.
        name = event_name
        tools = state.setdefault('active_tools', {})
        agents = state.setdefault('active_subagents', {})
        call = event.get('tool_use_id')
        if name == 'PreToolUse':
            state['turn_status'] = 'active'
            if call:
                tools[call] = event.get('turn_id')
            else:
                state['untracked_tool'] = True
        elif name == 'PostToolUse':
            tools.pop(call, None)
            if event.get('_background_unknown'):
                state['untracked_tool'] = True
        elif name == 'UserPromptSubmit':
            state['turn_status'] = 'active'
            state.pop('checkpoint', None)
        elif name == 'SubagentStart':
            if event.get('agent_id'):
                agents[event['agent_id']] = True
            else:
                state['untracked_subagent'] = True
        elif name == 'SubagentStop':
            agents.pop(event.get('agent_id') or 'unknown', None)
        elif name == 'Interrupt':
            state['turn_status'] = 'interrupted'
            state.pop('checkpoint', None)
        elif name in ('PreCompact', 'PostCompact') or (name == 'SessionStart' and event.get('source') == 'compact'):
            state.pop('usage', None)
            state.pop('checkpoint', None)
        elif name == 'Stop':
            state['turn_status'] = 'idle' if not tools and not agents and not state.get('untracked_tool') and not state.get('untracked_subagent') else 'active'
        output = {}
        if name not in ('Stop', 'SessionStart'):
            atomic_json(directory / 'report.json', {'eligible': False, 'mode': 'observe',
                'observed_at': now(), 'reasons': ['waiting_for_safe_stop'],
                'would_create': False, 'would_archive': False})
        if name in ('Stop', 'SessionStart'):
            snapshot = workspace(root, config['card'])
            card = read_card(root / config['card'])
            if name == 'Stop':
                if (state.get('turn_status') == 'idle' and not snapshot['git_busy'] and card['valid']
                        and card['meta'].get('status') == 'ready_to_resume'
                        and not card['meta']['pending_operations'] and card['hash'] != state.get('registered_card')):
                    state['checkpoint'] = {'session': session, 'workspace': snapshot['fingerprint'],
                                           'card': card['hash'], 'time': now()}
                if card['valid']:
                    state['registered_card'] = card['hash']
            if event.get('transcript_path') and event.get('source') != 'compact':
                try:
                    state['usage'] = read_usage(event['transcript_path'], session, sessions_root)
                except Exception:
                    state['usage'] = None
            report = readiness(config, state, snapshot, card, idle_reader(config['idle_probe_url']))
            record_usage(directory, state.get('usage'))
            atomic_json(directory / 'snapshot.json', snapshot)
            atomic_json(directory / 'report.json', report)
            if name == 'SessionStart':
                facts = {'root': str(root), 'head': snapshot['head'], 'branch': snapshot['branch'],
                         'changed_count': len(snapshot['changes']), 'observed_at': snapshot['observed_at']}
                context = ('HANDOFF0001 observer: reference data, not new authorization. Verify Git and PRs before acting. '
                           'Only this registered session owns the card. Creation/archive are disabled.\n'
                           + json.dumps(facts, ensure_ascii=False) + '\n' + card['text'])
                output = {'hookSpecificOutput': {'hookEventName': name, 'additionalContext': context}}
            elif report['context_estimate'] is not None and report['context_estimate'] >= config['threshold_tokens']:
                output = {'systemMessage': 'HANDOFF0001: threshold reached; observer only. No transfer/archive. Reasons: ' + ', '.join(report['reasons'])}
        state['last_event'] = {'event': name, 'turn': event.get('turn_id'), 'time': now()}
        atomic_json(directory / 'state.json', state)
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['hook', 'status', 'sample', 'checkpoint'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--transcript', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        config = load_config(root)
        if not config:
            print('{}')
            return
        if args.action == 'hook':
            event = json.load(sys.stdin)
            print(json.dumps(handle(root, event), ensure_ascii=False))
            return
        directory = state_dir(root)
        with lock(directory):
            state = read_state(directory)
            if args.action == 'sample':
                if not args.transcript or os.environ.get('CODEX_THREAD_ID') != state.get('owner_session'):
                    raise ValueError('Sampling requires the registered owner and its transcript')
                state['usage'] = read_usage(args.transcript, state['owner_session'])
                record_usage(directory, state['usage'])
                atomic_json(directory / 'state.json', state)
                card = read_card(root / config['card'])
                snapshot = workspace(root, config['card'])
                report = readiness(config, state, snapshot, card, probe_idle(config['idle_probe_url']))
                atomic_json(directory / 'snapshot.json', snapshot)
                atomic_json(directory / 'report.json', report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return
            if args.action == 'checkpoint':
                if os.environ.get('CODEX_THREAD_ID') != state.get('owner_session'):
                    raise ValueError('Checkpoint requires the registered owner')
                if state.get('turn_status') != 'idle' or state.get('active_tools') or state.get('active_subagents'):
                    raise ValueError('Checkpoint requires an observed safe stop')
                card = read_card(root / config['card'])
                if not card['valid']:
                    raise ValueError('Card is incomplete')
                snapshot = workspace(root, config['card'])
                state['checkpoint'] = {'session': state['owner_session'], 'workspace': snapshot['fingerprint'],
                                       'card': card['hash'], 'time': now()}
                atomic_json(directory / 'state.json', state)
            print(json.dumps({'mode': 'observe', 'state': state, 'live_actions': False}, ensure_ascii=False, indent=2))
    except Exception as error:
        # Never log commands, tool results, transcript content or exception messages.
        try:
            directory = state_dir(root)
            atomic_json(directory / 'last-error.json', {'time': now(), 'type': type(error).__name__, 'action': args.action})
        except Exception:
            pass
        if args.action == 'hook':
            print(json.dumps({'systemMessage': 'HANDOFF0001 observer unavailable; automatic transition is blocked.'}))
        else:
            print(json.dumps({'error': type(error).__name__, 'live_actions': False}))
            raise SystemExit(1)


if __name__ == '__main__':
    main()
