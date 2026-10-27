"""Register the observer without trusting hooks or touching existing handlers."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import uuid

from handoff import atomic_json, load_config, lock, read_card, read_state, state_dir

EVENTS = ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
          'PreCompact', 'PostCompact', 'Stop', 'Interrupt', 'SubagentStart', 'SubagentStop']
MARKER = 'Masar HANDOFF0001 observer'


def install(root, session, home=None):
    codex_home = (home or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))).resolve()
    with lock(codex_home / 'handoff-install'):
        return _install(root, session, codex_home)


def _install(root, session, codex_home):
    uuid.UUID(session)
    if not load_config(root):
        raise ValueError('Project has not opted in')
    codex_home.mkdir(parents=True, exist_ok=True)
    target = codex_home / 'hooks.json'
    original = target.read_bytes() if target.exists() else None
    hooks = json.loads(original.decode('utf-8-sig')) if original else {'hooks': {}}
    groups = hooks.setdefault('hooks', {})
    arguments = [sys.executable, '-X', 'utf8', str(root / 'scripts/handoff.py'), 'hook', '--root', str(root)]
    command = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
    changed = False
    for event in EVENTS:
        entries = groups.setdefault(event, [])
        handler = {'type': 'command', 'command': command, 'timeout': 15,
                   'statusMessage': MARKER, 'additionalContextLimit': 30000}
        owned = [group for group in entries if any(h.get('statusMessage') == MARKER and str(root / 'scripts/handoff.py') in h.get('command', '') for h in group.get('hooks', []))]
        if owned:
            # Do not overwrite unrecognized combinations or another project's hooks.
            if len(owned) != 1 or owned[0].get('hooks') != [handler]:
                raise ValueError('An existing observer definition requires manual review')
        else:
            entries.append({'hooks': [handler]})
            changed = True
    directory = state_dir(root)
    with lock(directory):
        state = read_state(directory)
        if state.get('owner_session') not in (None, session):
            raise ValueError('Another session owns this workstream')
        state.setdefault('owner_session', session)
        state.setdefault('turn_status', 'unknown')
        state.setdefault('registered_card', read_card(root / load_config(root)['card'])['hash'])
        if changed:
            # Check for a concurrent editor before replacing the user's hook file.
            if (target.read_bytes() if target.exists() else None) != original:
                raise ValueError('Hook file changed during installation')
            if original is not None:
                backup = codex_home / 'handoff-backups' / ('hooks-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            atomic_json(target, hooks)
        atomic_json(directory / 'state.json', state)
    return {'registered': True, 'changed': changed, 'mode': 'observe',
            'events': EVENTS, 'requires_hook_trust_review': True,
            'session_created': False, 'session_archived': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session', default=os.environ.get('CODEX_THREAD_ID'))
    args = parser.parse_args()
    if not args.session:
        parser.error('An explicit owner session is required')
    print(json.dumps(install(args.root.resolve(), args.session), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
