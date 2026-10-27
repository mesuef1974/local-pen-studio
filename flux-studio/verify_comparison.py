"""Validate saved evidence, physical exports, timing and source integrity."""
import hashlib
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from PIL import Image
from benchmark import ROOT,OUT,CASES,STYLES,atomic_json
from setup_flux import MODEL_DIR,QUANT_FILE


def verify():
    data=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    assert data['state']=='complete'
    expected={case['id']+'-'+style for case in CASES for style in STYLES}
    assert {row['id'] for row in data['rows']}==expected and len(data['rows'])==15
    cases={case['id']:case for case in CASES}
    saved_cases={case['id']:case for case in data['cases']}
    for key,case in cases.items():
        checksum=hashlib.sha256(case['path'].read_bytes()).hexdigest()
        assert checksum==saved_cases[key]['sourceSha256'],f'Original changed: {key}'
    branches=0
    for row in data['rows']:
        key=row['id'];assert row['state']=='complete',key
        metadata=json.loads((OUT/(key+'-generation.json')).read_text(encoding='utf-8'))
        assert metadata['engine']=='flux' and metadata['postProcessing'] is None
        assert metadata['settings']['seed']==42 and metadata['settings']['resolution']==768
        assert metadata['settings']['controls']['shading']=='none'
        assert metadata['settings']['controls']['palette']=='mono'
        assert 1<metadata['promptTokens']<=512
        for branch,suffix,image_suffix in [('direct','-direct','-flux.png'),('precise','-via-precise','-precise.png')]:
            metrics=row[branch];assert not metrics.get('error'),(key,branch)
            raw=json.loads((OUT/(key+suffix+'-paths.json')).read_text(encoding='utf-8'))
            assert metrics['count']==len(raw['paths'])
            with Image.open(OUT/(key+image_suffix)) as image:
                assert image.size==(raw['width'],raw['height'])
            assert metrics['paper']=='A4 portrait' and metrics['penMm']==.3
            expected_time=metrics['inkMm']/30+metrics['travelMm']/80+metrics['count']*.4
            assert math.isclose(metrics['seconds'],expected_time,abs_tol=1e-6)
            svg=ET.parse(OUT/(key+suffix+'.svg')).getroot()
            assert svg.attrib['width']=='210mm' and svg.attrib['height']=='297mm'
            paths=svg.findall('.//{http://www.w3.org/2000/svg}path')
            assert len(paths)==metrics['count']
            for path in paths:
                points=re.findall(r'[ML](-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',path.attrib['d'])
                assert len(points)>=2
                for sx,sy in points:
                    assert 15-.002<=float(sx)<=195+.002
                    assert 15-.002<=float(sy)<=282+.002
            branches+=1
    savings=[(r['precise']['seconds']-r['direct']['seconds'])/r['precise']['seconds']*100 for r in data['rows']]
    manifest=json.loads((MODEL_DIR/'verified.json').read_text(encoding='utf-8'))
    verification={'generated':15,'branches':branches,'originalsUnchanged':5,
        'directFasterPairs':sum(v>0 for v in savings),'medianSavingPercent':statistics.median(savings),
        'allSvgExportsWithinMargins':True,'allTimesMatchFormula':True,
        'modelRevision':manifest['revision'],'quantSha256':manifest['files'][QUANT_FILE]['sha256'],
        'sourceCodeSha256':{str(path.relative_to(ROOT.parent)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [ROOT/'geometry.js',ROOT/'generation_service.py',ROOT/'flux-catalog.json',
                ROOT.parent/'drawing-simulator/pen_paths.py']}}
    data['verification']=verification;atomic_json(OUT/'results.json',data)
    atomic_json(OUT/'integrity.json',verification)
    chosen=[('front-ink','direct','وجه أمامي · حبر نظيف',False),
      ('side-minimal','precise','وجه جانبي · يتطلب فحص الرموش',True),
      ('full-minimal','direct','شخصية كاملة مرسومة · مختصر',False),
      ('animal-minimal','direct','حيوان · اختصار الفرو',False),
      ('object-ink','direct','غرض · حدود واضحة',False)]
    profiles=[]
    for key,route,name,conditional in chosen:
        row=next(row for row in data['rows'] if row['id']==key)
        metadata=json.loads((OUT/(key+'-generation.json')).read_text(encoding='utf-8'))
        profiles.append({'name':name,'evidenceRow':key,'route':route,
          'manualFeatureReviewRequired':conditional,'generation':metadata['settings'],
          'effectivePrompt':metadata['effectivePrompt'],
          'pathSettings':{'lineMode':'centerline','inkThreshold':0,'lineDenoise':0,
            'toleranceMm':.03,'componentMin':0,'spurLength':0,'minLength':2,'junctionRouting':True},
          'motion':{'paperMm':[210,297],'marginMm':15,'penMm':.3,'drawSpeed':30,'travelSpeed':80,'lift':.4},
          'measured':row[route]})
    atomic_json(OUT/'tested-profiles.json',{'schema':'comparison-profiles-v1','simulationOnly':True,
        'note':'تفضيلات مقاسة للمراجعة وإعادة الاستخدام؛ ليست صيغة استيراد آلي مضافة إلى التطبيق. يلزم اختيار الصورة، ومراجعة الملامح قبل الاعتماد.',
        'profiles':profiles})
    print(json.dumps({k:v for k,v in verification.items() if k!='sourceCodeSha256'},indent=2))


if __name__=='__main__':verify()
