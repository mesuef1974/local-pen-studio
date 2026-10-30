"""Analyze calibration only. Held-out human judgments are never used for fitting."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
import cv2
from quality_features import detect,compare_features
from path_fidelity import decode_image
from validate_quality_ratings import validate,AXES


def analysis(round_directory,ratings_path,output):
    key=json.loads((round_directory/'private-allocation-key.json').read_text(encoding='utf8'))
    ratings=json.loads(ratings_path.read_text(encoding='utf-8-sig'))
    validate(key,[ratings])
    data_script=(round_directory/'round-data.js').read_text(encoding='utf8')
    encoded=re.fullmatch(r'window.REVIEW_DATA=JSON.parse\(atob\("([A-Za-z0-9+/=]+)"\)\);',data_script)
    if not encoded:raise ValueError('صيغة الجولة غير معروفة.')
    bundle=json.loads(base64.b64decode(encoded[1]))
    if bundle['roundId']!=key['roundId']:raise ValueError('مفتاح الجولة غير مطابق.')
    public={case['id']:case for case in bundle['cases']}
    axes={axis:{'numeric':0,'uncertain':0,'na':0,'missing':0,'histogram':{str(i):0 for i in range(1,6)}} for axis in sorted(AXES)}
    cache={};rows=[]
    def features(image):
        image_hash=hashlib.sha256(image.encode()).hexdigest()
        if image_hash not in cache:
            rgb,_=decode_image(image);h,w=rgb.shape[:2]
            if max(h,w)>1024:rgb=cv2.resize(rgb,(max(1,round(w*1024/max(h,w))),max(1,round(h*1024/max(h,w)))),interpolation=cv2.INTER_AREA)
            cache[image_hash]=detect(rgb)
        return cache[image_hash]
    for case in key['cases']:
        if case['split']!='calibration':continue
        item=public[case['caseId']]
        human=ratings.get('ratings',{}).get(case['caseId'],{}).get('scores',{})
        for axis in axes:
            value=human.get(axis)
            bucket='numeric' if value in {'1','2','3','4','5'} else value if value in {'uncertain','na'} else 'missing'
            axes[axis][bucket]+=1
            if bucket=='numeric':axes[axis]['histogram'][value]+=1
        measured=compare_features(features(bundle['sources'][item['sourceId']]),features(item['candidate']))
        rows.append({'caseId':case['caseId'],'human':human,'components':measured['components']})
    coverage={axis:sum(row['components'][axis]['state']=='raw_only' for row in rows) for axis in ['face','outlinePose','compositionCrop']}
    summary={'version':'calibration-analysis/1.0','roundId':key['roundId'],
        'acceptedRatingsFileSHA256':hashlib.sha256(ratings_path.read_bytes()).hexdigest(),
        'reviewers':1,'calibrationCases':len(rows),'heldoutCases':sum(c['split']=='heldout' for c in key['cases']),
        'heldoutHumanJudgmentsAnalyzed':False,'ratingsSummary':axes,'rawDetectorCoverage':coverage,
        'calibratedScore':None,'state':'exploratory_single_reviewer',
        'limitations':['Second independent human reviewer absent.','Pilot dataset is not representative.','No conversion to a percentage fitted or enabled.','Default highest rating may introduce response bias.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'calibration-private-rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'calibration-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--round',type=Path,required=True)
    parser.add_argument('--ratings',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(analysis(args.round,args.ratings,args.output),ensure_ascii=False,indent=2))
