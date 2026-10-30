"""Grouped offline comparison with exact archived procedure records and explicit choices."""
import argparse
import base64
import hashlib
import html
import io
import json
from pathlib import Path

from PIL import Image, ImageOps
from run_portrait_style_batch import STYLES

LABELS={'ink':'الحبر الخطي','minimal':'الخطوط المختصرة','pencil-light':'الرصاص الخفيف'}


def uri(path):
    return 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()


def build(manifest, run, allow_partial=False):
    sources=json.loads(manifest.read_text(encoding='utf8'))
    state=json.loads((run/'batch-state.json').read_text(encoding='utf8'))
    if not allow_partial and (state.get('state')!='complete' or state.get('completed')!=18):
        raise ValueError('The batch is incomplete; use --allow-partial only for a labelled progress view.')
    signature=hashlib.sha256(manifest.read_bytes()).hexdigest()
    if state['sourceManifestSHA256']!=signature:
        raise ValueError('Source manifest does not match the generation run.')
    groups=[];cases=[];markup=[]
    for source in sources:
        source_id=source['id'];group={'id':source_id,'source':source,'cases':[]}
        with Image.open(source['path']) as opened:preview=ImageOps.exif_transpose(opened).convert('RGB')
        preview.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        buf=io.BytesIO();preview.save(buf,format='JPEG',quality=95)
        photo='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()
        markup.append(f'<section aria-labelledby="heading-{source_id}"><h2 id="heading-{source_id}">{html.escape(source_id)} · {html.escape(source["note"])}</h2><div class="cards">')
        markup.append(f'<article><h3>الأصل الملون</h3><div class="frame"><img src="{photo}" alt="الصورة الأصلية {source_id}" loading="lazy"></div><p class="original-size" dir="ltr">{source["width"]} × {source["height"]}</p><a href="sources/{source_id}-original.jpg">الأصل بدقته الكاملة</a></article>')
        for style in STYLES:
            case_id=source_id+'-'+style;folder=run/case_id
            saved=next((c for c in state['cases'] if c['id']==case_id),{})
            item={'id':case_id,'sourceId':source_id,'style':style,'label':LABELS[style],
                  'state':saved.get('state','queued'),'lineValid':False}
            details='لم يكتمل التوليد بعد.'
            if saved.get('state')=='complete':
                procedure=json.loads((folder/'procedure.json').read_text(encoding='utf8'))
                if hashlib.sha256((folder/'final-black.png').read_bytes()).hexdigest()!=procedure['finalBlackSHA256']:
                    raise ValueError('Saved output hash mismatch.')
                item.update(width=saved['width'],height=saved['height'],lineValid=procedure['lineScreeningPassed'],
                    baseHash=procedure['finalBlackSHA256'],procedure=procedure,
                    images={name:uri(folder/filename) for name,filename in [('raw','raw-flux.png'),('corrected','corrected.png'),('blackLayer','black-transparent.png'),('base','final-black.png')]})
                g=procedure['generation'];c=procedure['correction'];face=procedure.get('rawFaceComparison',{})
                values=[('النموذج',g['model']),('البرومبت النهائي',g['effectivePrompt']),
                    ('البذرة والدقة والخطوات',f"42 · {g['width']}×{g['height']} · 4 خطوات · guidance=1"),
                    ('الزمن المسجل',str(g['seconds'])+' ثانية'),
                    ('تجهيز الأصل',str(procedure['sourceDimensions'])+' → '+str(procedure['modelInputDimensions'])+'؛ EXIF ثم RGB ثم Lanczos، دون قص. الأصل الكامل محفوظ.'),
                    ('مطابقة البرومبت القديم','مطابق حرفيًا. النص القديم كاملًا؛ خيارات الإضافة الحالية معطلة لمنع تكرار التعليمات. تعليمات الحفاظ موجودة داخل النص.'),
                    ('التصحيح الآلي',f"{c['state']} · {len(c['operations'])} عمليات · {c['changedPixels']} بكسلًا تغيّر. الامتناع لا يعني رفض الرسم."),
                    ('اختبار الخطية','اجتاز مرشحًا تجريبيًا، وليس ضمان جودة.' if item['lineValid'] else 'لم يجتز مرشح الخطية؛ الصورة محفوظة للتشخيص ولا تُعرض كنتاج خطي معتمد.'),
                    ('مقارنة الوجه','تعذّر القياس' if face.get('state')!='raw_only' else 'RMS خام باستخدام 21 نقطة: '+str(round(face['rms'],4))+'؛ ليس نسبة تشابه.'),
                    ('الإخراج','قبل/بعد محفوظان؛ خلفية شفافة؛ نسخة سوداء. التوهج للعرض ويزيد السماكة البصرية فقط.'),
                    ('العمليات التفصيلية',json.dumps(c.get('operations',[]),ensure_ascii=False,indent=2)),
                    ('بصمة النسخة الأساسية',item['baseHash'])]
                details='<table><tbody>'+''.join('<tr><th scope="row">'+html.escape(k)+'</th><td><pre>'+html.escape(v)+'</pre></td></tr>' for k,v in values)+'</tbody></table>'+f'<a href="{case_id}/procedure.json">السجل الكامل JSON</a> · <a href="{case_id}/final-black.png">الأساس دون توهج PNG</a>'
            group['cases'].append(case_id);cases.append(item)
            status='جارٍ التوليد' if item['state']!='complete' else ('جاهز للمراجعة' if item['lineValid'] else 'لم يتحقق مخرج خطي')
            markup.append(f'<article><h3>{html.escape(LABELS[style])}</h3><div class="frame"><canvas id="canvas-{case_id}" role="img" aria-label="{html.escape(LABELS[style])} للصورة {source_id}" hidden></canvas><p id="message-{case_id}">{status}</p></div><label class="approve"><input type="checkbox" id="approve-{case_id}" disabled> اعتماد</label><button type="button" id="save-{case_id}" disabled>تنزيل المعروض PNG</button><details><summary>الإجراء كاملًا والبرومبت</summary>{details}</details></article>')
        markup.append('</div></section>');groups.append(group)
    image_bank={}
    for case in cases:
        for name,encoded in list(case.get('images',{}).items()):
            key=hashlib.sha256(encoded.encode()).hexdigest()
            image_bank.setdefault(key,encoded)
            case['images'][name]=key
    payload={'version':'portrait-style-review/1.0','signature':signature,'groups':groups,'cases':cases,'images':image_bank,
             'completed':state.get('completed',0),'total':18,'automaticAction':False}
    template=(Path(__file__).parent/'portrait-style-review.html').read_text(encoding='utf8')
    template=template.replace('__SECTIONS__',''.join(markup)).replace('__BUNDLE__',base64.b64encode(json.dumps(payload).encode()).decode())
    output=run/'comparison.html';output.write_bytes(template.encode('utf8'))
    print('PAGE',output,'completed',payload['completed'],flush=True)
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--allow-partial',action='store_true')
    args=p.parse_args();build(args.manifest,args.run,args.allow_partial)
