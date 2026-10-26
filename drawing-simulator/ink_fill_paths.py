"""Continuous pen filling on ink pixels only. No invented off-ink bridges."""
import cv2
import numpy as np
from collections import defaultdict,deque

def scan_runs(binary):
    paths=[];active=[];height,width=binary.shape
    for y in range(height):
        edges=np.diff(np.r_[False,binary[y]>0,False].astype(np.int8));next_active=[];used=set()
        for left,right in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)-1):
            left=int(left);right=int(right);best=None
            for index in active:
                if index in used:continue
                previous=paths[index][-1];target=min(right,max(left,previous[0]));dx=target-previous[0]
                if abs(dx)>1:continue
                cost=abs(dx)
                if best is None or cost<best[0]:best=(cost,index,target)
            if best is None:
                line=[[left,y],[right,y]];paths.append(line);index=len(paths)-1
            else:
                _,index,target=best;line=paths[index];used.add(index)
                a,b=(left,right) if abs(target-left)<abs(target-right) else (right,left)
                line.append([target,y])
                if target!=a:line.append([a,y])
                if a!=b:line.append([b,y])
            next_active.append(index)
        active=next_active
    return paths

def connect_on_ink(paths,binary,maximum_steps=8):
    """Merge runs only by retracing existing black pixels, with bounded work."""
    height,width=binary.shape;parents=list(range(len(paths)));locations=defaultdict(list);pairs={};bridges={}
    def root(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,path in enumerate(paths):
        for side in (0,1):locations[tuple(path[0 if side==0 else -1])].append((i,side))
    for index,path in enumerate(paths):
        for side in (0,1):
            port=(index,side)
            if port in pairs:continue
            start=tuple(path[0 if side==0 else -1]);queue=deque([(start,0)]);previous={start:None};found=None
            while queue:
                (x,y),depth=queue.popleft()
                for target in locations.get((x,y),()):
                    if target not in pairs and root(target[0])!=root(index):found=(target,(x,y));break
                if found or depth==maximum_steps: 
                    if found:break
                    continue
                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    node=(x+dx,y+dy)
                    if 0<=node[0]<width and 0<=node[1]<height and binary[node[1],node[0]] and node not in previous:
                        previous[node]=(x,y);queue.append((node,depth+1))
            if found:
                target,node=found;bridge=[]
                while node is not None:bridge.append(list(node));node=previous[node]
                bridge.reverse();pairs[port]=target;pairs[target]=port;bridges[port]=bridge;bridges[target]=bridge[::-1]
                parents[root(index)]=root(target[0])
    output=[];visited=set()
    starts=[(i,side) for i in range(len(paths)) for side in (0,1) if (i,side) not in pairs]
    for start in starts:
        if start[0] in visited:continue
        line=[];port=start
        while port[0] not in visited:
            i,side=port;visited.add(i);points=paths[i] if side==0 else paths[i][::-1]
            line.extend(points if not line else points[1:]);end=(i,1-side)
            if end not in pairs:break
            line.extend(bridges[end][1:]);port=pairs[end]
        output.append(line)
    assert len(visited)==len(paths)
    return output


def copy_ink(binary):
    height,width=binary.shape
    if int((binary>0).sum())>120_000:
        raise ValueError('مساحة الحبر كبيرة لهذا الوضع؛ قلل الدقة أو قص المنطقة أولًا.')
    count,labels,stats,_=cv2.connectedComponentsWithStats(binary,8)
    if count>6001:raise ValueError('شظايا حبر كثيرة؛ نظّف المكونات الصغيرة قبل النسخ.')
    paths=connect_on_ink(scan_runs(binary),binary)
    for line in paths:
        if all(p==line[0] for p in line):
            x,y=line[0];line.append([x+(.01 if x<width-1 else -.01),y] if width>1 else [x,y+(.01 if y<height-1 else 0)])
    return paths
