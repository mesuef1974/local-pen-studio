import json
from pathlib import Path
import shutil
import subprocess
import unittest

import cv2
import numpy as np
from processing import process, encode


@unittest.skipUnless(shutil.which('node'), 'Node is required to read the frontend recipe catalog')
class PresetTests(unittest.TestCase):
    def test_every_preset_runs_through_real_pipeline(self):
        root=Path(__file__).resolve().parent
        catalog=json.loads(subprocess.check_output(['node','test-presets.cjs','--json'],cwd=root,text=True,encoding='utf-8'))
        rgb=np.full((120,160,3),230,np.uint8)
        cv2.rectangle(rgb,(20,20),(100,90),(20,20,20),3)
        cv2.circle(rgb,(125,55),15,(70,100,140),-1)
        image=encode(rgb)
        for method,recipes in catalog.items():
            for key,_,_,options in recipes:
                with self.subTest(method=method,preset=key):
                    data=process({'image':image,'settings':dict(options,method=method)})
                    self.assertEqual((data['width'],data['height']),(160,120))
                    self.assertGreater(data['edgePixels'],0)


if __name__=='__main__':unittest.main()
