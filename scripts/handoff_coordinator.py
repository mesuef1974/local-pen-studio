"""Safe 200k handoff coordinator using the supported Codex CLI.

Creates at most one fresh receiver after the observer proves a safe stop. It
never archives a session. Runtime data stays under Git metadata.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import re

import handoff as h


def discover_transcript(session, sessions_root=None):
    root = (sessions_root or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions').resolve()
    matches = []
    for path in root.rglob('*' + session + '.jsonl'):
        try:
            with path.open('rb') as source:
                if h.header_session(source.read(4096).decode('utf-8', errors='ignore')) == session:
                    matches.append(path.resolve())
        except OSError:
            continue
    if len(matches) != 1:
        raise ValueError('Exactly one owner transcript is required')
    return matches[0]


def transfer_id(owner, card_hash, workspace):
    return h.digest((owner + card_hash + workspace).encode())


def nested_values(value, depth=0):
    if depth > 16:
        return
    yield value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        yield from nested_values(parsed, depth + 1)
    elif isinstance(value, list):
        for part in value:
            yield from nested_values(part, depth + 1)
    elif isinstance(value, dict):
        for part in value.values():
            yield from nested_values(part, depth + 1)


def background_ids(value):
    found = set()
    for part in nested_values(value):
        if isinstance(part, dict):
            for key in ('session_id', 'cell_id'):
                if part.get(key) is not None:
                    found.add(str(part[key]))
        elif isinstance(part, str):
            for pattern in (r'(?:cell ID|cell_id["\'\s:=]+)([\w-]+)',
                            r'(?:session ID|session_id["\'\s:=]+)([\w-]+)'):
                found.update(re.findall(pattern, part, re.I))
    return found


def completed_output(value):
    for part in nested_values(value):
        if isinstance(part, dict) and type(part.get('exit_code')) is int:
            return True
        if isinstance(part, str) and re.search(r'(?m)^(?:Script|Process) completed\b', part):
            return True
    return False


def audit_transcript(path, owner):
    calls = {}
    backgrounds = set()
    last_turn = None
    completed_turn = None
    rows = calls_started = calls_finished = passive_outputs = 0
    with path.open('rb') as source:
        if h.header_session(source.read(4096).decode('utf-8', errors='ignore')) != owner:
            raise ValueError('Transcript owner mismatch')
        source.seek(0)
        for raw in source:
            rows += 1
            row = json.loads(raw)
            payload = row.get('payload') or {}
            kind = payload.get('type')
            if row.get('type') == 'event_msg':
                if kind == 'task_started':
                    last_turn = payload.get('turn_id') or payload.get('root_turn_id')
                    completed_turn = None
                elif kind == 'task_complete':
                    turn = payload.get('turn_id') or payload.get('root_turn_id')
                    if turn == last_turn:
                        completed_turn = turn
                elif kind == 'turn_aborted':
                    completed_turn = None
            elif row.get('type') == 'response_item':
                if kind in ('function_call', 'custom_tool_call'):
                    call = payload.get('call_id')
                    if not call or call in calls:
                        raise ValueError('Unidentifiable or duplicate tool call')
                    source_value = payload.get('arguments', payload.get('input', ''))
                    calls[call] = background_ids(source_value)
                    calls_started += 1
                elif kind in ('function_call_output', 'custom_tool_call_output'):
                    call = payload.get('call_id')
                    if (not call and payload.get('namespace') == 'codex_app'
                            and payload.get('name') == 'send_message_to_thread'
                            and str(payload.get('id', '')).startswith('fco_')):
                        passive_outputs += 1
                        continue
                    targets = calls.pop(call, None)
                    if targets is None:
                        raise ValueError('Tool output without a matching call')
                    output = payload.get('output', '')
                    ids = background_ids(output)
                    if h_bridge_background_unknown(output):
                        backgrounds.update(ids)
                    if completed_output(output):
                        backgrounds.difference_update(targets | ids)
                    calls_finished += 1
    return {'safe': bool(last_turn and completed_turn == last_turn and not calls and not backgrounds),
            'rows': rows, 'calls_started': calls_started, 'calls_finished': calls_finished,
            'passive_outputs': passive_outputs,
            'open_calls': len(calls), 'open_backgrounds': len(backgrounds),
            'last_turn_complete': bool(last_turn and completed_turn == last_turn)}


def h_bridge_background_unknown(value):
    # Import lazily so the coordinator and bridge retain one interpretation of
    # nested Work tool results without creating a dependency cycle.
    from handoff_bridge import background_unknown
    return background_unknown(value)


def reconcile_if_safe(root, transcript, owner):
    directory = h.state_dir(root)
    before = transcript.stat()
    try:
        audit = audit_transcript(transcript, owner)
    except (ValueError, json.JSONDecodeError) as error:
        return False, {'safe': False, 'error_type': type(error).__name__}
    after = transcript.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or not audit['safe']:
        return False, audit
    with h.lock(directory):
        state = h.read_state(directory)
        if state.get('owner_session') != owner:
            raise ValueError('Ownership changed during reconciliation')
        if state.get('active_subagents') or state.get('untracked_subagent'):
            return False, audit
        if not (state.get('active_tools') or state.get('active_subagents')
                or state.get('untracked_tool') or state.get('untracked_subagent')):
            return False, audit
        previous = h.digest(json.dumps(state, sort_keys=True).encode())
        state['active_tools'] = {}
        state['untracked_tool'] = False
        state['turn_status'] = 'idle'
        state.pop('checkpoint', None)
        h.atomic_json(directory / 'state.json', state)
        h.atomic_json(directory / 'coordinator/reconciliation.json', {
            'time': h.now(), 'owner': owner, 'transcript_size': after.st_size,
            'transcript_mtime_ns': after.st_mtime_ns, 'previous_state': previous,
            'evidence': audit})
    return True, audit


def prompt_for(identity, card, snapshot, existing=False):
    origin = 'رشحها المستخدم لاستلام المسار' if existing else 'أنشأها منسق HANDOFF0001 بعد بلوغ 200000 توكن'
    return f"""0001 — استئناف آلي آمن

هذه جلسة {origin}. اقرأ بطاقة
docs/handoffs/HANDOFF0001.md من المشروع الحالي وتحقق فعليًا من Git. لا تعدل أي
ملف، ولا تنشر، ولا تدمج، ولا تنشئ أو تؤرشف جلسة. أعد إقرار JSON فقط بالقيم
المطلوبة إذا تطابقت بصمة البطاقة ومساحة العمل، وإلا أعد status=\"rejected\".

transfer={identity}
card={card['hash']}
workspace={snapshot['fingerprint']}
head={snapshot['head']}
"""


class CodexCLI:
    def __init__(self, executable=None, timeout=300):
        self.executable = executable or shutil.which('codex')
        self.timeout = timeout
        if not self.executable:
            raise ValueError('Codex CLI is unavailable')

    def queue(self, session, message):
        result = subprocess.run([self.executable, 'queue', '--thread', session, '--message', message],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30)
        if result.returncode:
            raise RuntimeError('Codex queue failed')

    def _receive(self, root, identity, card, snapshot, local):
        schema = local / 'ack-schema.json'
        ack_path = local / 'ack.json'
        schema_value = {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'status': {'enum': ['accepted', 'rejected']},
                'transfer': {'type': 'string'}, 'card': {'type': 'string'},
                'workspace': {'type': 'string'}},
            'required': ['status', 'transfer', 'card', 'workspace']}
        h.atomic_json(schema, schema_value)
        ack_path.unlink(missing_ok=True)
        command = [self.executable, '-a', 'never', 'exec', '--json', '-C', str(root),
                   '-s', 'read-only', '--output-schema', str(schema), '-o', str(ack_path), '-']
        result = subprocess.run(command, input=prompt_for(identity, card, snapshot), text=True,
                                encoding='utf-8', capture_output=True, timeout=self.timeout)
        if result.returncode:
            raise RuntimeError('Codex receiver failed')
        observed = None
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            observed = observed or value.get('thread_id') or value.get('threadId')
            if value.get('type') == 'thread.started':
                observed = observed or value.get('thread_id')
        if not observed or not ack_path.exists():
            raise RuntimeError('Receiver identity or acknowledgement is missing')
        ack = json.loads(ack_path.read_text(encoding='utf-8'))
        return observed, ack

    def create(self, root, identity, card, snapshot, local):
        return self._receive(root, identity, card, snapshot, local)

def nominate(root, receiver):
    uuid.UUID(receiver)
    directory = h.state_dir(root)
    local = directory / 'coordinator'
    with h.lock(directory):
        owner = h.read_state(directory).get('owner_session')
        if not owner or receiver == owner:
            raise ValueError('Receiver must differ from the registered owner')
        h.atomic_json(local / 'nomination.json', {'source': owner, 'receiver': receiver,
                                                  'time': h.now()})
    return {'source': owner, 'receiver': receiver, 'ownership_changed': False}


def read_receiver_ack(receiver, expected, requested_at, sessions_root=None):
    transcript = discover_transcript(receiver, sessions_root)
    requested = h.dt.datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
    accepted = None
    with transcript.open('r', encoding='utf-8') as source:
        for line in source:
            row = json.loads(line)
            if row.get('type') != 'event_msg' or (row.get('payload') or {}).get('type') != 'task_complete':
                continue
            timestamp = h.dt.datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if timestamp < requested:
                continue
            try:
                value = json.loads((row.get('payload') or {}).get('last_agent_message', ''))
            except (TypeError, ValueError):
                continue
            if value == expected:
                accepted = value
    return accepted


def refresh_usage(root, sessions_root=None):
    directory = h.state_dir(root)
    with h.lock(directory):
        owner = h.read_state(directory).get('owner_session')
    transcript = discover_transcript(owner, sessions_root)
    reconcile_if_safe(root, transcript, owner)
    usage = h.read_usage(transcript, owner, sessions_root)
    if not usage:
        raise ValueError('Owner usage is unavailable')
    with h.lock(directory):
        state = h.read_state(directory)
        if state.get('owner_session') != owner:
            raise ValueError('Ownership changed during usage refresh')
        state['usage'] = usage
        h.atomic_json(directory / 'state.json', state)
        h.record_usage(directory, usage)
    return owner, transcript, usage


def once(root, backend, sessions_root=None, idle_reader=None, dry_run=False):
    root = root.resolve()
    config = h.load_config(root)
    if not config:
        return {'result': 'disabled'}
    directory = h.state_dir(root)
    local = directory / 'coordinator'
    local.mkdir(parents=True, exist_ok=True)
    owner, transcript, usage = refresh_usage(root, sessions_root)
    with h.lock(directory):
        state = h.read_state(directory)
        card = h.read_card(root / config['card'])
        snapshot = h.workspace(root, config['card'])
        idle = (idle_reader or h.probe_idle)(config['idle_probe_url'])
        report = h.readiness(config, state, snapshot, card, idle)
        h.atomic_json(directory / 'snapshot.json', snapshot)
        h.atomic_json(directory / 'report.json', report)
        tokens = usage['context_estimate']
        prepare = config.get('prepare_tokens', config['threshold_tokens'])
        if tokens < prepare:
            return {'result': 'below_threshold', 'context_estimate': usage['context_estimate']}
        at_threshold = tokens >= config['threshold_tokens']
        allowed_nudge_reasons = {'below_threshold', 'card_incomplete', 'task_not_ready_to_resume',
                                 'pending_operations', 'checkpoint_missing_or_stale'}
        if not at_threshold and set(report['reasons']) == {'below_threshold'}:
            return {'result': 'prepared', 'context_estimate': tokens}
        if not report['eligible']:
            key = h.digest(json.dumps([owner, usage['timestamp'], card['hash'], report['reasons']]).encode())
            marker = local / 'nudge.json'
            previous = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
            nudge_allowed = set(report['reasons']).issubset(allowed_nudge_reasons)
            if not dry_run and nudge_allowed and previous.get('key') != key:
                h.atomic_json(marker, {'key': key, 'owner': owner, 'time': h.now()})
                nudge = True
            else:
                nudge = False
            result = {'result': 'preparing' if not at_threshold else 'blocked',
                      'reasons': report['reasons'], 'nudge': nudge}
        else:
            identity = transfer_id(owner, card['hash'], snapshot['fingerprint'])
            transfer_path = local / 'transfer.json'
            transfer = json.loads(transfer_path.read_text(encoding='utf-8')) if transfer_path.exists() else {}
            if transfer and transfer.get('id') != identity and transfer.get('phase') != 'complete':
                return {'result': 'blocked', 'reasons': ['different_transfer_needs_review']}
            if transfer.get('phase') == 'complete' and transfer.get('id') == identity:
                return {'result': 'already_created', 'receiver': transfer.get('receiver')}
            if transfer.get('phase') == 'complete':
                history = local / 'history' / (transfer['id'] + '.json')
                h.atomic_json(history, transfer)
                transfer = {}
            if dry_run:
                nominated = local / 'nomination.json'
                return {'result': 'would_verify' if nominated.exists() else 'would_create',
                        'transfer': identity}
            nomination_path = local / 'nomination.json'
            nomination = json.loads(nomination_path.read_text(encoding='utf-8')) if nomination_path.exists() else {}
            nominated_receiver = nomination.get('receiver') if nomination.get('source') == owner else None
            phase = 'awaiting_existing_ack' if nominated_receiver else 'creating'
            if transfer.get('phase') == 'creating':
                reason = 'creation_outcome_needs_review'
                return {'result': 'blocked', 'reasons': [reason]}
            if transfer.get('phase') == 'awaiting_existing_ack':
                nominated_receiver = transfer.get('receiver')
                requested_at = transfer.get('time')
                queue_existing = False
            else:
                requested_at = h.now()
                h.atomic_json(transfer_path, {'id': identity, 'phase': phase, 'source': owner,
                                             'receiver': nominated_receiver,
                                             'card': card['hash'], 'workspace': snapshot['fingerprint'],
                                             'time': requested_at})
                queue_existing = bool(nominated_receiver)
            nudge = False
            result = None
    if result is not None:
        if result.get('nudge'):
            backend.queue(owner, 'بلغ سياق HANDOFF0001 حد 200000. حدّث متن البطاقة الآن فقط، واجعل status=ready_to_resume بعد إكمال الأقسام والعمليات المعلقة، ثم أنهِ الدور. لا تنشئ أو تؤرشف جلسة ولا تنشر.')
        return result
    expected = {'status': 'accepted', 'transfer': identity,
                'card': card['hash'], 'workspace': snapshot['fingerprint']}
    if nominated_receiver:
        if queue_existing:
            backend.queue(nominated_receiver, prompt_for(identity, card, snapshot, True))
            return {'result': 'awaiting_receiver_ack', 'receiver': nominated_receiver}
        ack = read_receiver_ack(nominated_receiver, expected, requested_at, sessions_root)
        if ack is None:
            return {'result': 'awaiting_receiver_ack', 'receiver': nominated_receiver}
        receiver = nominated_receiver
    else:
        try:
            receiver, ack = backend.create(root, identity, card, snapshot, local)
        except Exception:
            # The creating marker deliberately blocks blind retries: a receiver may
            # have been created even if its acknowledgement was interrupted.
            raise
    if ack != expected:
        h.atomic_json(local / 'transfer.json', {'id': identity, 'phase': 'rejected',
                      'source': owner, 'receiver': receiver, 'time': h.now()})
        return {'result': 'blocked', 'reasons': ['receiver_rejected']}
    with h.lock(directory):
        current = h.read_state(directory)
        current_card = h.read_card(root / config['card'])
        current_snapshot = h.workspace(root, config['card'])
        if (current.get('owner_session') != owner or current_card['hash'] != card['hash']
                or current_snapshot['fingerprint'] != snapshot['fingerprint']):
            h.atomic_json(local / 'transfer.json', {'id': identity, 'phase': 'stale_ack',
                          'source': owner, 'receiver': receiver, 'time': h.now()})
            return {'result': 'blocked', 'reasons': ['state_changed_before_transfer']}
        current['owner_session'] = receiver
        current['turn_status'] = 'unknown'
        current['active_tools'] = {}
        current['active_subagents'] = {}
        current['untracked_tool'] = False
        current['untracked_subagent'] = False
        current.pop('checkpoint', None)
        current.pop('usage', None)
        h.atomic_json(directory / 'state.json', current)
        h.atomic_json(local / 'transfer.json', {'id': identity, 'phase': 'complete',
                      'source': owner, 'receiver': receiver, 'time': h.now(),
                      'session_archived': False})
    (local / 'nomination.json').unlink(missing_ok=True)
    return {'result': 'adopted' if nominated_receiver else 'created',
            'receiver': receiver, 'source_archived': False}


def watch(root, nonce):
    config = h.load_config(root)
    local = h.state_dir(root) / 'coordinator'
    status = local / 'runtime-status.json'
    try:
        with h.lock(local / 'runtime'):
            while not (local / 'stop.request').exists():
                try:
                    result = once(root, CodexCLI())
                    value = {'running': True, 'nonce': nonce, 'pid': os.getpid(),
                             'heartbeat': h.now(), 'last_result': result}
                except Exception as error:
                    value = {'running': True, 'nonce': nonce, 'pid': os.getpid(),
                             'heartbeat': h.now(), 'last_result': {'result': 'error',
                             'type': type(error).__name__}}
                    h.atomic_json(local / 'last-error.json', {'time': h.now(),
                                  'type': type(error).__name__})
                h.atomic_json(status, value)
                time.sleep(config.get('coordinator_poll_seconds', 15))
            h.atomic_json(status, {'running': False, 'nonce': nonce,
                                  'heartbeat': h.now(), 'reason': 'stop_requested'})
    except FileExistsError:
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['once', 'nominate', 'start', 'watch', 'stop', 'status'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--nonce', default='direct')
    parser.add_argument('--codex', type=Path)
    parser.add_argument('--receiver')
    args = parser.parse_args()
    root = args.root.resolve()
    local = h.state_dir(root) / 'coordinator'
    if args.action == 'status':
        runtime = local / 'runtime-status.json'
        transfer = local / 'transfer.json'
        print(json.dumps({'runtime': json.loads(runtime.read_text(encoding='utf-8')) if runtime.exists() else {'running': False},
                          'transfer': json.loads(transfer.read_text(encoding='utf-8')) if transfer.exists() else {'phase': 'idle'}},
                         ensure_ascii=False, indent=2))
        return
    if args.action == 'nominate':
        if not args.receiver:
            parser.error('--receiver is required')
        print(json.dumps(nominate(root, args.receiver), ensure_ascii=False, indent=2))
        return
    if args.action == 'stop':
        (local / 'stop.request').touch()
        return
    if args.action == 'watch':
        raise SystemExit(watch(root, args.nonce))
    if args.action == 'start':
        if (local / 'runtime/observer.lock').exists():
            raise SystemExit('Coordinator already running or stale lock needs review')
        (local / 'stop.request').unlink(missing_ok=True)
        nonce = uuid.uuid4().hex
        subprocess.Popen([os.sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), 'watch',
                          '--root', str(root), '--nonce', nonce], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), close_fds=True)
        for _ in range(100):
            path = local / 'runtime-status.json'
            if path.exists():
                value = json.loads(path.read_text(encoding='utf-8'))
                if value.get('nonce') == nonce:
                    print(json.dumps(value, ensure_ascii=False))
                    raise SystemExit(0 if value.get('running') else 1)
            time.sleep(.1)
        raise SystemExit('Coordinator startup not confirmed')
    try:
        print(json.dumps(once(root, CodexCLI(str(args.codex) if args.codex else None),
                              dry_run=args.dry_run), ensure_ascii=False, indent=2))
    except Exception as error:
        h.atomic_json(local / 'last-error.json', {'time': h.now(), 'type': type(error).__name__})
        print(json.dumps({'result': 'error', 'type': type(error).__name__}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
