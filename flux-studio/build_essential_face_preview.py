"""Reuse existing detections: selecting landmarks does not rerun or improve detection."""
import argparse
import base64
import json
import re
from pathlib import Path
import numpy as np
from essential_face import VERSION, GROUPS, INDICES, EDGES, compare


def build(source, output):
    html = source.read_text(encoding='utf8')
    match = re.search(r"atob\('([^']+)'\)", html)
    if not match:
        raise ValueError('Missing full-mesh bundle.')
    data = json.loads(base64.b64decode(match[1]))
    data.update(version=VERSION, pointIndices=INDICES, pointGroups=GROUPS, edges=EDGES)
    for row in data['samples']:
        row['comparison'] = {'state': 'unavailable', 'score': None}
        if len(row['source']['faces']) == len(row['result']['faces']) == 1:
            points = [np.array(row[role]['faces'][0])[:,:2]*[row[role]['width'],row[role]['height']]
                      for role in ['source','result']]
            row['comparison'] = compare(*points)
    template = (Path(__file__).parent/'full-face-preview.html').read_text(encoding='utf8')
    template = template.replace('مختبر شبكة الوجه الكاملة', 'مختبر معالم الوجه الأساسية')
    template = template.replace('الأصل والرسم تحت الشبكة الكاملة', 'الأصل والرسم · 25 نقطة أساسية')
    template = template.replace('تجربة مستقلة · جميع نقاط الوجه', 'تجربة مستقلة · essential-face/2.0')
    template = template.replace('تُعرض جميع النقاط التي اكتشفها النموذج دون حذف أو انتقاء، مع وصلات الشبكة والقزحيتين.',
        'تُعرض وتُقارن 25 نقطة مختارة من شبكة النموذج: العينان 8، الأنف 5، الفم 8، الجبهة 4. الاختيار تجريبي ولم يُعاير بعد. استُبعد الفك والحاجبان والخدان والقزحية من الحساب. نقاط الجبهة تقديرات هندسية ولا تمثل بالضرورة خطوطًا ظاهرة أو خط الشعر.')
    template = template.replace('جميع النقاط</label>', 'النقاط الأساسية</label>')
    template = template.replace('احتُفظ بإحداثيات x وy وz لجميع النقاط في بيانات الصفحة؛',
        'الكاشف نفسه يستخرج 478 نقطة، وبياناتها الأصلية محفوظة؛ الحساب والعرض هنا يعتمدان على النقاط الأساسية فقط. لا يعالج هذا الاختيار فشل كشف الوجه. ')
    output.write_bytes(template.replace('__BUNDLE__', base64.b64encode(json.dumps(data).encode()).decode()).encode('utf8'))
    summary = {'version': VERSION, 'selectedIndices': INDICES, 'groups': GROUPS,
               'selectionIsExperimental': True, 'detectorUnchanged': True, 'score': None,
               'samples': [{'id': r['id'], 'comparison': r['comparison']} for r in data['samples']]}
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
