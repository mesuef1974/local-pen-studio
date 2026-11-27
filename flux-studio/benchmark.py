"""Resumable local comparison: five subjects, three prompts, two pen-path pipelines."""
import base64
import hashlib
import io
import json
import subprocess
import time
from pathlib import Path
import requests
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'comparison-review'
API='http://127.0.0.1:8770'
RESOLUTION=768
STYLES=['ink','minimal','pencil-light']
CATALOG=json.loads((ROOT/'flux-catalog.json').read_text(encoding='utf-8'))
LABELS={p['id']:p['title'] for p in CATALOG['presets']}
DOWNLOADS=Path.home()/'Downloads'
CASES=[
 {'id':'front','name':'وجه أمامي','kind':'human','path':DOWNLOADS/'pngtree-portrait-of-a-person-png-image_14289687.png','note':'صورة المستخدم الأمامية؛ توجد علامات مائية في الأصل وقد تؤثر في الرسم. لم تُزل.'},
 {'id':'side','name':'وجه جانبي','kind':'human','path':DOWNLOADS/'tumblr_ompd8y9dGn1s1u22do1_1280.png','note':'صورة المستخدم الجانبية؛ إضاءة قوية وتفاصيل رموش وشعر دقيقة.'},
 {'id':'full','name':'شخصية كاملة · عينة مرسومة','kind':'human','path':DOWNLOADS/'روبوت قطري أنيق بحقيبة.png','note':'رسمة الروبوت التي استخدمها المستخدم. هذه عينة تحكم مرسومة، ولا تثبت الأداء على صورة طبيعية لشخص كامل.'},
 {'id':'animal','name':'حيوان · قطة Chelsea','kind':'animal','path':OUT/'fixtures/chelsea.png','note':'صورة فوتوغرافية مفتوحة CC0، المصور Stefan van der Walt، من أمثلة scikit-image.'},
 {'id':'object','name':'غرض · فنجان قهوة','kind':'object','path':OUT/'fixtures/coffee.png','note':'صورة فوتوغرافية مفتوحة CC0، المصورة Rachel Michetti، من أمثلة scikit-image.'},
]


def atomic_json(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def fixture(name,expected):
    path=OUT/'fixtures'/name
    if not path.is_file():
        url=f'https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/{name}'
        response=requests.get(url,timeout=60);response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest()!=expected:raise ValueError(f'Fixture checksum mismatch: {name}')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(response.content)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError(f'Fixture changed: {name}')


def api_post(session,path,payload):
    deadline=time.monotonic()+900
    while True:
        response=session.post(API+path,json=payload,timeout=180)
        if response.status_code==429 and time.monotonic()<deadline:
            time.sleep(3);continue
        if not response.ok:
            try:message=response.json().get('error')
            except ValueError:message=f'HTTP {response.status_code}'
            raise RuntimeError(message)
        return response.json()


def encode_file(path):
    return 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()


def save_image(data,path):
    path.write_bytes(base64.b64decode(data.split(',',1)[1]))


def tailored_prompt(case,style):
    base=next(p['prompt'] for p in CATALOG['presets'] if p['id']==style)
    if case['kind']=='human':return base
    subject=('the cat, including its eye placement, nose, ears and head silhouette' if case['kind']=='animal'
             else 'the coffee cup and saucer, including their elliptical rims, handle and relative proportions')
    strategy={
      'ink':'Use clean confident black pen contours with connected readable structural lines.',
      'minimal':'Use only a sparse set of long informative contour strokes; omit secondary details.',
      'pencil-light':'Use light graphite outline strokes on clean white paper without tonal shading or crosshatching.',
    }[style]
    return f'Redraw {subject} from the main reference. {strategy} Preserve the subject shape, orientation and framing. Group fur or surface texture into a few meaningful shapes. Omit background, cast shadows, dense texture and hatching. Do not add any human face, new objects or text.'


def render_preview(data,metrics,target):
    # .3 mm * 10 pixels/mm is exactly three pixels before downsampling.
    canvas=Image.new('RGB',(2100,2970),'white');draw=ImageDraw.Draw(canvas)
    mapping=metrics['mapping']
    for path in data['paths']:
        points=[((x*mapping['scale']+mapping['x'])*10,(y*mapping['scale']+mapping['y'])*10) for x,y in path]
        if len(points)>1:draw.line(points,fill='#102b3b',width=3)
    canvas.resize((840,1188),Image.Resampling.LANCZOS).save(target)


def path_result(session,image,prefix):
    json_path=OUT/(prefix+'-paths.json')
    if json_path.is_file():
        data=json.loads(json_path.read_text(encoding='utf-8'))
    else:
        with Image.open(io.BytesIO(base64.b64decode(image.split(',',1)[1]))) as source:w,h=source.size
        scale=min(180/max(1,w-1),267/max(1,h-1))
        data=api_post(session,'/api/paths',{'image':image,'lineMode':'centerline','lineDenoise':0,
          'inkThreshold':0,'tolerance':min(2.5,.03/scale),'componentMin':0,'spurLength':0,
          'minLength':2,'junctionRouting':True})
        atomic_json(json_path,data)
    process=subprocess.run(['node',str(ROOT/'benchmark_metrics.mjs'),str(json_path),str(OUT/prefix)],
        capture_output=True,text=True,encoding='utf-8',timeout=180)
    if process.returncode:raise RuntimeError(process.stderr[-1500:])
    metrics=json.loads(process.stdout)
    # Render exported centerlines, at the same physical .3 mm pen width, on A4 paper.
    render_preview(data,metrics,OUT/(prefix+'-paths.png'))
    return metrics


def run():
    OUT.mkdir(exist_ok=True)
    fixture('chelsea.png','596aa1e7cb875eb79f437e310381d26b338a81c2da23439704a73c4651e8c4bb')
    fixture('coffee.png','cc02f8ca188b167c775a7101b5d767d1e71792cf762c33d6fa15a4599b5a8de7')
    session=requests.Session();session.trust_env=False;session.headers['Origin']=API
    result_path=OUT/'results.json'
    report=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {
      'version':1,'model':'FLUX.2 Klein 4B Q5_K_M','seed':42,'resolution':RESOLUTION,
      'protocol':{'styles':STYLES,'pathMode':'centerline','paper':'A4','penMm':.3,'marginMm':15,
        'drawSpeed':30,'travelSpeed':80,'liftSecondsPerStroke':.4,'timeBudgetPruning':False,
        'preciseResolution':RESOLUTION,'sourcePreparation':'import normalization only; no cropping or filtering'},
      'cases':[], 'rows':[], 'state':'running'}
    report['state']='running';atomic_json(result_path,report)
    for case in CASES:
        original_hash=hashlib.sha256(case['path'].read_bytes()).hexdigest()
        source_path=OUT/(case['id']+'-source.png')
        if not source_path.exists():
            raw=base64.b64encode(case['path'].read_bytes()).decode()
            imported=api_post(session,'/api/import',{'image':'data:image/png;base64,'+raw})
            save_image(imported['image'],source_path)
        if not any(c['id']==case['id'] for c in report['cases']):
            report['cases'].append({k:case[k] for k in ('id','name','kind','note')}|{'sourceFile':case['path'].name,'sourceSha256':original_hash})
        for style in STYLES:
            key=case['id']+'-'+style
            row=next((r for r in report['rows'] if r['id']==key),None)
            if row and row.get('state')=='complete':continue
            row={'id':key,'case':case['id'],'style':style,'label':LABELS[style],'state':'running'}
            report['rows']=[r for r in report['rows'] if r['id']!=key]+[row];atomic_json(result_path,report)
            print('START '+key,flush=True)
            try:
                generated=OUT/(key+'-flux.png');metadata_path=OUT/(key+'-generation.json')
                if not (generated.exists() and metadata_path.exists()):
                    started=time.perf_counter()
                    settings={'image':encode_file(source_path),'style':style,'prompt':tailored_prompt(case,style),
                      'mode':'edit','resolution':RESOLUTION,'seed':42,'aspect':'source','references':[],
                      'controls':{'shading':'none','background':'white','palette':'mono'},
                      'preserve':{'identity':case['kind']!='object','pose':case['kind']!='object','clothes':case['kind']=='human'}}
                    job=api_post(session,'/api/generate',settings)['job']
                    deadline=time.monotonic()+1300
                    while time.monotonic()<deadline:
                        status=session.get(API+'/api/generation',params={'job':job},timeout=30).json()['job']
                        if status is None:raise RuntimeError('The benchmark job is no longer retained.')
                        if status['state']=='failed':raise RuntimeError(status.get('error','Generation failed'))
                        if status['state']=='complete':break
                        time.sleep(1)
                    else:raise TimeoutError('Generation timed out')
                    output=status['result'];save_image(output['image'],generated)
                    metadata={k:v for k,v in output.items() if k!='image'}
                    metadata['wallSeconds']=round(time.perf_counter()-started,2)
                    atomic_json(metadata_path,metadata)
                metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
                row['generation']={k:metadata.get(k) for k in ('width','height','seconds','wallSeconds','peakMiB','promptTokens','effectivePrompt')}
                direct=encode_file(generated)
                try:row['direct']=path_result(session,direct,key+'-direct')
                except Exception as error:row['direct']={'error':str(error)}
                precise_file=OUT/(key+'-precise.png')
                if not precise_file.exists():
                    output=api_post(session,'/api/model',{'image':direct,'resolution':RESOLUTION})
                    save_image(output['image'],precise_file)
                    atomic_json(OUT/(key+'-precise-model.json'),{k:v for k,v in output.items() if k!='image'})
                try:row['precise']=path_result(session,encode_file(precise_file),key+'-via-precise')
                except Exception as error:row['precise']={'error':str(error)}
                row['state']='complete'
                print('DONE '+key+' '+json.dumps({branch:row[branch].get('count',row[branch].get('error')) for branch in ['direct','precise']}),flush=True)
            except Exception as error:
                row.update(state='failed',error=str(error));print('FAILED '+key+': '+str(error),flush=True)
            atomic_json(result_path,report)
        assert hashlib.sha256(case['path'].read_bytes()).hexdigest()==original_hash,'Original image changed'
    report['state']='complete';atomic_json(result_path,report)
    print('BENCHMARK COMPLETE',flush=True)


if __name__=='__main__':run()
