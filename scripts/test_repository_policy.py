import unittest
from repository_policy import MAX_BYTES, path_error, workflow_errors


class RepositoryPolicyTests(unittest.TestCase):
    def test_local_and_secret_files_are_blocked_even_when_nested(self):
        for name in ['x/.env', 'x/.env.production', 'x/MODELS/file.json',
                     'x/.venv-flux/config.py', 'node_modules/a.js', 'x/key.PEM',
                     'x/weights.GGUF', 'x/credentials-prod.json', 'x/secrets.json']:
            with self.subTest(name=name):
                self.assertIsNotNone(path_error(name, 1))

    def test_source_and_sanitized_example_are_allowed_but_oversize_is_not(self):
        for name in ['flux-studio/app.js', '.github/main-ruleset.json', '.env.example']:
            self.assertIsNone(path_error(name, 10))
        self.assertIsNotNone(path_error('fixture.png', MAX_BYTES + 1))

    def test_movable_or_untrusted_action_references_are_rejected(self):
        for reference in ['actions/checkout@main', 'actions/checkout@v5',
                          './local-action', 'docker://image:latest']:
            self.assertTrue(workflow_errors('- uses: ' + reference))
        self.assertEqual(workflow_errors('- uses: actions/checkout@' + 'a' * 40), [])

    def test_privileged_pull_request_event_is_rejected(self):
        self.assertTrue(workflow_errors('on:\n  pull_request_target:\n'))


if __name__ == '__main__':
    unittest.main()
