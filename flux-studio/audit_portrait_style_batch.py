"""Verify saved real experiment artifacts; never infer identity or visual approval."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from run_portrait_style_batch import STYLES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(manifest, run):
    sources=json.loads(manifest.read_text(encoding='utf8'))
    state=json.loads((run/'batch-state.json').read_text(encoding='utf8'))
    if state.get('state')!='complete' or state.get('completed')!=18:
        raise ValueError('Generation is incomplete.')
    assert state['sourceManifestSHA256']==sha(manifest)
    expected={s['id']+'-'+style for s in sources for style in STYLES}
    assert len(expected)==18 and expected=={c['id'] for c in state['cases']}
    records=[]
    for source in sources:
        assert sha(run/'sources'/(source['id']+'-original.jpg'))==source['sha256']
        model_input=run/'sources'/(source['id']+'-model-input.png')
        for style in STYLES:
            case_id=source['id']+'-'+style;folder=run/case_id
            p=json.loads((folder/'procedure.json').read_text(encoding='utf8'))
            historical=json.loads((folder/'archived-profile.json').read_text(encoding='utf8'))
            g=p['generation'];correction=p['correction']
            assert p['historicalPromptExact'] and g['effectivePrompt']==historical['effectivePrompt']
            assert g['seed']==42 and g['style']==style and g['engine']=='flux' and g['mode']=='edit' and g['referenceCount']==1
            assert sha(model_input)==p['modelInputSHA256']
            assert sha(folder/'raw-flux.png')==p['rawSHA256'] and sha(folder/'final-black.png')==p['finalBlackSHA256']
            raw=np.asarray(Image.open(folder/'raw-flux.png').convert('RGB'))
            corrected=np.asarray(Image.open(folder/'corrected.png').convert('RGB'))
            black=np.asarray(Image.open(folder/'final-black.png').convert('RGB'))
            assert raw.shape==corrected.shape==black.shape
            assert list(reversed(raw.shape[:2]))==p['modelInputDimensions']==[g['width'],g['height']]
            changed=np.any(raw!=corrected,axis=2)
            assert int(changed.sum())==correction['changedPixels']
            roi=np.zeros(raw.shape[:2],bool)
            for l,t,r,b in p['regions']:roi[t:b,l:r]=True
            assert not (changed&~roi).any()
            assert np.array_equal(black[:,:,0],black[:,:,1]) and np.array_equal(black[:,:,1],black[:,:,2])
            alpha=Image.open(folder/'black-transparent.png')
            white=Image.new('RGBA',alpha.size,'white');white.alpha_composite(alpha)
            assert np.array_equal(np.asarray(white.convert('RGB')),black)
            coloured=Image.open(folder/'corrected-transparent.png')
            white=Image.new('RGBA',coloured.size,'white');white.alpha_composite(coloured)
            assert np.abs(np.asarray(white.convert('RGB')).astype(int)-corrected.astype(int)).max()<=1
            assert p['automaticApproval'] is False
            records.append({'id':case_id,'sourceId':source['id'],'style':style,
                'width':g['width'],'height':g['height'],'seconds':g['seconds'],
                'seed':g['seed'],'model':g['model'],'promptTokens':g['promptTokens'],
                'historicalPromptExact':True,'effectivePromptSHA256':hashlib.sha256(g['effectivePrompt'].encode()).hexdigest(),
                'sourceSHA256':source['sha256'],'rawSHA256':p['rawSHA256'],'finalBlackSHA256':p['finalBlackSHA256'],
                'lineScreeningPassed':p['lineScreeningPassed'],'correctionState':correction['state'],
                'operations':correction.get('operations',[]),'changedPixels':correction['changedPixels'],
                'faceComparisonState':p['rawFaceComparison']['state'],'automaticApproval':False})
    result={'version':'portrait-batch-audit/1.0','sources':6,'results':18,'styles':list(STYLES),
        'lineScreenedResults':sum(r['lineScreeningPassed'] for r in records),
        'recordedInferenceSeconds':round(sum(r['seconds'] for r in records),2),
        'changedPixels':sum(r['changedPixels'] for r in records),
        'operations':sum(len(r['operations']) for r in records),
        'verificationScope':'saved artifact consistency; unit tests are recorded separately',
        'nativeBrowserInteractionTested':False,
        'visualApproval':'pending owner selection; generation and tests do not establish identity fidelity',
        'automaticAction':False,'records':records}
    (run/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='records'}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    args=p.parse_args();audit(args.manifest,args.run)
