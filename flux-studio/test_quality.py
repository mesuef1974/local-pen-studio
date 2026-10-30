import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
from quality_features import compare_features,silhouette,binary_mask
from build_quality_round import build
from validate_quality_ratings import validate


class QualityTests(unittest.TestCase):
    def test_stratified_split_requires_calibration_and_test_sources_per_profile(self):
        import random
        from build_quality_round import split_groups
        groups=[(Path(name+'-source.png'),[]) for name in ['a','b','c','d']]
        allocations=split_groups(groups,random.Random(1),{'a':'face-supported','b':'face-supported','c':'other','d':'other'})
        for category,names in [('face-supported',{'a','b'}),('other',{'c','d'})]:
            self.assertEqual({split for source,_,split in allocations if source.stem.removesuffix('-source') in names},{'calibration','heldout'})
        with self.assertRaises(ValueError):split_groups(groups[:3],random.Random(1),{'a':'face-supported','b':'other','c':'other'})
    def test_calibration_analysis_does_not_use_heldout_judgments(self):
        from analyze_quality_calibration import analysis
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);samples=root/'samples';samples.mkdir()
            for i in range(2):
                image=Image.new('RGB',(20,20),(i*100,0,0))
                image.save(samples/f'case{i}-source.png');image.save(samples/f'case{i}-test-flux.png')
            built=build(samples,root/'round',seed=1)
            key=json.loads((root/'round/private-allocation-key.json').read_text(encoding='utf8'))
            ratings={'roundId':built['roundId'],'reviewer':'human1','ratings':{c['caseId']:{'scores':{a:'5' for a in ['face','outlinePose','compositionCrop','traceability']}} for c in key['cases']}}
            file=root/'ratings.json';file.write_text(json.dumps(ratings),encoding='utf8')
            with patch('analyze_quality_calibration.detect',return_value=self.feature()):
                first=analysis(root/'round',file,root/'first')
                for case in key['cases']:
                    if case['split']=='heldout':ratings['ratings'][case['caseId']]['scores']={a:'1' for a in ratings['ratings'][case['caseId']]['scores']}
                file.write_text(json.dumps(ratings),encoding='utf8')
                second=analysis(root/'round',file,root/'second')
            self.assertEqual(first['ratingsSummary'],second['ratingsSummary'])
            self.assertFalse(second['heldoutHumanJudgmentsAnalyzed'])
            self.assertIsNone(second['calibratedScore'])
    def test_detector_single_channel_mask_is_two_dimensional(self):
        self.assertEqual(binary_mask(np.ones((10,20,1))).shape,(10,20))
        with self.assertRaises(ValueError):binary_mask(np.ones((10,20,3)))
    def feature(self):
        mask=np.zeros((100,100),bool);mask[10:90,30:70]=True
        points=np.array([[i/20,(i%3)/3] for i in range(12)])
        return dict(face=points.copy(),pose=points.copy(),visibility=np.ones(12),mask=mask)

    def test_identical_geometry_is_raw_zero_without_invented_score(self):
        a=self.feature();r=compare_features(a,a)
        self.assertEqual(r['components']['face']['raw']['normalizedLandmarkRMS'],0)
        self.assertEqual(r['components']['outlinePose']['raw']['shapeNormalizedMaskIoU'],1)
        self.assertIsNone(r['score']);self.assertFalse(r['automaticApproval'])

    def test_changed_face_is_measured_but_missing_face_never_reweights(self):
        a,b=self.feature(),self.feature();b['face'][3]+=.2
        self.assertGreater(compare_features(a,b)['components']['face']['raw']['normalizedLandmarkRMS'],0)
        b['face']=None;r=compare_features(a,b)
        self.assertEqual(r['components']['face']['state'],'unavailable')
        self.assertEqual([c['weight'] for c in r['components'].values()],[.5,.3,.2])
        self.assertIsNone(r['score'])

    def test_silhouette_keeps_aspect_ratio(self):
        a=np.zeros((100,100),bool);a[20:80,40:60]=1
        b=np.zeros((100,100),bool);b[40:60,20:80]=1
        self.assertLess((silhouette(a)&silhouette(b)).sum()/(silhouette(a)|silhouette(b)).sum(),.3)

    def test_low_visibility_prevents_pose_measurement(self):
        a,b=self.feature(),self.feature();b['visibility'][:8]=.2
        self.assertEqual(compare_features(a,b)['components']['outlinePose']['state'],'unavailable')

    def test_round_hides_prompt_names_and_splits_by_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);samples=root/'samples';samples.mkdir()
            for index,stem in enumerate(['human','animal','object']):
                Image.new('RGB',(20,20),(index*50,100,200)).save(samples/f'{stem}-source.png')
                Image.new('RGB',(20,20),'black').save(samples/f'{stem}-secret-prompt-flux.png')
            result=build(samples,root/'out',seed=42)
            html=(root/'out/review.html').read_text(encoding='utf8')
            self.assertNotIn('secret-prompt',html)
            self.assertEqual(result['cases'],3)
            key=json.loads((root/'out/private-allocation-key.json').read_text())
            self.assertFalse(validate(key,[])['humanDataComplete'])
            (samples/'animal-source.png').write_bytes((samples/'human-source.png').read_bytes())
            with self.assertRaisesRegex(ValueError,'مكرر'):build(samples,root/'second',seed=42)

    def test_owner_approved_single_complete_reviewer_is_sufficient(self):
        key={'roundId':'one','cases':[{'caseId':'a','sourceSHA256':'hash','split':'calibration'}]}
        export={'roundId':'one','reviewer':'manager','ratings':{'a':{'scores':{axis:'5' for axis in ['face','outlinePose','compositionCrop','traceability']}}}}
        result=validate(key,[export])
        self.assertTrue(result['humanDataComplete'])
        self.assertIsNone(result['calibratedScore'])

    def test_rating_import_rejects_wrong_round_and_duplicate_reviewers(self):
        key={'roundId':'one','cases':[{'caseId':'a','sourceSHA256':'hash','split':'heldout'}]}
        export={'roundId':'one','reviewer':'r1','ratings':{}}
        self.assertFalse(validate(key,[export])['humanDataComplete'])
        with self.assertRaises(ValueError):validate(key,[export,export])
        with self.assertRaises(ValueError):validate(key,[export|{'roundId':'other'}])

    def test_traceability_uses_existing_engine_and_separate_result(self):
        try:import cairosvg
        except (ImportError,OSError):self.skipTest('Cairo runtime unavailable on this runner')
        from quality_measurement import evaluate
        image=Image.new('RGB',(48,48),'white');ImageDraw.Draw(image).line((8,24,40,24),fill='black',width=2)
        buffer=io.BytesIO();image.save(buffer,format='PNG');encoded='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
        with patch('quality_measurement.RUNTIME',Path('missing-quality-runtime')):
            result=evaluate({'source':encoded,'result':encoded,'widthMm':20,'penMm':.2})
        self.assertIsNone(result['similarity']['score']);self.assertEqual(result['traceability']['state'],'measured')
        self.assertGreater(result['traceability']['paths'],0)
        self.assertTrue(result['traceability']['pathsUsedForAuditOnly']);self.assertFalse(result['automaticApproval'])


if __name__=='__main__':unittest.main()
