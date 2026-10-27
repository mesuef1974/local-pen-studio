"""Focused tests for the live create-only coordinator."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import handoff as h
import handoff_coordinator as c
from test_handoff import CONFIG, OWNER, OTHER, card, usage


class Backend:
    def __init__(self):
        self.queued = []
        self.created = 0
        self.reject = False
        self.fail = False

    def queue(self, session, message):
        self.queued.append((session, message))

    def create(self, root, identity, card_data, snapshot, local):
        self.created += 1
        if self.fail:
            raise RuntimeError('unknown create outcome')
        return OTHER, {'status': 'rejected' if self.reject else 'accepted',
                       'transfer': identity, 'card': card_data['hash'],
                       'workspace': snapshot['fingerprint']}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'repo'; self.root.mkdir()
        h.git(self.root, 'init', '-b', 'main')
        (self.root / 'source.py').write_text('x=1\n')
        h.git(self.root, 'add', 'source.py')
        h.git(self.root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
              'commit', '-m', 'fixture')
        config = dict(CONFIG, mode='create_only', allow_session_create=True, prepare_tokens=180000)
        (self.root / '.codex').mkdir()
        (self.root / '.codex/handoff.json').write_text(json.dumps(config))
        self.card_path = self.root / config['card']; self.card_path.parent.mkdir(parents=True)
        self.card_path.write_text(card(), encoding='utf-8')
        self.sessions = base / 'sessions' / '2026' / '10' / '27'; self.sessions.mkdir(parents=True)
        self.transcript = self.sessions / ('rollout-' + OWNER + '.jsonl')
        self.write_usage(200000)
        self.directory = h.state_dir(self.root); self.directory.mkdir(parents=True)
        snapshot = h.workspace(self.root, config['card']); card_data = h.read_card(self.card_path)
        state = {'owner_session': OWNER, 'turn_status': 'idle', 'active_tools': {},
                 'active_subagents': {}, 'untracked_tool': False, 'untracked_subagent': False,
                 'checkpoint': {'session': OWNER, 'workspace': snapshot['fingerprint'],
                                'card': card_data['hash']}}
        h.atomic_json(self.directory / 'state.json', state)
        self.backend = Backend()

    def write_usage(self, tokens):
        row = usage(tokens)
        self.transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': OWNER}})
                                   + '\n' + json.dumps(row) + '\n', encoding='utf-8')

    def write_records(self, *records):
        self.transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': OWNER}})
                                   + '\n' + '\n'.join(json.dumps(row) for row in records) + '\n',
                                   encoding='utf-8')

    def run_once(self, dry=False):
        return c.once(self.root, self.backend, self.sessions.parents[3], lambda url: True, dry)

    def test_discovers_only_the_matching_owner_transcript(self):
        self.assertTrue(os.path.samefile(c.discover_transcript(OWNER, self.sessions.parents[3]), self.transcript))
        with self.assertRaises(ValueError):
            c.discover_transcript(OTHER, self.sessions.parents[3])

    def test_below_threshold_does_not_queue_or_create(self):
        self.write_usage(179999)
        self.assertEqual(self.run_once()['result'], 'below_threshold')
        self.assertFalse(self.backend.queued); self.assertEqual(self.backend.created, 0)

    def test_preparation_nudges_before_the_hard_threshold(self):
        self.write_usage(180000)
        self.card_path.write_text(card(status='working'), encoding='utf-8')
        result = self.run_once()
        self.assertEqual(result['result'], 'preparing')
        self.assertTrue(result['nudge']); self.assertEqual(len(self.backend.queued), 1)

    def test_incomplete_handoff_queues_one_idempotent_nudge(self):
        self.card_path.write_text(card(status='working'), encoding='utf-8')
        first = self.run_once(); second = self.run_once()
        self.assertEqual(first['result'], 'blocked'); self.assertTrue(first['nudge'])
        self.assertFalse(second['nudge']); self.assertEqual(len(self.backend.queued), 1)
        self.assertEqual(h.read_state(self.directory)['owner_session'], OWNER)

    def test_dry_run_proves_readiness_without_creating(self):
        result = self.run_once(True)
        self.assertEqual(result['result'], 'would_create')
        self.assertEqual(self.backend.created, 0)

    def test_verified_receiver_becomes_owner_without_archiving_source(self):
        result = self.run_once()
        self.assertEqual(result, {'result': 'created', 'receiver': OTHER, 'source_archived': False})
        state = h.read_state(self.directory)
        self.assertEqual(state['owner_session'], OTHER)
        self.assertFalse(state['untracked_tool'])
        transfer = json.loads((self.directory / 'coordinator/transfer.json').read_text())
        self.assertEqual(transfer['phase'], 'complete'); self.assertFalse(transfer['session_archived'])

    def test_nominated_existing_receiver_is_verified_without_creating_another(self):
        c.nominate(self.root, OTHER)
        waiting = self.run_once()
        self.assertEqual(waiting, {'result': 'awaiting_receiver_ack', 'receiver': OTHER})
        transfer = json.loads((self.directory / 'coordinator/transfer.json').read_text())
        expected = {'status': 'accepted', 'transfer': transfer['id'],
                    'card': transfer['card'], 'workspace': transfer['workspace']}
        with patch.object(c, 'read_receiver_ack', return_value=expected):
            result = self.run_once()
        self.assertEqual(result, {'result': 'adopted', 'receiver': OTHER, 'source_archived': False})
        self.assertEqual(self.backend.created, 0); self.assertEqual(len(self.backend.queued), 1)
        self.assertEqual(h.read_state(self.directory)['owner_session'], OTHER)
        self.assertFalse((self.directory / 'coordinator/nomination.json').exists())

    def test_rejected_ack_preserves_source_owner(self):
        self.backend.reject = True
        self.assertEqual(self.run_once()['reasons'], ['receiver_rejected'])
        self.assertEqual(h.read_state(self.directory)['owner_session'], OWNER)

    def test_unknown_creation_outcome_blocks_blind_retry(self):
        self.backend.fail = True
        with self.assertRaises(RuntimeError): self.run_once()
        self.backend.fail = False
        result = self.run_once()
        self.assertEqual(result['reasons'], ['creation_outcome_needs_review'])
        self.assertEqual(self.backend.created, 1)
        self.assertEqual(h.read_state(self.directory)['owner_session'], OWNER)

    def test_reconciliation_requires_complete_turn_and_matching_outputs(self):
        started = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-1'}}
        call = {'type': 'response_item', 'payload': {'type': 'function_call',
                'call_id': 'call-1', 'arguments': '{}'}}
        done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-1'}}
        self.write_records(started, call, done)
        self.assertFalse(c.audit_transcript(self.transcript, OWNER)['safe'])
        output = {'type': 'response_item', 'payload': {'type': 'function_call_output',
                  'call_id': 'call-1', 'output': {'exit_code': 0}}}
        self.write_records(started, call, output, done)
        self.assertTrue(c.audit_transcript(self.transcript, OWNER)['safe'])

    def test_delegation_delivery_without_call_id_is_passive_but_other_orphans_fail(self):
        started = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-1'}}
        delegated = {'type': 'response_item', 'payload': {'type': 'function_call_output',
                     'id': 'fco_fixture', 'namespace': 'codex_app',
                     'name': 'send_message_to_thread', 'output': '{}'}}
        done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-1'}}
        self.write_records(started, delegated, done)
        audit = c.audit_transcript(self.transcript, OWNER)
        self.assertTrue(audit['safe']); self.assertEqual(audit['passive_outputs'], 1)
        delegated['payload']['name'] = 'unknown_tool'
        self.write_records(started, delegated, done)
        with self.assertRaises(ValueError): c.audit_transcript(self.transcript, OWNER)

    def test_reconciliation_closes_a_verified_background_session(self):
        started = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-1'}}
        launch = {'type': 'response_item', 'payload': {'type': 'function_call',
                  'call_id': 'launch', 'arguments': '{}'}}
        launched = {'type': 'response_item', 'payload': {'type': 'function_call_output',
                    'call_id': 'launch', 'output': {'session_id': 42}}}
        wait = {'type': 'response_item', 'payload': {'type': 'function_call',
                'call_id': 'wait', 'arguments': '{"session_id":42}'}}
        waited = {'type': 'response_item', 'payload': {'type': 'function_call_output',
                  'call_id': 'wait', 'output': {'session_id': 42, 'exit_code': 0}}}
        done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-1'}}
        self.write_records(started, launch, launched, wait, waited, done)
        self.assertTrue(c.audit_transcript(self.transcript, OWNER)['safe'])

    def test_safe_reconciliation_clears_sticky_flags_with_evidence(self):
        started = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-1'}}
        done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-1'}}
        self.write_records(started, done, usage())
        state = h.read_state(self.directory); state['untracked_tool'] = True
        state['active_tools'] = {'old': 'turn-0'}; h.atomic_json(self.directory / 'state.json', state)
        changed, audit = c.reconcile_if_safe(self.root, self.transcript, OWNER)
        self.assertTrue(changed); self.assertTrue(audit['safe'])
        saved = h.read_state(self.directory)
        self.assertFalse(saved['untracked_tool']); self.assertEqual(saved['active_tools'], {})
        evidence = json.loads((self.directory / 'coordinator/reconciliation.json').read_text())
        self.assertEqual(evidence['owner'], OWNER); self.assertTrue(evidence['evidence']['safe'])

    def test_reconciliation_never_clears_unresolved_subagents(self):
        started = {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-1'}}
        done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-1'}}
        self.write_records(started, done, usage())
        state = h.read_state(self.directory); state['untracked_subagent'] = True
        h.atomic_json(self.directory / 'state.json', state)
        changed, audit = c.reconcile_if_safe(self.root, self.transcript, OWNER)
        self.assertFalse(changed); self.assertTrue(audit['safe'])
        self.assertTrue(h.read_state(self.directory)['untracked_subagent'])

    def test_incomplete_audit_blocks_reconciliation_without_breaking_usage_refresh(self):
        orphan = {'type': 'response_item', 'payload': {'type': 'function_call_output',
                  'call_id': 'missing', 'output': {'exit_code': 0}}}
        self.write_records(orphan, usage())
        state = h.read_state(self.directory); state['untracked_tool'] = True
        h.atomic_json(self.directory / 'state.json', state)
        owner, transcript, measured = c.refresh_usage(self.root, self.sessions.parents[3])
        self.assertEqual(owner, OWNER); self.assertTrue(os.path.samefile(transcript, self.transcript))
        self.assertEqual(measured['context_estimate'], 200000)
        self.assertTrue(h.read_state(self.directory)['untracked_tool'])

    def test_codex_cli_places_global_approval_option_before_exec(self):
        local = self.directory / 'cli-test'; local.mkdir(parents=True)
        snapshot = h.workspace(self.root, '.codex/unused-card.md')
        card_data = h.read_card(self.card_path)
        identity = c.transfer_id(OWNER, card_data['hash'], snapshot['fingerprint'])

        def fake_run(command, **kwargs):
            ack = Path(command[command.index('-o') + 1])
            h.atomic_json(ack, {'status': 'accepted', 'transfer': identity,
                          'card': card_data['hash'], 'workspace': snapshot['fingerprint']})
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {'type': 'thread.started', 'thread_id': OTHER}) + '\n')

        with patch.object(c.subprocess, 'run', side_effect=fake_run) as invoked:
            receiver, ack = c.CodexCLI(executable='codex').create(
                self.root, identity, card_data, snapshot, local)
        command = invoked.call_args.args[0]
        self.assertEqual(command[:4], ['codex', '-a', 'never', 'exec'])
        self.assertEqual(receiver, OTHER); self.assertEqual(ack['status'], 'accepted')



if __name__ == '__main__':
    unittest.main()
