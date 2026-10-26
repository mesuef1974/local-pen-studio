"""Reproducible geometry fixture benchmark, not a portrait-quality evaluation."""
from pathlib import Path
import sys,io,json,base64,math,subprocess,tempfile,hashlib
import cv2,numpy as np
from PIL import Image
from pen_paths import extract_paths
APP=Path(__file__).resolve().parent
ROOT=APP/'reference-benchmark'
w,h=Image.open(ROOT/'reference.png').size
image=np.array(Image.open(ROOT/'reference.png').convert('RGB'))
features=json.loads((ROOT/'reference-definition.json').read_text(encoding='utf-8'))
truth=np.zeros((h,w),np.uint8);masks={}
for feature in features:
 mask=np.zeros((h,w),np.uint8)
 cv2.polylines(mask,[np.rint(feature['points']).astype(np.int32)],False,255,1,cv2.LINE_8)
 masks[feature['id']]=mask>0;truth|=mask
expected=cv2.connectedComponents(truth,8)[0]-1
buffer=io.BytesIO();Image.fromarray(image).save(buffer,format='PNG')
url='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
node="""const fs=require('fs'),vm=require('vm');const i=JSON.parse(fs.readFileSync(process.argv[1]));let result;const c={self:{postMessage:r=>result=r},Math,Float32Array,Uint8Array,Map,Set};vm.createContext(c);c.importScripts=()=>vm.runInContext(fs.readFileSync('path-refinement.js','utf8'),c);vm.runInContext(fs.readFileSync('trace-worker.js','utf8'),c);c.self.onmessage({data:{...i,pixels:new Uint8Array(i.pixels)}});if(result.error)throw Error(result.error);process.stdout.write(JSON.stringify(result));"""
length=lambda paths:sum(sum(math.dist(a,b) for a,b in zip(p,p[1:])) for p in paths)
results=[]
for mode in ['edges','centerline']:
 extracted=extract_paths({'image':url,'detail':60,'minLength':2,'lineDenoise':0,'level':100,'lineMode':mode,'tolerance':0})
 args={'id':1,'width':w,'height':h,'pixels':np.concatenate([image,np.full((h,w,1),255,np.uint8)],2).reshape(-1).tolist(),'basePaths':extracted['paths'],'executionLevel':100,'shading':False,'protectFeatures':False,'featureRegion':None,'epsilon':0,'joinGapMm':0,'curveSmoothMm':0,'paper':{'width':210,'height':297,'margin':15},'penWidth':.5}
 with tempfile.TemporaryDirectory() as t:
  input_file=Path(t)/'input.json';input_file.write_text(json.dumps(args))
  output=json.loads(subprocess.run(['node','-e',node,str(input_file)],cwd=APP,capture_output=True,text=True,check=True).stdout)
 paths=output['paths'];render=np.zeros((h,w),np.uint8);counts=np.zeros((h,w),np.uint16);preview=np.full((h,w,3),255,np.uint8)
 for path in paths:
  points=np.rint(path).astype(np.int32);mask=np.zeros((h,w),np.uint8)
  cv2.polylines(mask,[points],False,1,1,cv2.LINE_8);render|=mask;counts+=mask
  cv2.polylines(preview,[points],False,(30,55,48),5,cv2.LINE_AA)
 cv2.imwrite(str(ROOT/(mode+'-render.png')),preview)
 dt_truth=cv2.distanceTransform((truth==0).astype(np.uint8),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
 dt_render=cv2.distanceTransform((render==0).astype(np.uint8),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
 precision=float((dt_truth[render>0]<=2).mean());recall=float((dt_render[truth>0]<=2).mean())
 components=cv2.connectedComponents(render,8)[0]-1;ratio=length(paths)/length([f['points'] for f in features])
 per_feature={key:float((dt_render[mask]<=2).mean()) for key,mask in masks.items()}
 passed=precision>=.95 and recall>=.95 and components==expected and .85<=ratio<=1.15 and min(per_feature.values())>=.9
 r={'mode':mode,'strokeCount':len(paths),'precisionWithin2px':precision,'recallWithin2px':recall,'precisionWithin4px':float((dt_truth[render>0]<=4).mean()),'recallWithin4px':float((dt_render[truth>0]<=4).mean()),'components':components,'expectedComponents':int(expected),'lengthRatio':ratio,'overlapPixelFraction':float((counts[render>0]>1).mean()),'featureRecall':per_feature,'pass':bool(passed)}
 results.append(r);(ROOT/(mode+'-paths.json')).write_text(json.dumps({**r,'paths':paths},indent=2))
 markup=''.join('<path d="'+' '.join(('M' if i==0 else 'L')+f'{x:.3f} {y:.3f}' for i,(x,y) in enumerate(path))+'"/>' for path in paths)
 (ROOT/(mode+'-output.svg')).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><g fill="none" stroke="black" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">{markup}</g></svg>')
 print(mode,'PASS' if passed else 'FAIL',len(paths),'strokes','recall2',round(recall,6),'length ratio',round(ratio,4))
(ROOT/'results.json').write_text(json.dumps(results,indent=2))
(ROOT/'provenance.json').write_text(json.dumps({'OpenCV':cv2.__version__,'sourceSHA256':hashlib.sha256((ROOT/'reference.png').read_bytes()).hexdigest(),'settings':{'level':100,'minLength':2,'lineDenoise':0,'detail':60,'backendTolerance':0,'workerTolerance':0,'shading':False,'joining':False,'smoothing':False,'protection':False,'timeLimit':False},'limits':'Synthetic separated strokes only. Actual Python extractor and JS worker; static rasterization of returned geometry, no mechanical simulation.'},indent=2))
