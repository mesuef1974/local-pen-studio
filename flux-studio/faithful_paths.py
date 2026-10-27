"""Fixed-pen reconstruction: all centerlines plus pen-aware interior contour fills."""
import base64
import io
import math
import sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from path_fidelity import decode_image,ink_mask,validate_physics,measure,render_svg


def sample(field,points):
    if len(points)>16000:return np.concatenate([sample(field,points[i:i+16000]) for i in range(0,len(points),16000)])
    return cv2.remap(field,points[:,0].astype(np.float32).reshape(1,-1),
        points[:,1].astype(np.float32).reshape(1,-1),cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,borderValue=0).reshape(-1)


def refine_contour(points,distance,gx,gy,level):
    points=points.astype(np.float64)
    for _ in range(3):
        values=sample(distance,points);dx=sample(gx,points);dy=sample(gy,points)
        denominator=np.maximum(dx*dx+dy*dy,.05)
        amount=np.clip((values-level)/denominator,-1.,1.)
        points-=np.column_stack((dx*amount,dy*amount))
    return points


def connect_fills(fills,distance,radius):
    """Join closed offset loops only through safe pen centers, never through a hole."""
    if not fills:return []
    _,regions=cv2.connectedComponents((distance>=radius+.35).astype(np.uint8),8)
    groups={}
    for points in fills:
        center=np.rint(points[0]).astype(int);x,y=center
        label=int(regions[min(max(y,0),regions.shape[0]-1),min(max(x,0),regions.shape[1]-1)])
        groups.setdefault(label,[]).append(points)
    merged=[]
    for label,loops in groups.items():
        if not label:merged.extend(loops);continue
        remaining=loops[:];current=remaining.pop(0).tolist()
        while remaining:
            end=np.asarray(current[-1]);best=None
            # Closed-loop rotation avoids forcing a pen lift at an arbitrary contour start.
            for index,loop in enumerate(remaining):
                distances=np.sum((loop[:-1]-end)**2,axis=1)
                if not len(distances):continue
                vertex=int(np.argmin(distances));length=float(math.sqrt(distances[vertex]))
                if length>max(4.,radius*6):continue
                bridge=np.linspace(end,loop[vertex],max(2,math.ceil(length*2)+1))
                if np.min(sample(distance,bridge))<radius+.25:continue
                if best is None or length<best[0]:best=(length,index,vertex)
            if best is None:merged.append(np.asarray(current));current=remaining.pop(0).tolist();continue
            _,index,vertex=best;loop=remaining.pop(index)
            rotated=np.vstack([loop[vertex:-1],loop[:vertex+1]])
            current.extend(rotated.tolist())
        merged.append(np.asarray(current))
    return merged


def covered_seed(path,fill_distance,pad,factor,radius):
    samples=[]
    for a,b in zip(path,path[1:]):
        length=math.dist(a,b)*factor
        samples.append(np.linspace(a,b,max(2,math.ceil(length*2)+1)))
    points=np.vstack(samples)
    points=(points+pad+.5)*factor-.5
    return bool(np.min(sample(fill_distance,points))>=radius+.71)


def extract(data):
    rgb,gray=decode_image(data.get('image'));scale,pen=validate_physics(data)
    height,width=gray.shape;mask,threshold=ink_mask(gray,data.get('inkThreshold',0))
    if np.count_nonzero(mask)>gray.size*.45:raise ValueError('مساحة الحبر واسعة جدًا لهذا الوضع الدقيق؛ استخدم رسمًا خطيًا بخلفية بيضاء.')
    engine=str(Path(__file__).resolve().parent.parent/'drawing-simulator')
    if engine not in sys.path:sys.path.insert(0,engine)
    from pen_paths import extract_paths
    buffer=io.BytesIO();Image.fromarray(255-mask).save(buffer,format='PNG')
    seed=extract_paths({'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
        'lineMode':'centerline','lineDenoise':0,'inkThreshold':127,'tolerance':0,
        'componentMin':0,'spurLength':0,'minLength':2,'junctionRouting':True})
    paths=seed['paths']
    # Preserve disconnected dots and compact components that thinning reduces to one pixel.
    count,labels,stats,centroids=cv2.connectedComponentsWithStats(mask,8)
    represented=set()
    for path in paths:
        for x,y in path:represented.add(int(labels[int(y),int(x)]))
    dots=0
    for label in range(1,count):
        if label in represented:continue
        left,top,cw,ch,_=stats[label]
        ys,xs=np.where(labels[top:top+ch,left:left+cw]==label);xs+=left;ys+=top
        if not len(xs):continue
        x=float(xs[len(xs)//2]);y=float(ys[len(ys)//2]);step=.001 if x<width-1 else -.001
        paths.append([[x,y],[x+step,y]]);dots+=1
    if len(paths)>6000 or sum(len(path) for path in paths)>400_000:
        raise ValueError('تجاوزت العلامات والخطوط حد التعقيد؛ لم تُحذف أي تفاصيل تلقائيًا.')
    baseline=measure(rgb,gray,mask,paths,scale,pen,include_images=False)
    factor=min(8,max(1,int(math.sqrt(40_000_000/(width*height)))))
    work=cv2.resize(mask,(width*factor,height*factor),interpolation=cv2.INTER_NEAREST)
    # Padding makes distance-to-background valid even if a line touches the frame.
    padded=cv2.copyMakeBorder(work,1,1,1,1,cv2.BORDER_CONSTANT,value=0)
    distance=cv2.distanceTransform(padded,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)[1:-1,1:-1]
    radius=pen/scale*factor/2
    level=radius+.5;step=max(1.,pen/scale*factor*.8)
    gx=cv2.Sobel(distance,cv2.CV_32F,1,0,ksize=3,scale=1/8)
    gy=cv2.Sobel(distance,cv2.CV_32F,0,1,ksize=3,scale=1/8)
    fills=[]
    maximum=float(distance.max()) if distance.size else 0
    if maximum>level+step*64:raise ValueError('مساحات الحبر تحتاج تمريرات كثيرة جدًا؛ قلل مساحة التعبئة أو اختر قلمًا أعرض.')
    while level<=maximum:
        interior=(distance>=level).astype(np.uint8)*255
        contours,_=cv2.findContours(interior,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            points=refine_contour(contour.reshape(-1,2),distance,gx,gy,level)
            if len(points)==1:
                points=np.vstack([points,points+[.001,0]])
            elif np.linalg.norm(points[0]-points[-1])>0:
                points=np.vstack([points,points[0]])
            fills.append(points)
        if len(fills)+len(paths)>12_000 or sum(len(p) for p in fills)>500_000:
            raise ValueError('تجاوزت خطة المطابقة حد التعقيد؛ لم تُحذف أي خطوط تلقائيًا.')
        level+=step
    fills=connect_fills(fills,distance,radius)
    fill_paths=[]
    for points in fills:
        points=(points+.5)/factor-.5
        points[:,0]=np.clip(points[:,0],-.5,width-.5);points[:,1]=np.clip(points[:,1],-.5,height-.5)
        fill_paths.append(points.tolist())
    retained=paths
    if fill_paths:
        raster,pad,audit_factor=render_svg(fill_paths,width,height,pen/scale,upscale=factor)
        filled=(raster<128).astype(np.uint8)*255
        fill_distance=cv2.distanceTransform(filled,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        retained=[path for path in paths if not covered_seed(path,fill_distance,pad,audit_factor,pen/scale*audit_factor/2)]
    candidate=retained+fill_paths
    if len(candidate)>6000 or sum(len(p) for p in candidate)>400_000:raise ValueError('تجاوزت خطة المطابقة حد التعقيد؛ لم تُحذف خطوط.')
    final=measure(rgb,gray,mask,candidate,scale,pen)
    contours_added=len(fill_paths)
    # Never silently choose a fill that worsens the measured mask agreement.
    if final['inkIoU']+0.01<baseline['inkIoU']:
        contours_added=0;final=measure(rgb,gray,mask,paths,scale,pen)
    else:paths=candidate
    final['baselineCenterline']=baseline
    final['planningUpscale']=factor
    final['threshold']=threshold
    return {'paths':paths,'width':width,'height':height,
        'method':'physical-pen centerlines + interior contour filling',
        'inputPoints':seed['inputPoints'],'outputPoints':sum(len(path) for path in paths),
        'fillPasses':contours_added,'isolatedMarksPreserved':dots,'fidelity':final}
