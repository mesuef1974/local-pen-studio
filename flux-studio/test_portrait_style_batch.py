import copy
import json
import tempfile
import unittest
from pathlib import Path

from generation import prompts
from run_portrait_style_batch import transport_settings
from build_portrait_style_page import build


class PortraitStyleBatchTests(unittest.TestCase):
    def profile(self, style='ink'):
        return {'effectivePrompt':'Preserve facial proportions and the full head. Draw thin black lines on white.',
                'settings':{'style':style,'prompt':'original preset','resolution':768,'seed':42,
                    'mode':'edit','aspect':'source','preserve':{'identity':True},'controls':{}}}

    def test_archived_prompt_reproduced_without_duplicate_rules(self):
        for style in ['ink','minimal','pencil-light']:
            profile=self.profile(style);original=copy.deepcopy(profile)
            transported=transport_settings(profile)
            self.assertEqual(prompts(transported),profile['effectivePrompt'])
            self.assertEqual(profile,original)
            self.assertEqual(transported['style'],style)
            self.assertEqual(transported['seed'],42)
            self.assertEqual(transported['resolution'],768)
            self.assertFalse(any(transported['preserve'].values()))

    def test_empty_prompt_not_silently_replaced(self):
        profile=self.profile();profile['effectivePrompt']=''
        with self.assertRaises(ValueError):transport_settings(profile)

    def test_incomplete_batch_cannot_be_presented_as_final(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'manifest.json';manifest.write_text('[]')
            (root/'batch-state.json').write_text(json.dumps({'state':'running','completed':3}))
            with self.assertRaises(ValueError):build(manifest,root)

    def test_source_manifest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'manifest.json';manifest.write_text('[]')
            (root/'batch-state.json').write_text(json.dumps({'state':'complete','completed':18,'sourceManifestSHA256':'wrong'}))
            with self.assertRaises(ValueError):build(manifest,root)


if __name__=='__main__':unittest.main()
