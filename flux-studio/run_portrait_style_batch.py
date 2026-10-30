"""Resumable local experiment: six sources x three archived FLUX prompt profiles."""
import argparse
import base64
import hashlib
import io
import json
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from generation import CATALOG, dimensions, prompts, validate
from quality_features import verified_model
from essential_face import compare
from build_quality_round import require_line_candidate
from build_line_correction_experiment import feature_regions, transparent, png
from conservative_line_corrector import correct, source_evidence

STYLES = ('ink','minimal','pencil-light')


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')


def request(port, route, payload=None):
    raw=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}{route}',data=raw,
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'})
    with urllib.request.urlopen(req,timeout=40) as response:
        return json.load(response)


def transport_settings(archived):
    """Full historical prompt, no duplicate instructions from the current catalog."""
    settings={key:value for key,value in archived['settings'].items()}
    settings.update(prompt=archived['effectivePrompt'],resolution=768,seed=42,
        references=[],mode='edit',aspect='source',
        preserve={key:False for key in CATALOG['preserve']},
        controls={key:'auto' for key in CATALOG['controls']})
    if prompts(settings)!=archived['effectivePrompt']:
        raise ValueError('Historical prompt could not be reproduced exactly.')
    return settings


def run(manifest, archive, output, port):
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    sources=json.loads(manifest.read_text(encoding='utf8'))
    if len(sources)!=6:
        raise ValueError('This experiment requires exactly six source portraits.')
    output.mkdir(parents=True,exist_ok=True)
    state_path=output/'batch-state.json'
    state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {
        'version':'portrait-three-styles/1.0','createdAt':utc(),'total':18,'cases':[],
        'sourceManifestSHA256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    if state['sourceManifestSHA256']!=hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError('Source manifest changed; use a new experiment directory.')
    archived={style:json.loads((archive/f'front-{style}-generation.json').read_text(encoding='utf8')) for style in STYLES}
    source_folder=output/'sources';source_folder.mkdir(exist_ok=True)
    evidence_cache={};feature_cache={}
    options=vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=verified_model('face_landmarker.task')),
        num_faces=2,min_face_detection_confidence=.7,min_face_presence_confidence=.7)
    with vision.FaceLandmarker.create_from_options(options) as detector:
        for source in sources:
            source_id=source['id']
            if source_id not in ('man-01','man-02','man-03','woman-01','woman-02','woman-03'):
                raise ValueError('Unexpected source id.')
            original=Path(source['path'])
            if hashlib.sha256(original.read_bytes()).hexdigest()!=source['sha256']:
                raise ValueError('Original source hash mismatch.')
            copied=source_folder/(source_id+'-original.jpg')
            if not copied.exists():shutil.copyfile(original,copied)
            with Image.open(original) as opened:rgb=ImageOps.exif_transpose(opened).convert('RGB')
            source_size=rgb.size
            target=dimensions({'resolution':768,'aspect':'source'},source_size)
            ready=rgb.resize(target,Image.Resampling.LANCZOS)
            model_path=source_folder/(source_id+'-model-input.png')
            ready.save(model_path,format='PNG')
            ready_array=np.asarray(ready)
            feature_cache[source_id]=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(ready_array))).face_landmarks
            evidence_cache[source_id]=source_evidence(ready_array)
            for style in STYLES:
                case_id=source_id+'-'+style;folder=output/case_id;folder.mkdir(exist_ok=True)
                case=next((c for c in state['cases'] if c['id']==case_id),None)
                if case and case.get('state')=='complete':
                    if hashlib.sha256((folder/'raw-flux.png').read_bytes()).hexdigest()!=case['rawSHA256']:
                        raise ValueError('Previously saved result changed.')
                    print('REUSE',case_id,flush=True);continue
                if case is None:
                    case={'id':case_id,'sourceId':source_id,'style':style,'state':'queued'}
                    state['cases'].append(case)
                settings=transport_settings(archived[style])
                settings['image']='data:image/png;base64,'+base64.b64encode(model_path.read_bytes()).decode()
                validate(settings)
                write_json(folder/'request.json',{key:value for key,value in settings.items() if key!='image'})
                write_json(folder/'archived-profile.json',archived[style])
                write_json(state_path,state)
                if not case.get('job'):
                    deadline=time.monotonic()+1200
                    while request(port,'/api/generation?summary=1').get('processing'):
                        if time.monotonic()>deadline:raise TimeoutError('Local generation service remained busy.')
                        time.sleep(3)
                    case.update(job=request(port,'/api/generate',settings)['job'],state='running',startedAt=utc())
                    write_json(state_path,state)
                deadline=time.monotonic()+1200;last=None
                while True:
                    job=request(port,'/api/generation?job='+case['job']+'&summary=1').get('job')
                    if not job:raise ValueError('Saved job no longer exists; keep evidence and inspect before resuming.')
                    progress=(job.get('state'),job.get('step'))
                    if progress!=last:
                        print(case_id,*progress,flush=True);last=progress
                    if job.get('state')=='failed':
                        case.update(state='failed',error=job.get('error'));write_json(state_path,state)
                        raise ValueError(job.get('error'))
                    if job.get('state')=='complete':break
                    if time.monotonic()>deadline:raise TimeoutError('Generation exceeded the recorded 20-minute limit.')
                    time.sleep(2)
                result=request(port,'/api/generation?job='+case['job'])['job']['result']
                if result['effectivePrompt']!=archived[style]['effectivePrompt']:
                    raise ValueError('Actual generated prompt differs from the archived profile.')
                raw=base64.b64decode(result.pop('image').split(',')[1])
                raw_path=folder/'raw-flux.png';raw_path.write_bytes(raw)
                write_json(folder/'generation.json',result)
                line_valid=True
                try:require_line_candidate(raw_path)
                except ValueError:line_valid=False
                with Image.open(raw_path) as opened:before=np.asarray(opened.convert('RGB'))
                if before.shape[:2]!=(target[1],target[0]):raise ValueError('Unexpected output dimensions.')
                mask=cv2.cvtColor(before,cv2.COLOR_RGB2GRAY)<200
                regions=np.zeros(mask.shape,np.uint8);protected=np.zeros_like(mask);boxes=[]
                faces=feature_cache[source_id]
                if len(faces)==1:
                    coordinates=[[p.x,p.y,p.z] for p in faces[0]]
                    regions,protected,boxes=feature_regions(mask.shape,coordinates)
                if line_valid:
                    corrected,correction=correct(mask,evidence_cache[source_id],regions,protected)
                else:
                    corrected=mask.copy();correction={'state':'abstained','operations':[],'changedPixels':0,'reason':'Output did not pass the experimental line-art screening.'}
                changed=mask!=corrected
                if (changed & ((regions==0)|protected)).any():raise ValueError('Protected or out-of-region pixel changed.')
                after=before.copy();after[mask&~corrected]=255;after[~mask&corrected]=0
                if not np.array_equal(before[~changed],after[~changed]):raise ValueError('Unchanged pixels were modified.')
                layer=transparent(after);black_layer=np.zeros_like(layer);black_layer[:,:,3]=layer[:,:,3]
                black=np.repeat(after.min(axis=2)[:,:,None],3,axis=2)
                (folder/'corrected.png').write_bytes(png(after));(folder/'corrected-transparent.png').write_bytes(png(layer))
                (folder/'black-transparent.png').write_bytes(png(black_layer));(folder/'final-black.png').write_bytes(png(black))
                report={'version':'portrait-three-styles/1.0','source':source,
                    'sourceDimensions':list(source_size),'modelInputDimensions':list(target),
                    'modelInputSHA256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
                    'preprocessing':'EXIF orientation, RGB, Lanczos resize to model dimensions; no crop or generated enhancement',
                    'historicalPromptExact':True,'historicalGenerationProfile':f'front-{style}-generation.json',
                    'promptTransport':'Archived full prompt; preserve=false and controls=auto avoid duplicate additions only. Preservation instructions remain in the full prompt.',
                    'generation':result,'lineScreeningPassed':line_valid,'sourceFaceCount':len(faces),
                    'correction':correction,'regions':boxes,'automaticApproval':False,
                    'rawSHA256':hashlib.sha256(raw).hexdigest(),
                    'finalBlackSHA256':hashlib.sha256((folder/'final-black.png').read_bytes()).hexdigest()}
                result_faces=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(before))).face_landmarks
                report['rawFaceComparison']={'state':'unavailable','score':None}
                if len(faces)==len(result_faces)==1:
                    a,b=[np.array([[p.x,p.y] for p in face])*target for face in [faces[0],result_faces[0]]]
                    report['rawFaceComparison']=compare(a,b)
                write_json(folder/'procedure.json',report)
                case.update(state='complete',completedAt=utc(),rawSHA256=report['rawSHA256'],
                    finalBlackSHA256=report['finalBlackSHA256'],lineScreeningPassed=line_valid,
                    width=result['width'],height=result['height'],seconds=result['seconds'],
                    correctionOperations=len(correction['operations']))
                state['completed']=sum(c['state']=='complete' for c in state['cases']);write_json(state_path,state)
                print('SAVED',case_id,f"{state['completed']}/18",flush=True)
    state['state']='complete';state['finishedAt']=utc();write_json(state_path,state)
    print('BATCH_COMPLETE',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args()
    run(args.manifest,args.archive,args.output,args.port)
