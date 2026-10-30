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
    def test_line_round_preserves_original_photo_as_reference(self):
        import re
        from build_line_quality_round import create
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=[]
            for i in range(2):
                reference=root/f'photo{i}.png';Image.new('RGB',(80,80),(100+i*30,150,200)).save(reference)
                line=root/f'line{i}.png';im=Image.new('L',(80,80),'white');ImageDraw.Draw(im).ellipse((15+i,10,65,70),outline='black',width=2);im.save(line)
                manifest.append({'id':f'person{i}','path':str(line),'reference':str(reference),'roi':[.5,.5,.3,.3]})
            result=create(manifest,root/'output',root)
            script=(root/'output/round/round-data.js').read_text(encoding='utf8')
            bundle=json.loads(base64.b64decode(re.search(r'atob\("([A-Za-z0-9+/=]+)"',script)[1]))
            references=[]
            for value in bundle['sources'].values():references.append(np.asarray(Image.open(io.BytesIO(base64.b64decode(value.split(',')[1]))).convert('RGB')))
            for i in range(2):self.assertTrue(any(np.array_equal(a,np.asarray(Image.open(root/f'photo{i}.png'))) for a in references))
            for case in bundle['cases']:
                pixels=np.asarray(Image.open(io.BytesIO(base64.b64decode(case['candidate'].split(',')[1]))).convert('RGB'))
                self.assertTrue(np.all((pixels==0)|(pixels==255)))
            self.assertEqual(result['cases'],10)
            self.assertTrue(result['allCandidatesAreLineArt'])
    def test_future_rounds_reject_photographic_outputs_and_photo_controls(self):
        from build_quality_round import require_line_candidate
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'photo.png';Image.new('RGB',(40,40),(180,110,70)).save(file)
            with self.assertRaises(ValueError):require_line_candidate(file)
            with self.assertRaises(ValueError):build(Path(directory),Path(directory)/'round',include_controls=True)
    def test_line_controls_are_binary_and_reject_photo_like_inputs(self):
        from build_line_quality_round import line_baseline,variants,verify_line
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'lines.png'
            im=Image.new('L',(120,120),'white');draw=ImageDraw.Draw(im)
            draw.ellipse((30,20,90,100),outline='black',width=2);draw.line((45,55,75,55),fill='black',width=2);im.save(file)
            base=line_baseline(file);controls=variants(base,[.5,.5,.3,.3])
            self.assertEqual(len(controls),5)
            self.assertTrue(np.array_equal(base,controls['baseline']))
            for kind,array in controls.items():
                self.assertTrue(verify_line(array)['binary'])
                if kind!='baseline':self.assertGreater(np.sum(base!=array),0)
            Image.fromarray(np.tile(np.arange(120,dtype='uint8')+60,(120,1))).save(root/'gray.png')
            with self.assertRaises(ValueError):line_baseline(root/'gray.png')

    def test_constant_human_ratings_never_imply_a_perfect_calibration(self):
        from analyze_quality_calibration import fit_readiness
        key={'cases':[{'caseId':str(i),'sourceSHA256':str(i),'split':'calibration'} for i in range(3)]}
        rows=[{'caseId':str(i),'human':{axis:'5' for axis in ['face','outlinePose','compositionCrop']},
            'components':{axis:{'state':'raw_only'} for axis in ['face','outlinePose','compositionCrop']}} for i in range(3)]
        readiness=fit_readiness(rows,key)
        for component in readiness.values():
            self.assertFalse(component['readyForExploratoryFit'])
            self.assertIsNone(component['calibratedScore'])
            self.assertEqual(component['humanLevels'],[5])
    def test_offline_export_includes_public_assets_and_preserves_existing_files(self):
        from export_quality_round import export
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'review.html').write_text('<main>review</main><script src="round-data.js"></script><script src="round-ui.js"></script>',encoding='utf8')
            (root/'round-data.js').write_text('window.REVIEW_DATA={roundId:"test"};',encoding='utf8')
            (root/'round-ui.js').write_text('console.log("ready");',encoding='utf8')
            (root/'private-allocation-key.json').write_text('PRIVATE_DO_NOT_BUNDLE',encoding='utf8')
            output=root/'offline.html';result=export(root,output);html=output.read_text(encoding='utf8')
            self.assertIn('roundId:"test"',html);self.assertNotIn('src=',html)
            self.assertNotIn('PRIVATE_DO_NOT_BUNDLE',html)
            self.assertFalse(result['privateAllocationKeyIncluded'])
            with self.assertRaises(FileExistsError):export(root,output)
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
                image=Image.new('RGB',(20,20),'white');ImageDraw.Draw(image).line((2+i,2,18,18),fill='black')
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
                candidate=Image.new('RGB',(20,20),'white');ImageDraw.Draw(candidate).line((2,2,18,18),fill='black');candidate.save(samples/f'{stem}-secret-prompt-flux.png')
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
