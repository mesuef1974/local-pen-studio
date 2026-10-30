"""Local human-image features. Raw errors are not calibrated similarity percentages."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

VERSION = 'human-geometry/1.0'
MODELS = Path.home()/'.codex/models/flux-quality'
HASHES = {'face_landmarker.task': '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff',
          'pose_landmarker_lite.task': '59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a'}


def verified_model(name):
    path = MODELS/name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[name]:
        raise ValueError('نموذج القياس مفقود أو بصمته غير مطابقة: '+name)
    return str(path)


def detect(rgb):
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    with vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=verified_model('face_landmarker.task')),
            num_faces=2, min_face_detection_confidence=.7, min_face_presence_confidence=.7)) as model:
        faces = model.detect(image).face_landmarks
    with vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=verified_model('pose_landmarker_lite.task')),
            num_poses=2, output_segmentation_masks=True,
            min_pose_detection_confidence=.7, min_pose_presence_confidence=.7)) as model:
        pose = model.detect(image)
    frame_scale=np.array([rgb.shape[1],rgb.shape[0]])/max(rgb.shape[:2])
    face = np.array([[p.x,p.y] for p in faces[0]])*frame_scale if len(faces)==1 else None
    points = np.array([[p.x,p.y] for p in pose.pose_landmarks[0]])*frame_scale if len(pose.pose_landmarks)==1 else None
    confidence = np.array([min(p.presence,p.visibility) for p in pose.pose_landmarks[0]]) if points is not None else None
    mask = binary_mask(pose.segmentation_masks[0].numpy_view()) if points is not None and pose.segmentation_masks else None
    return {'face':face,'pose':points,'visibility':confidence,'mask':mask,
            'faceCount':len(faces),'poseCount':len(pose.pose_landmarks)}


def binary_mask(array):
    array=np.asarray(array)
    if array.ndim==3 and array.shape[-1]==1:array=array[:,:,0]
    if array.ndim!=2:raise ValueError('أبعاد قناع الكاشف غير مدعومة.')
    return array>.5


def normalized(points):
    low=points.min(axis=0);span=points.max(axis=0)-low
    if min(span)<1e-5:raise ValueError('معالم غير صالحة للتطبيع.')
    # Translation and independent frame-size normalization only; never rotate the head.
    return (points-low)/max(span)


def mask_box(mask):
    y,x=np.where(mask)
    if len(x)<16:raise ValueError('قناع الموضوع غير كافٍ.')
    return np.array([x.min()/mask.shape[1],y.min()/mask.shape[0],
                     (x.max()+1)/mask.shape[1],(y.max()+1)/mask.shape[0]])


def silhouette(mask):
    y,x=np.where(mask)
    crop=mask[y.min():y.max()+1,x.min():x.max()+1].astype('uint8')
    h,w=crop.shape;factor=256/max(h,w);nw,nh=max(1,round(w*factor)),max(1,round(h*factor))
    canvas=np.zeros((256,256),dtype='uint8');left,top=(256-nw)//2,(256-nh)//2
    canvas[top:top+nh,left:left+nw]=cv2.resize(crop,(nw,nh),interpolation=cv2.INTER_NEAREST)
    return canvas>0


def compare_features(a,b):
    components = {key:{'weight':weight,'score':None,'state':'unavailable'}
                  for key,weight in [('face',.5),('outlinePose',.3),('compositionCrop',.2)]}
    face=components['face']
    if a['face'] is not None and b['face'] is not None:
        face.update(state='raw_only',raw={'normalizedLandmarkRMS':float(np.sqrt(np.mean(np.sum((normalized(a['face'])-normalized(b['face']))**2,axis=1))))},
                    confidence={'probability':None,'detectorThreshold':.7,'calibrated':False})
    else:face['reason']='يلزم وجه واحد قابل للكشف في كل صورة؛ لا يثبت الكشف هوية الشخص.'
    if a['mask'] is not None and b['mask'] is not None and a['mask'].sum()>=16 and b['mask'].sum()>=16:
        am,bm=silhouette(a['mask']),silhouette(b['mask'])
        box_a,box_b=mask_box(a['mask']),mask_box(b['mask'])
        common=(a['visibility']>=.7)&(b['visibility']>=.7)
        components['compositionCrop'].update(state='raw_only',raw={'frameBoxMeanAbsoluteError':float(np.abs(box_a-box_b).mean()),
            'sourceBox':box_a.tolist(),'resultBox':box_b.tolist(),
            'sourceTouchesFrame':bool(np.any(box_a[:2]<=.01) or np.any(box_a[2:]>=.99)),
            'resultTouchesFrame':bool(np.any(box_b[:2]<=.01) or np.any(box_b[2:]>=.99))},
            confidence={'probability':None,'calibrated':False,'basis':'human pose segmentation; mask not independently validated'})
        if common.sum()>=8:
            pa,pb=normalized(a['pose'][common]),normalized(b['pose'][common])
            components['outlinePose'].update(state='raw_only',raw={
                'shapeNormalizedMaskIoU':float((am&bm).sum()/(am|bm).sum()),
                'normalizedPoseRMS':float(np.sqrt(np.mean(np.sum((pa-pb)**2,axis=1)))),
                'commonVisibleJoints':int(common.sum())},confidence={'minimumObservedVisibility':float(np.minimum(a['visibility'][common],b['visibility'][common]).min()),'calibrated':False})
        else:components['outlinePose']['reason']='نقاط وضعية موثوقة مشتركة أقل من ثمانٍ.'
    else:
        for key in ['outlinePose','compositionCrop']:components[key]['reason']='قناع شخص واحد غير متاح في الصورتين؛ الملف الحالي مخصص للبشر.'
    return {'version':VERSION,'profile':'human-single-subject','score':None,'state':'uncalibrated',
            'reason':'المعايرة والتقييم البشري المستقل لم يكتملَا؛ لا تُعرض نسبة كلية أو يعاد توزيع الأوزان.',
            'components':components,'background':'excluded by subject mask; invariance still requires independent validation',
            'automaticApproval':False}


if __name__=='__main__':
    import sys
    from path_fidelity import decode_image
    payload=json.load(sys.stdin)
    images=[decode_image(payload[key])[0] for key in ['source','result']]
    original_shapes=[list(image.shape[:2][::-1]) for image in images]
    images=[cv2.resize(image,(max(1,round(image.shape[1]*1024/max(image.shape[:2]))),max(1,round(image.shape[0]*1024/max(image.shape[:2])))),interpolation=cv2.INTER_AREA) if max(image.shape[:2])>1024 else image for image in images]
    features=[detect(image) for image in images]
    result=compare_features(*features)
    result['detections']=[{'faces':x['faceCount'],'poses':x['poseCount']} for x in features]
    from importlib.metadata import version
    result['provenance']={'mediapipe':version('mediapipe'),'opencv':cv2.__version__,'modelsSHA256':HASHES,
        'originalDimensions':original_shapes,'analysisDimensions':[list(image.shape[:2][::-1]) for image in images],
        'preprocessing':'EXIF transpose; alpha composited on white; RGB; max side 1024, area resize; no rotation alignment',
        'sourceHash':hashlib.sha256(payload['source'].encode()).hexdigest(),'resultHash':hashlib.sha256(payload['result'].encode()).hexdigest()}
    print(json.dumps(result))
