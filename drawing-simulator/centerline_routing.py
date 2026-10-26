"""Pair unambiguous continuations at identical skeleton junctions.

This changes pen lifts only: no invented bridge, smoothing or edge deletion.
"""
from collections import defaultdict
import math
import numpy as np

def route_junctions(segments, maximum_turn=40, lookahead=5):
    paths=[np.asarray(p,dtype=np.int32).reshape(-1,2).tolist() for p in segments if len(p)>1]
    incident=defaultdict(list)
    directions={}
    for index,path in enumerate(paths):
        if path[0]==path[-1]:continue
        for side in (0,1):
            points=path if side==0 else path[::-1]
            origin=points[0];travel=0;target=points[-1]
            for previous,point in zip(points,points[1:]):
                travel+=math.dist(previous,point);target=point
                if travel>=lookahead:break
            dx=target[0]-origin[0];dy=target[1]-origin[1];length=math.hypot(dx,dy)
            if not length:continue
            port=(index,side);directions[port]=(dx/length,dy/length)
            incident[tuple(origin)].append(port)
    pairs={};limit=-math.cos(math.radians(maximum_turn))
    for ports in incident.values():
        if len(ports)<2:continue
        candidates=[];scores=defaultdict(list)
        for i,a in enumerate(ports):
            for b in ports[i+1:]:
                if a[0]==b[0]:continue
                score=sum(x*y for x,y in zip(directions[a],directions[b]))
                if score<=limit:
                    candidates.append((score,a,b));scores[a].append(score);scores[b].append(score)
        for score,a,b in sorted(candidates):
            if a in pairs or b in pairs:continue
            # Avoid arbitrary routing between equally plausible branches.
            if any(len(scores[p])>1 and sorted(scores[p])[1]-sorted(scores[p])[0]<.08 for p in (a,b)):continue
            pairs[a]=b;pairs[b]=a
    visited=set();routed=[]
    starts=[(i,side) for i in range(len(paths)) for side in (0,1) if (i,side) not in pairs]
    starts.extend((i,0) for i in range(len(paths)))
    for index,side in starts:
        if index in visited:continue
        line=[];port=(index,side)
        while port[0] not in visited:
            index,side=port;visited.add(index)
            points=paths[index] if side==0 else paths[index][::-1]
            if line:
                assert line[-1]==points[0]
                line.extend(points[1:])
            else:line.extend(points)
            continuation=pairs.get((index,1-side))
            if continuation is None:break
            port=continuation
        routed.append(np.asarray(line,dtype=np.int32))
    return routed,{'junctionPairs':len(pairs)//2,'segmentsBeforeRouting':len(paths),'segmentsAfterRouting':len(routed)}
