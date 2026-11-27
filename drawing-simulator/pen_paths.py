"""Connected edge segments from OpenCV EdgeDrawing, before time-budget pruning."""
import base64, binascii, io, math, time
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

_DIRECTIONS=[(dy,dx) for dy in (-1,0,1) for dx in (-1,0,1) if dx or dy]


def _trace_skeleton(skeleton,spur=0):
    """Build neighbor links in NumPy, then trace with low-overhead Python lists."""
    height,width=skeleton.shape
    graph_started=time.perf_counter()
    active=skeleton>0
    ys,xs=np.nonzero(active)
    node_ids=(ys*width+xs).astype(np.int32)
    lookup=np.full(height*width,-1,np.int32)
    lookup[node_ids]=np.arange(len(node_ids),dtype=np.int32)
    adjacency=np.full((len(node_ids),8),-1,np.int32)
    for direction,(dy,dx) in enumerate(_DIRECTIONS):
        nx=xs+dx;ny=ys+dy
        valid=(nx>=0)&(nx<width)&(ny>=0)&(ny<height)
        source=np.flatnonzero(valid)
        neighbor=lookup[ny[valid]*width+nx[valid]]
        linked=neighbor>=0
        if dx and dy and np.any(linked):
            cross=(active[ys[valid][linked],nx[valid][linked]]|
                   active[ny[valid][linked],xs[valid][linked]])
            linked_indices=np.flatnonzero(linked)
            linked[linked_indices[cross]]=False
        adjacency[source[linked],direction]=neighbor[linked]
    degree=np.count_nonzero(adjacency>=0,axis=1)
    coordinates=np.column_stack((xs,ys)).astype(np.int32)
    neighbors={int(node):adjacency[node,adjacency[node]>=0].tolist()
               for node in np.flatnonzero(degree>0)}
    if spur:
        remove=set()
        for node,adj in neighbors.items():
            if len(adj)!=1:continue
            chain=[node];previous=node;current=adj[0];length=0
            while True:
                length+=math.hypot(*(coordinates[current]-coordinates[previous]))
                if length>spur:break
                if len(neighbors[current])!=2:
                    if len(neighbors[current])>2:remove.update(chain)
                    break
                chain.append(current);next_node=next(n for n in neighbors[current] if n!=previous)
                previous,current=current,next_node
        neighbors={node:[n for n in adj if n not in remove] for node,adj in neighbors.items() if node not in remove}
    graph_ms=(time.perf_counter()-graph_started)*1000
    trace_started=time.perf_counter()
    segments=[]
    def walk(start,next_node):
        line=[start];previous=start;current=next_node
        while True:
            visited.add(tuple(sorted((previous,current))));line.append(current);adj=neighbors[current]
            if current==start or len(adj)!=2:break
            other=adj[0] if adj[1]==previous else adj[1]
            if tuple(sorted((current,other))) in visited:break
            previous,current=current,other
        if len(line)>=2:segments.append(coordinates[line])
    visited=set()
    for degree_check in (True,False):
        for node,adj in neighbors.items():
            if degree_check and len(adj)==2:continue
            for other in adj:
                if tuple(sorted((node,other))) not in visited:walk(node,other)
    return segments,graph_ms,(time.perf_counter()-trace_started)*1000


def extract_paths(data,path_limit=10_000):
    # path_limit is set by trusted callers only; request data never raises it.
    profile_enabled=data.get('profileTimings',False)
    if not isinstance(profile_enabled,bool):raise ValueError('خيار قياس الزمن غير صحيح.')
    total_started=time.perf_counter();stage_started=total_started;timings={}
    def mark(stage):
        nonlocal stage_started
        now=time.perf_counter()
        if profile_enabled:timings[stage]=round((now-stage_started)*1000,3)
        stage_started=now
    encoded=data.get('image','')
    if not isinstance(encoded,str) or not encoded.startswith('data:image/png;base64,'):
        raise ValueError('يلزم مصدر PNG.')
    try:raw=base64.b64decode(encoded.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise ValueError('بيانات الصورة غير صحيحة.')
    if not 0<len(raw)<=6_000_000:raise ValueError('الصورة أكبر من الحد.')
    level=data.get('level',25)
    if isinstance(level,bool) or not isinstance(level,(int,float)) or not math.isfinite(level) or not 0<=level<=100:
        raise ValueError('درجة التفاصيل غير صحيحة.')
    try:
        with Image.open(io.BytesIO(raw),formats=('PNG',)) as source:
            if source.width*source.height>4_000_000:raise ValueError('مصدر المسارات أكبر من أربعة ملايين بكسل.')
            rgba=ImageOps.exif_transpose(source).convert('RGBA')
            background=Image.new('RGBA',rgba.size,'white');background.alpha_composite(rgba)
            image=np.asarray(background.convert('RGB'))
    except (OSError,UnidentifiedImageError):raise ValueError('تعذر قراءة المصدر.')
    mark('input_decode_and_validation')
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
    mark('grayscale_and_denoise')
    if not hasattr(cv2,'ximgproc') or not hasattr(cv2.ximgproc,'thinning'):
        raise ValueError('توليد المسارات يتطلب OpenCV contrib.')
    segments=[]
    if mode=='edges':
        if not hasattr(cv2.ximgproc,'createEdgeDrawing'):
            raise ValueError('تتبّع الحواف يتطلب OpenCV contrib مع EdgeDrawing.')
        detector=cv2.ximgproc.createEdgeDrawing();parameters=detector.Params()
        parameters.GradientThresholdValue=round(60-detail*.55)
        parameters.AnchorThresholdValue=4;parameters.ScanInterval=1
        parameters.MinPathLength=round(minimum)
        parameters.Sigma=1.3;parameters.PFmode=False
        detector.setParams(parameters);detector.detectEdges(gray)
        segments=detector.getSegments()
    mark('edge_detection')
    routing_stats={}
    if mode in ('centerline','ink'):
        # For existing dark ink on light paper, not direct photographic shading.
        threshold=data.get('inkThreshold',0);component_min=data.get('componentMin',0);spur=data.get('spurLength',0)
        for name,value,maximum in [('inkThreshold',threshold,245),('componentMin',component_min,150),('spurLength',spur,20)]:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=maximum:raise ValueError('إعداد الخط المركزي غير صحيح: '+name)
        _,binary=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY_INV+(cv2.THRESH_OTSU if threshold==0 else 0))
        mark('threshold')
        if component_min:
            _,labels,stats,_=cv2.connectedComponentsWithStats(binary,8)
            small=np.where(stats[:,cv2.CC_STAT_AREA]<component_min)[0];small=small[small!=0];binary[np.isin(labels,small)]=0
        if mode=='ink':
            from ink_fill_paths import copy_ink
            paths=copy_ink(binary)
            return {'paths':paths,'width':gray.shape[1],'height':gray.shape[0],'method':'continuous binary ink copy','inkCopyStrokes':len(paths),'inkPixels':int((binary>0).sum()),'inputPoints':sum(len(p) for p in paths),'outputPoints':sum(len(p) for p in paths)}
        skeleton=cv2.ximgproc.thinning(binary)
        mark('thinning')
        # Trace a skeleton graph into open centerlines; no contour around ink width.
        # Prune terminal spurs only; preserve closed loops and isolated strokes.
        # Opt-in: can remove small facial details, so the default stays zero.
        segments,graph_ms,trace_ms=_trace_skeleton(skeleton,float(spur))
        if profile_enabled:
            timings['graph_construction']=round(graph_ms,3)
            timings['graph_trace']=round(trace_ms,3)
        stage_started=time.perf_counter()
        mark('spur_pruning')
        routing=data.get('junctionRouting',True)
        if not isinstance(routing,bool):raise ValueError('خيار تتبع التقاطعات غير صحيح.')
        if routing:
            from centerline_routing import route_junctions
            segments,routing_stats=route_junctions(segments)
        mark('junction_routing')
        segments=[segment for segment in segments if len(segment)>=minimum]
    result=[]
    for segment in segments:
        # Approximation preserves each connected segment instead of stopping at junctions.
        points=(cv2.approxPolyDP(np.asarray(segment,dtype=np.int32),tolerance,False) if tolerance else np.asarray(segment,dtype=np.int32)).reshape(-1,2)
        if len(points)>1:result.append(points.tolist())
    if len(result)>path_limit:raise ValueError(f'الصورة شديدة التعقيد؛ الحد {path_limit:,} مسار.')
    mark('path_simplification_and_limits')
    output={'paths':result,'width':gray.shape[1],'height':gray.shape[0],'method':'OpenCV '+('EdgeDrawing' if mode=='edges' else 'thinning + shared-junction routing'),'inputPoints':sum(len(p) for p in segments),'outputPoints':sum(len(p) for p in result),**routing_stats}
    if profile_enabled:
        timings['total']=round((time.perf_counter()-total_started)*1000,3);output['profileTimingsMs']=timings
    return output
