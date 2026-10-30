"""Validate blinded human response exports without inventing missing judgments."""
import argparse
import json
from pathlib import Path

AXES={'face','outlinePose','compositionCrop','traceability'}
VALUES={'1','2','3','4','5','na','uncertain'}


def validate(key, exports):
    ids={case['caseId'] for case in key['cases']}
    groups={}
    for case in key['cases']:
        groups.setdefault(case['sourceSHA256'],set()).add(case['split'])
    if any(len(split)!=1 for split in groups.values()):raise ValueError('تسرب مصدر بين المعايرة والاختبار.')
    reviewers=set();rows=[]
    for export in exports:
        reviewer=export.get('reviewer','').strip()
        if not reviewer or reviewer in reviewers:raise ValueError('رمز المراجع فارغ أو مكرر؛ لا يحتسب مرتين.')
        if export.get('roundId')!=key['roundId']:raise ValueError('الإجابات من جولة مختلفة.')
        reviewers.add(reviewer);ratings=export.get('ratings',{})
        if set(ratings)-ids:raise ValueError('معرّفات تقييم غير موجودة في الجولة.')
        for item in ratings.values():
            if set(item.get('scores',{}))!=AXES or any(v not in VALUES for v in item['scores'].values()):
                raise ValueError('تقييم خارج النطاق أو محور مفقود.')
        rows.append({'reviewer':reviewer,'rated':len(ratings),'expected':len(ids),'complete':set(ratings)==ids})
    return {'roundId':key['roundId'],'reviewers':rows,'reviewPolicy':'one owner-approved manager reviewer is sufficient; independent holdout remains required',
            'humanDataComplete':len(rows)>=1 and all(row['complete'] for row in rows),
            'calibrationState':'pending_model_validation','calibratedScore':None,
            'pilotOnly':key.get('pilotOnly',True)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--key',type=Path,required=True)
    parser.add_argument('ratings',type=Path,nargs='*');args=parser.parse_args()
    print(json.dumps(validate(json.loads(args.key.read_text(encoding='utf-8')),
        [json.loads(p.read_text(encoding='utf-8')) for p in args.ratings]),ensure_ascii=False,indent=2))
