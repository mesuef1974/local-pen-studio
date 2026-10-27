"""Isolated tests: temporary Git repositories, fake events, in-memory transport."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

import handoff as h
from install_handoff_hooks import install

OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CONFIG = dict(version=1, enabled=True, workstream='0001', card='docs/handoffs/HANDOFF0001.md',
              threshold_tokens=200000, mode='observe', allow_session_create=False,
              allow_session_archive=False, usage_max_age_seconds=300,
              idle_probe_url='http://127.0.0.1:8770/api/generation?summary=1')


def card(status='ready_to_resume', suffix='', pending=None):
    meta = {'version': 1, 'workstream': '0001', 'status': status, 'pending_operations': pending or []}
    return '# 0001\n<!-- HANDOFF-META\n' + json.dumps(meta) + '\n-->\n' + ''.join(
        '\n## ' + section + '\nVerified task data. ' + suffix + '\n' for section in h.SECTIONS)


def usage(tokens=200000):
    last = dict(input_tokens=tokens - 100, cached_input_tokens=tokens - 200,
                output_tokens=100, reasoning_output_tokens=50, total_tokens=tokens)
    return {'type': 'event_msg', 'timestamp': h.now(), 'payload': {'type': 'token_count',
            'info': {'last_token_usage': last, 'total_token_usage': last,
                     'model_context_window': 475000}}}


class FakeBackend:
    kind = 'in-memory-test'

    def __init__(self, snapshot, card_data):
        self.snapshot, self.card = snapshot, card_data
        self.created, self.archived, self.records = {}, [], []
        self.bad_ack = False
        self.archive_failure = False

    def create_once(self, identity, text):
        self.created.setdefault(identity, OTHER)
        self.records.append('create')
        self.identity = identity
        return self.created[identity]

    def receive(self, receiver):
        self.records.append('ack')
        return {} if self.bad_ack else dict(workspace=self.snapshot['fingerprint'],
                                           card=self.card['hash'], transfer=self.identity, receiver=receiver)

    def current_workspace(self):
        return self.snapshot['fingerprint']

    def archive(self, session):
        if self.archive_failure:
            raise RuntimeError('simulated transport failure')
        self.records.append('archive')
        self.archived.append(session)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        h.git(self.root, 'init', '-b', 'main')
        (self.root / 'source.py').write_text('x=1\n')
        h.git(self.root, 'add', 'source.py')
        h.git(self.root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
        (self.root / '.codex').mkdir()
        (self.root / '.codex/handoff.json').write_text(json.dumps(CONFIG))
        self.card_path = self.root / CONFIG['card']
        self.card_path.parent.mkdir(parents=True)
        self.card_path.write_text(card(), encoding='utf-8')
        self.directory = h.state_dir(self.root)
        self.directory.mkdir(parents=True)
        self.sessions = Path(self.temp.name) / 'sessions'
        self.sessions.mkdir()
        self.transcript = self.sessions / 'session.jsonl'
        self.write_log(usage())
        self.state = {'owner_session': OWNER, 'turn_status': 'idle',
                      'usage': h.read_usage(self.transcript, OWNER, self.sessions)}
        self.snapshot = h.workspace(self.root, CONFIG['card'])
        self.card_data = h.read_card(self.card_path)
        self.state['checkpoint'] = dict(session=OWNER, workspace=self.snapshot['fingerprint'], card=self.card_data['hash'])
        h.atomic_json(self.directory / 'state.json', self.state)

    def write_log(self, *records, session=OWNER):
        rows = [{'type': 'session_meta', 'payload': {'id': session}}, *records]
        self.transcript.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')

    def ready(self, idle=True):
        return h.readiness(CONFIG, self.state, self.snapshot, self.card_data, idle)

    def event(self, name, **kwargs):
        return dict(session_id=OWNER, cwd=str(self.root), hook_event_name=name, turn_id='turn-1',
                    transcript_path=str(self.transcript), **kwargs)

    def handle(self, name, **kwargs):
        return h.handle(self.root, self.event(name, **kwargs), self.sessions, lambda url: True)

    def test_threshold_boundary_uses_latest_request_not_cumulative_total(self):
        self.assertTrue(self.ready()['eligible'])
        self.state['usage']['context_estimate'] = 199999
        self.state['usage']['total']['total_tokens'] = 9000000
        self.assertIn('below_threshold', self.ready()['reasons'])

    def test_cached_and_reasoning_tokens_are_subsets_not_added_twice(self):
        value = h.read_usage(self.transcript, OWNER, self.sessions)
        self.assertEqual(value['context_estimate'], 200000)
        self.assertEqual(value['last']['reasoning_output_tokens'], 50)

    def test_wrong_transcript_owner_and_outside_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            h.read_usage(self.transcript, OTHER, self.sessions)
        with self.assertRaises(ValueError):
            h.read_usage(self.root / 'source.py', OWNER, self.sessions)

    def test_large_metadata_is_not_parsed_or_injected(self):
        metadata = {'timestamp': h.now(), 'ordinal': 0, 'type': 'session_meta',
                    'payload': {'creator_user_id': 'fixture-user', 'session_id': OWNER,
                                'id': OWNER, 'instructions': 'private metadata' * 5000}}
        self.transcript.write_text(json.dumps(metadata) + '\n' + json.dumps(usage()) + '\n')
        result = h.read_usage(self.transcript, OWNER, self.sessions)
        self.assertEqual(result['context_estimate'], 200000)
        self.assertNotIn('instructions', result)

    def test_unknown_schema_and_negative_or_inconsistent_counts_fail_closed(self):
        for key, value in [('input_tokens', -1), ('cached_input_tokens', 999999), ('total_tokens', 5)]:
            row = usage()
            row['payload']['info']['last_token_usage'][key] = value
            self.write_log(row)
            self.assertIsNone(h.read_usage(self.transcript, OWNER, self.sessions))
        self.write_log({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'new_schema': True}}})
        self.assertIsNone(h.read_usage(self.transcript, OWNER, self.sessions))

    def test_compaction_invalidates_previous_pressure(self):
        self.write_log(usage(), {'type': 'compacted'})
        self.assertIsNone(h.read_usage(self.transcript, OWNER, self.sessions))
        self.handle('PreCompact')
        self.assertNotIn('checkpoint', h.read_state(self.directory))

    def test_missing_and_stale_usage_block_readiness(self):
        self.state['usage']['timestamp'] = '2000-01-01T00:00:00+00:00'
        self.assertIn('usage_stale', self.ready()['reasons'])
        self.state['usage'] = None
        self.assertIn('usage_unavailable', self.ready()['reasons'])

    def test_incomplete_and_placeholder_cards_are_rejected(self):
        self.card_path.write_text(card().replace('## الخطوة التالية', '## Other'), encoding='utf-8')
        self.assertFalse(h.read_card(self.card_path)['valid'])
        self.card_path.write_text(card(suffix='TODO'), encoding='utf-8')
        self.assertFalse(h.read_card(self.card_path)['valid'])

    def test_waiting_completed_and_working_tasks_never_spawn_followups(self):
        for status in ['waiting_user', 'completed', 'working']:
            self.card_data['meta']['status'] = status
            self.assertIn('task_not_ready_to_resume', self.ready()['reasons'])

    def test_pending_operations_and_active_workers_block_transfer(self):
        self.card_data['meta']['pending_operations'] = ['generation-job-1']
        self.assertIn('pending_operations', self.ready()['reasons'])
        self.state['active_tools'] = {'call': 'turn-1'}
        self.assertIn('work_in_progress', self.ready()['reasons'])
        self.state.pop('active_tools')
        self.state['active_subagents'] = {'worker': True}
        self.assertIn('work_in_progress', self.ready()['reasons'])

    def test_git_locks_and_unavailable_or_busy_platform_block(self):
        self.snapshot['git_busy'] = ['index.lock']
        self.assertIn('git_in_progress', self.ready()['reasons'])
        self.assertIn('processing_active', self.ready(False)['reasons'])
        self.assertIn('processing_unknown', self.ready(None)['reasons'])

    def test_edit_after_checkpoint_invalidates_freshness(self):
        (self.root / 'source.py').write_text('x=2\n')
        self.snapshot = h.workspace(self.root, CONFIG['card'])
        self.assertIn('checkpoint_missing_or_stale', self.ready()['reasons'])

    def test_card_is_excluded_from_its_own_workspace_hash_but_has_separate_digest(self):
        self.card_path.write_text(card(suffix='new evidence'), encoding='utf-8')
        changed = h.workspace(self.root, CONFIG['card'])
        self.assertEqual(changed['fingerprint'], self.snapshot['fingerprint'])
        self.card_data = h.read_card(self.card_path)
        self.assertIn('checkpoint_missing_or_stale', self.ready()['reasons'])

    def test_foreign_session_cannot_modify_state_or_receive_card(self):
        before = (self.directory / 'state.json').read_bytes()
        event = self.event('SessionStart'); event['session_id'] = OTHER
        self.assertEqual(h.handle(self.root, event, self.sessions), {})
        self.assertEqual((self.directory / 'state.json').read_bytes(), before)

    def test_tool_lifecycle_never_marks_running_work_idle(self):
        self.handle('PreToolUse', tool_use_id='call-1')
        self.handle('Stop')
        self.assertEqual(h.read_state(self.directory)['turn_status'], 'active')
        self.handle('PostToolUse', tool_use_id='call-1')
        self.handle('Stop')
        self.assertEqual(h.read_state(self.directory)['turn_status'], 'idle')

    def test_unknown_tool_identity_and_interrupt_remain_blocked(self):
        self.handle('PreToolUse')
        self.handle('Stop')
        self.assertEqual(h.read_state(self.directory)['turn_status'], 'active')
        self.handle('Interrupt')
        self.assertNotIn('checkpoint', h.read_state(self.directory))

    def test_observer_never_requests_continuation_or_modifies_card(self):
        before = self.card_path.read_bytes()
        response = self.handle('Stop')
        self.assertNotIn('decision', response)
        self.assertNotIn('continue', response)
        self.assertEqual(self.card_path.read_bytes(), before)
        self.assertEqual(h.read_state(self.directory)['owner_session'], OWNER)
        report = json.loads((self.directory / 'report.json').read_text())
        self.assertFalse(report['would_create']); self.assertFalse(report['would_archive'])

    def test_stop_captures_only_a_new_complete_card_at_a_safe_point(self):
        self.state.pop('checkpoint')
        self.state['registered_card'] = self.card_data['hash']
        h.atomic_json(self.directory / 'state.json', self.state)
        self.handle('Stop')
        self.assertNotIn('checkpoint', h.read_state(self.directory))
        self.card_path.write_text(card(suffix='fresh evidence'), encoding='utf-8')
        self.handle('Stop')
        self.assertIn('checkpoint', h.read_state(self.directory))

    def test_opt_in_disabled_projects_have_no_hook_side_effects(self):
        (self.root / '.codex/handoff.json').unlink()
        before = (self.directory / 'state.json').read_bytes()
        self.assertEqual(self.handle('Stop'), {})
        self.assertEqual((self.directory / 'state.json').read_bytes(), before)

    def test_live_configuration_is_explicitly_rejected(self):
        value = dict(CONFIG, allow_session_archive=True)
        (self.root / '.codex/handoff.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):h.load_config(self.root)

    def test_atomic_write_failure_preserves_previous_json(self):
        target = self.directory / 'atomic.json'
        h.atomic_json(target, {'old': True})
        with patch.object(h.os, 'replace', side_effect=OSError):
            with self.assertRaises(OSError):h.atomic_json(target, {'old': False})
        self.assertEqual(json.loads(target.read_text()), {'old': True})

    def test_exclusive_lock_prevents_two_writers(self):
        with h.lock(self.directory):
            with self.assertRaises(FileExistsError):
                with h.lock(self.directory):pass
        self.assertFalse((self.directory / 'observer.lock').exists())

    def test_simulation_requires_receipt_before_ownership_and_archive(self):
        backend = FakeBackend(self.snapshot, self.card_data)
        backend.bad_ack = True
        result = h.transition_simulation(self.state, self.snapshot, self.card_data, self.ready(), backend)
        self.assertEqual(result['owner'], OWNER)
        self.assertFalse(backend.archived)
        backend.bad_ack = False
        result = h.transition_simulation(self.state, self.snapshot, self.card_data, self.ready(), backend)
        self.assertEqual(result['result'], 'simulated_complete')
        self.assertEqual(backend.archived, [OWNER])
        self.assertEqual(len(backend.created), 1)
        h.transition_simulation(self.state, self.snapshot, self.card_data, {'eligible': True}, backend)
        self.assertEqual(backend.archived, [OWNER])

    def test_workspace_change_during_receipt_keeps_source_owner(self):
        backend = FakeBackend(self.snapshot, self.card_data)
        backend.current_workspace = lambda: 'changed'
        result = h.transition_simulation(self.state, self.snapshot, self.card_data, self.ready(), backend)
        self.assertEqual(result['owner'], OWNER)
        self.assertFalse(backend.archived)

    def test_archive_failure_can_retry_without_duplicate_receiver(self):
        backend = FakeBackend(self.snapshot, self.card_data)
        backend.archive_failure = True
        self.assertEqual(h.transition_simulation(self.state, self.snapshot, self.card_data, self.ready(), backend)['result'], 'awaiting_archive_retry')
        backend.archive_failure = False
        h.transition_simulation(self.state, self.snapshot, self.card_data, {'eligible': True}, backend)
        self.assertEqual(len(backend.created), 1)
        self.assertEqual(backend.archived, [OWNER])

    def test_live_backends_cannot_be_used_even_when_ready(self):
        backend = FakeBackend(self.snapshot, self.card_data); backend.kind = 'live'
        with self.assertRaises(ValueError):h.transition_simulation(self.state, self.snapshot, self.card_data, self.ready(), backend)

    def test_installer_preserves_existing_hooks_and_is_idempotent(self):
        home = Path(self.temp.name) / 'codex-home';home.mkdir()
        existing = {'description': 'preserve', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing'}]}]}}
        (home / 'hooks.json').write_text(json.dumps(existing))
        first = install(self.root, OWNER, home)
        data = json.loads((home / 'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(data['hooks']['Stop'][0], existing['hooks']['Stop'][0])
        self.assertEqual(data['description'], 'preserve')
        self.assertTrue(first['requires_hook_trust_review'])
        self.assertFalse(install(self.root, OWNER, home)['changed'])
        self.assertEqual(len(list((home / 'handoff-backups').glob('*.json'))), 1)

    def test_installer_refuses_to_take_another_sessions_ownership(self):
        home = Path(self.temp.name) / 'codex-home'
        with self.assertRaises(ValueError):install(self.root, OTHER, home)
        self.assertFalse((home / 'hooks.json').exists())

    def test_installer_limits_context_to_session_start_and_interrupt_to_three_seconds(self):
        home = Path(self.temp.name) / 'codex-home'
        install(self.root, OWNER, home)
        data = json.loads((home / 'hooks.json').read_text(encoding='utf-8'))
        for event, groups in data['hooks'].items():
            handler = groups[0]['hooks'][0]
            self.assertEqual(handler['timeout'], 3 if event == 'Interrupt' else 15)
            self.assertEqual('additionalContextLimit' in handler, event == 'SessionStart')

    def test_known_legacy_definitions_are_migrated_without_touching_other_handlers(self):
        home = Path(self.temp.name) / 'codex-home'
        install(self.root, OWNER, home)
        path = home / 'hooks.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for groups in data['hooks'].values():
            groups[0]['hooks'][0].update(timeout=15, additionalContextLimit=30000)
        external = {'hooks': [{'type': 'command', 'command': 'preserve-me'}]}
        data['hooks']['Stop'].append(external)
        path.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(install(self.root, OWNER, home)['changed'])
        updated = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(updated['hooks']['Stop'][-1], external)
        self.assertNotIn('additionalContextLimit', updated['hooks']['Stop'][0]['hooks'][0])
        self.assertFalse(install(self.root, OWNER, home)['changed'])

    def test_registered_command_executes_json_contract_in_a_path_with_spaces(self):
        spaced = Path(self.temp.name) / 'repo with spaces'
        shutil.copytree(self.root, spaced)
        (spaced / 'scripts').mkdir()
        shutil.copy2(Path(h.__file__), spaced / 'scripts/handoff.py')
        config = dict(CONFIG, idle_probe_url='disabled-for-isolated-test')
        (spaced / '.codex/handoff.json').write_text(json.dumps(config))
        home = Path(self.temp.name) / 'codex-home'
        install(spaced, OWNER, home)
        definition = json.loads((home / 'hooks.json').read_text(encoding='utf-8'))
        command = definition['hooks']['SessionStart'][-1]['hooks'][0]['command']
        event = dict(session_id=OWNER, hook_event_name='SessionStart', cwd=str(spaced), source='resume')
        result = subprocess.run(command, shell=True, input=json.dumps(event), cwd=spaced,
                                text=True, encoding='utf-8', capture_output=True, timeout=20,
                                env=dict(os.environ, PYTHONUTF8='1', CODEX_HOME=str(home)))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertIn('HANDOFF0001', output['hookSpecificOutput']['additionalContext'])
        self.assertEqual(h.read_state(h.state_dir(spaced))['owner_session'], OWNER)

    def test_hook_failure_is_visible_and_does_not_break_session(self):
        (self.root / '.codex/handoff.json').write_text('{broken')
        result = subprocess.run([os.sys.executable, h.__file__, 'hook', '--root', str(self.root)],
                                input='{}', text=True, capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn('blocked', json.loads(result.stdout)['systemMessage'])
        saved = json.loads((self.directory / 'last-error.json').read_text())
        self.assertEqual(saved['type'], 'JSONDecodeError')
        self.assertNotIn('message', saved)


if __name__ == '__main__':
    unittest.main()
