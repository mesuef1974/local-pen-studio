import json
import unittest

import handoff as h
from handoff_bridge import Bridge, NativeAvailable, OwnerChanged, ProjectDisabled, block_if_owned, background_unknown, LIMIT
import test_handoff as fixtures
from test_handoff import OWNER, OTHER, usage


def start(turn='turn-bridge'):
    return {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn}}


def call(identity='call-1'):
    return {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': identity,
                                               'name': 'exec_command', 'arguments': 'private command'}}


def finish(identity='call-1', output='completed'):
    return {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': identity,
                                               'output': output}}


class BridgeTests(unittest.TestCase):
    write_log = fixtures.HandoffTests.write_log

    def setUp(self):
        fixtures.HandoffTests.setUp(self)
        self.write_log(start(), usage())

    def bridge(self):
        return Bridge(self.root, self.transcript, self.sessions, lambda url: True)

    def append(self, *records):
        with self.transcript.open('a', encoding='utf-8') as stream:
            for row in records:stream.write(json.dumps(row) + '\n')

    def test_actual_record_envelopes_drive_tools_and_tokens(self):
        self.append(call())
        bridge = self.bridge();bridge.step()
        state = h.read_state(self.directory)
        self.assertEqual(state['turn_status'], 'active')
        self.assertIn('call-1', state['active_tools'])
        self.assertEqual(state['usage']['context_estimate'], 200000)
        self.append(finish(), {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn-bridge'}})
        bridge.step()
        state = h.read_state(self.directory)
        self.assertEqual(state['turn_status'], 'idle')
        self.assertEqual(state['owner_session'], OWNER)
        receipt = json.loads((self.directory/'last-dispatch.json').read_text())
        self.assertEqual(receipt['transport'], 'transcript_bridge')
        self.assertEqual(receipt['event'], 'Stop')

    def test_partial_records_are_not_lost_or_emitted_early(self):
        bridge = self.bridge();bridge.step()
        data = json.dumps(call()).encode()
        with self.transcript.open('ab') as stream:stream.write(data[:30])
        count = bridge.step()
        with self.transcript.open('ab') as stream:stream.write(data[30:]+b'\n')
        self.assertEqual(bridge.step(), count+1)
        self.assertIn('call-1', h.read_state(self.directory)['active_tools'])

    def test_cursor_restart_does_not_replay_completed_records(self):
        self.append(call(), finish())
        bridge = self.bridge();bridge.step()
        resumed = self.bridge()
        self.assertEqual(resumed.step(), 0)

    def test_no_bootstrap_without_a_known_turn(self):
        self.write_log(usage())
        with self.assertRaises(ValueError):self.bridge()

    def test_wrong_owner_and_truncation_are_rejected(self):
        self.write_log(start(), session=OTHER)
        with self.assertRaises(ValueError):self.bridge()
        self.write_log(start(), usage());bridge=self.bridge();bridge.step()
        self.transcript.write_text('')
        with self.assertRaises(ValueError):bridge.step()

    def test_native_arrival_stands_down_instead_of_duplicate_dispatch(self):
        bridge=self.bridge()
        h.atomic_json(self.directory/'last-dispatch.json', {'transport':'native'})
        with self.assertRaises(NativeAvailable):bridge.step()

    def test_old_worker_never_modifies_a_replacement_owners_state(self):
        bridge=self.bridge()
        state=h.read_state(self.directory);state['owner_session']=OTHER
        h.atomic_json(self.directory/'state.json',state)
        before=(self.directory/'state.json').read_bytes()
        with self.assertRaises(OwnerChanged):bridge.step()
        block_if_owned(self.directory,OWNER)
        self.assertEqual((self.directory/'state.json').read_bytes(),before)

    def test_disabling_project_stops_without_processing_more_records(self):
        bridge=self.bridge()
        config=json.loads((self.root/'.codex/handoff.json').read_text());config['enabled']=False
        (self.root/'.codex/handoff.json').write_text(json.dumps(config))
        with self.assertRaises(ProjectDisabled):bridge.step()
        self.assertFalse((self.directory/'last-dispatch.json').exists())

    def test_detached_work_never_becomes_safe_just_because_turn_ended(self):
        self.append(call(), finish(output='Script running with cell ID 42'),
                    {'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn-bridge'}})
        self.bridge().step()
        state=h.read_state(self.directory)
        self.assertTrue(state['untracked_tool'])
        self.assertNotEqual(state['turn_status'],'idle')

    def test_real_text_block_envelope_detects_running_sessions_with_no_exit_field(self):
        value=[{'type':'text','text':json.dumps({'session_id':42,'output':'starting'})}]
        self.assertTrue(background_unknown(value))

    def test_completed_result_stdout_cannot_be_mistaken_for_detached_work(self):
        value=[{'type':'text','text':json.dumps({'session_id':42,'exit_code':0,
                 'output':'Script running with cell ID is an example in a source file'})}]
        self.assertFalse(background_unknown(value))

    def test_nested_work_mcp_envelope_is_not_unknown_work(self):
        def envelope(value):
            return [{'type': 'input_text', 'text': json.dumps(value)}]
        self.assertFalse(background_unknown(envelope({'content': [
            {'type': 'text', 'text': json.dumps({'running': True, 'pid': 123})}
        ], 'isError': False})))
        self.assertTrue(background_unknown(envelope({'content': [
            {'type': 'text', 'text': json.dumps({'session_id': 42})}
        ]})))

    def test_excessive_envelope_depth_still_blocks(self):
        value = 'unknown'
        for _ in range(20):
            value = {'content': value}
        self.assertTrue(background_unknown(value))

    def test_secret_text_never_enters_receipts_or_cursor(self):
        self.append(call(), finish(output='private tool output'))
        self.bridge().step()
        for path in [self.directory/'last-dispatch.json',self.directory/'bridge/cursor.json']:
            value=path.read_text()
            self.assertNotIn('private command',value)
            self.assertNotIn('private tool output',value)

    def test_oversize_and_mismatched_turn_completions_fail_closed(self):
        bridge=self.bridge();bridge.step()
        self.append({'type':'event_msg','payload':{'type':'task_complete','turn_id':'other'}})
        with self.assertRaises(ValueError):bridge.step()
        self.write_log(start(),usage());cursor=self.directory/'bridge/cursor.json';cursor.unlink()
        bridge=self.bridge();bridge.step()
        with self.transcript.open('ab') as stream:stream.write(b'x'*(LIMIT+2))
        with self.assertRaises(ValueError):bridge.step()


if __name__ == '__main__':unittest.main()
