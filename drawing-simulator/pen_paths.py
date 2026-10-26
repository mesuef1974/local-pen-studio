"""Connected edge segments from OpenCV EdgeDrawing, before time-budget pruning."""
import base64, binascii, io, math
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

def extract_paths(data):
    encoded=data.get('image','')
    if not isinstance(encoded,str) or not encoded.startswith('data:image/png;base64,'):
        raise ValueError('يلزم مصدر PNG.')
    try:raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=5_000_000:raise ValueError('الصورة أكبر من الحد.')
    level=data.get('level',25)
    if isinstance(level,bool) or not isinstance(level,(int,float)) or not math.isfinite(level) or not 0<=level<=100:
        raise ValueError('درجة التفاصيل غير صحيحة.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>4_000_000:raise ValueError('مصدر المسارات أكبر من أربعة ملايين بكسل.')
            image=np.asarray(ImageOps.exif_transpose(source).convert('RGB'))
    except (OSError,UnidentifiedImageError):raise ValueError('تعذر قراءة المصدر.')
    if not hasattr(cv2,'ximgproc') or not hasattr(cv2.ximgproc,'createEdgeDrawing'):
        raise ValueError('توليد المسارات يتطلب OpenCV contrib مع EdgeDrawing.')
    tolerance=data.get('tolerance',.35)
    if isinstance(tolerance,bool) or not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or not 0<=tolerance<=2.5:raise ValueError('سماحية الاختصار غير صحيحة.')
    detail=data.get('detail',60);minimum=data.get('minLength',12)
    smoothing=data.get('lineDenoise',35);mode=data.get('lineMode','edges')
    if isinstance(smoothing,bool) or not isinstance(smoothing,(int,float)) or not math.isfinite(smoothing) or not 0<=smoothing<=100:raise ValueError('تنعيم الخطوط غير صحيح.')
    if mode not in ['edges','centerline','ink']:raise ValueError('أسلوب الخطوط غير معروف.')
    if isinstance(detail,bool) or not isinstance(detail,(int,float)) or not 0<=detail<=100:raise ValueError('درجة حساسية الحواف غير صحيحة.')
    if isinstance(minimum,bool) or not isinstance(minimum,(int,float)) or not 2<=minimum<=25:raise ValueError('الحد الأدنى للمسار غير صحيح.')
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    if smoothing:gray=cv2.bilateralFilter(gray,9,float(smoothing),25)
    detector=cv2.ximgproc.createEdgeDrawing();parameters=detector.Params()
    parameters.GradientThresholdValue=round(60-detail*.55)
    parameters.AnchorThresholdValue=4;parameters.ScanInterval=1
    parameters.MinPathLength=round(minimum)
    parameters.Sigma=1.3;parameters.PFmode=False
    detector.setParams(parameters);detector.detectEdges(gray)
    segments=detector.getSegments()
    routing_stats={}
    if mode in ('centerline','ink'):
        # For existing dark ink on light paper, not direct photographic shading.
        threshold=data.get('inkThreshold',0);component_min=data.get('componentMin',0);spur=data.get('spurLength',0)
        for name,value,maximum in [('inkThreshold',threshold,245),('componentMin',component_min,150),('spurLength',spur,20)]:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=maximum:raise ValueError('إعداد الخط المركزي غير صحيح: '+name)
        _,binary=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY_INV+(cv2.THRESH_OTSU if threshold==0 else 0))
        if component_min:
            _,labels,stats,_=cv2.connectedComponentsWithStats(binary,8)
            small=np.where(stats[:,cv2.CC_STAT_AREA]<component_min)[0];small=small[small!=0];binary[np.isin(labels,small)]=0
        if mode=='ink':
            from ink_fill_paths import copy_ink
            paths=copy_ink(binary)
            return {'paths':paths,'width':gray.shape[1],'height':gray.shape[0],'method':'continuous binary ink copy','inkCopyStrokes':len(paths),'inkPixels':int((binary>0).sum()),'inputPoints':sum(len(p) for p in paths),'outputPoints':sum(len(p) for p in paths)}
        skeleton=cv2.ximgproc.thinning(binary)
        # Trace a skeleton graph into open centerlines; no contour around ink width.
        ys,xs=np.where(skeleton>0);nodes={int(y)*gray.shape[1]+int(x) for y,x in zip(ys,xs)};w=gray.shape[1]
        neighbors={}
        for node in nodes:
            y,x=divmod(node,w);adj=[]
            for dy in [-1,0,1]:
                for dx in [-1,0,1]:
                    if not(dx or dy):continue
                    if not(0<=x+dx<w and 0<=y+dy<gray.shape[0]):continue
                    other=(y+dy)*w+x+dx
                    if other not in nodes:continue
                    if dx and dy and (y*w+x+dx in nodes or (y+dy)*w+x in nodes):continue
                    adj.append(other)
            neighbors[node]=adj
        # Prune terminal spurs only; preserve closed loops and isolated strokes.
        # Opt-in: can remove small facial details, so the default stays zero.
        if spur:
            remove=set()
            for node,adj in neighbors.items():
                if len(adj)!=1:continue
                chain=[node];previous=node;current=adj[0];length=0
                while True:
                    length+=math.hypot(current%w-previous%w,current//w-previous//w)
                    if length>spur:break
                    if len(neighbors[current])!=2:
                        if len(neighbors[current])>2:remove.update(chain)
                        break
                    chain.append(current);next_node=next(n for n in neighbors[current] if n!=previous);previous,current=current,next_node
            neighbors={node:[n for n in adj if n not in remove] for node,adj in neighbors.items() if node not in remove}
        visited=set();segments=[]
        def walk(start,next_node):
            line=[start];previous=start;current=next_node
            while True:
                visited.add(tuple(sorted((previous,current))));line.append(current)
                adj=neighbors[current]
                if current==start or len(adj)!=2:break
                other=adj[0] if adj[1]==previous else adj[1]
                if tuple(sorted((current,other))) in visited:break
                previous,current=current,other
            if len(line)>=2:segments.append(np.array([[v%w,v//w] for v in line],np.int32))
        for degree_check in [True,False]:
            for node,adj in neighbors.items():
                if degree_check and len(adj)==2:continue
                for other in adj:
                    if tuple(sorted((node,other))) not in visited:walk(node,other)
        routing=data.get('junctionRouting',True)
        if not isinstance(routing,bool):raise ValueError('خيار تتبع التقاطعات غير صحيح.')
        if routing:
            from centerline_routing import route_junctions
            segments,routing_stats=route_junctions(segments)
        segments=[segment for segment in segments if len(segment)>=minimum]
    result=[]
    for segment in segments:
        # Approximation preserves each connected segment instead of stopping at junctions.
        points=(cv2.approxPolyDP(np.asarray(segment,dtype=np.int32),tolerance,False) if tolerance else np.asarray(segment,dtype=np.int32)).reshape(-1,2)
        if len(points)>1:result.append(points.tolist())
    if len(result)>6000:raise ValueError('الصورة شديدة التعقيد؛ خفّف الضوضاء أو قلل التفاصيل.')
    return {'paths':result,'width':gray.shape[1],'height':gray.shape[0],'method':'OpenCV '+('EdgeDrawing' if mode=='edges' else 'thinning + shared-junction routing'),'inputPoints':sum(len(p) for p in segments),'outputPoints':sum(len(p) for p in result),**routing_stats}
