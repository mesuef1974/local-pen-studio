/* OpenCV connected contours -> protected selection -> conservative refinement. */
importScripts('path-refinement.js');
self.onmessage=({data})=>{try{const {id,width:w,height:h,pixels,detail,minLength,epsilon:requestedEpsilon,shading,paper,penWidth,featureRegion,executionLevel=25,protectFeatures=true,featureToleranceMm=.04,joinGapMm=.2,curveSmoothMm=.03,fitToStrokes=true}=data;
 const quick=true;
 const preserveInk=data.preserveInk===true,epsilon=preserveInk?0:requestedEpsilon;
 const richness=Math.max(0,Math.min(1,executionLevel/100));
 const focused=(x,y)=>featureRegion&&x/w>=featureRegion.x&&x/w<=featureRegion.x+featureRegion.width&&y/h>=featureRegion.y&&y/h<=featureRegion.y+featureRegion.height;
 const n=w*h,gray=new Float32Array(n),tmp=new Float32Array(n),blur=new Float32Array(n);
 for(let i=0;i<n;i++)gray[i]=.2126*pixels[i*4]+.7152*pixels[i*4+1]+.0722*pixels[i*4+2];
 const k=[1,4,6,4,1];
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){let v=0;for(let a=-2;a<=2;a++)v+=gray[y*w+Math.max(0,Math.min(w-1,x+a))]*k[a+2];tmp[y*w+x]=v/16;}
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){let v=0;for(let a=-2;a<=2;a++)v+=tmp[Math.max(0,Math.min(h-1,y+a))*w+x]*k[a+2];blur[y*w+x]=v/16;}
 const mag=new Float32Array(n);let raw=[];
 if(data.basePaths){
  for(const points of data.basePaths){let length=0;for(let i=1;i<points.length;i++)length+=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);raw.push({points,length});}
  for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++)mag[y*w+x]=Math.hypot(blur[y*w+x+1]-blur[y*w+x-1],blur[(y+1)*w+x]-blur[(y-1)*w+x]);
 }else {throw new Error('لم تصل مسارات OpenCV المتصلة.');}
 const high=0;
 const rawCount=raw.length;raw.forEach(p=>{let contrast=0,cx=0,cy=0;for(const [x,y]of p.points){contrast+=mag[Math.round(y)*w+Math.round(x)];cx+=x;cy+=y;}cx/=p.points.length*w;cy/=p.points.length*h;const central=Math.exp(-((cx-.5)**2/.035+(cy-.4)**2/.05));const fraction=p.points.filter(([x,y])=>focused(x,y)).length/p.points.length;p.score=Math.pow(p.length,.35)*(contrast/p.points.length)*(featureRegion?(.2+18*fraction):(1+2*central));});raw.sort((a,b)=>quick?b.score-a.score:b.length-a.length);const anchors=[...raw].sort((a,b)=>b.length-a.length).slice(0,Math.min(8,raw.length));
 const buckets=Array.from({length:24},()=>[]);
 for(const path of raw){if(anchors.includes(path))continue;let cx=0,cy=0;for(const [x,y]of path.points){cx+=x;cy+=y;}cx/=path.points.length*w;cy/=path.points.length*h;const col=Math.max(0,Math.min(3,Math.floor(cx*4))),row=Math.max(0,Math.min(5,Math.floor(cy*6)));buckets[row*4+col].push(path);}
 const protectedLines=protectFeatures&&featureRegion?raw.filter(p=>p.points.some(([x,y])=>focused(x,y))):[];
 const mustKeep=[...new Set([...protectedLines,...anchors])];
 for(const bucket of buckets)for(let i=bucket.length-1;i>=0;i--)if(mustKeep.includes(bucket[i]))bucket.splice(i,1);
 const targetCount=Math.min(raw.length,Math.max(mustKeep.length,Math.round(12+richness*(raw.length-12))));
 const chosen=mustKeep.slice();for(let rank=0;chosen.length<targetCount;rank++){let added=0;for(const bucket of buckets){if(bucket[rank]&&chosen.length<targetCount){chosen.push(bucket[rank]);added++;}}if(!added)break;}
 let xmin=Infinity,ymin=Infinity,xmax=-Infinity,ymax=-Infinity;
 for(const path of raw)for(const [x,y]of path.points){xmin=Math.min(xmin,x);xmax=Math.max(xmax,x);ymin=Math.min(ymin,y);ymax=Math.max(ymax,y);}
 const mmPerPixel=Math.min((paper.width-2*paper.margin)/Math.max(1,fitToStrokes?xmax-xmin:w-1),(paper.height-2*paper.margin)/Math.max(1,fitToStrokes?ymax-ymin:h-1));
 const refined=refinePenPaths(chosen.map(p=>p.points),{protectedFlags:chosen.map(p=>Boolean(protectFeatures&&featureRegion&&p.points.some(([x,y])=>focused(x,y)))),joinGapPixels:preserveInk?0:joinGapMm/mmPerPixel,smoothPixels:preserveInk?0:curveSmoothMm/mmPerPixel,evidence:(x,y)=>mag[Math.max(0,Math.min(h-1,Math.round(y)))*w+Math.max(0,Math.min(w-1,Math.round(x)))]});
 const protectedFlags=refined.protectedFlags;
 const kept=refined.paths.map((path,i)=>epsilon===0?path:simplify(path,protectedFlags[i]?Math.min(epsilon,featureToleranceMm/mmPerPixel):epsilon));
 // Greedy nearest endpoint ordering. This is a heuristic, not an optimal route guarantee.
 const paths=[];let cursor=[0,0];while(kept.length){if(quick){paths.push(kept.shift());continue;}let best=0,reverse=false,distance=Infinity;
  for(let i=0;i<kept.length;i++){const p=kept[i];const da=distance2(cursor,p[0]),db=distance2(cursor,p[p.length-1]);if(da<distance){distance=da;best=i;reverse=false;}if(db<distance){distance=db;best=i;reverse=true;}}
  const p=kept.splice(best,1)[0];if(reverse)p.reverse();paths.push(p);cursor=p[p.length-1];
 }
 const edgeCount=paths.length;let hatchCount=0;
 if(shading){
  const scale=Math.min((paper.width-2*paper.margin)/w,(paper.height-2*paper.margin)/h);
  const spacing=Math.max(3,(quick?(6-richness*4.5):Math.max(1.1,penWidth*3))/scale);
  const layers=[{threshold:.18,slope:.45,offset:0},{threshold:.43,slope:.45,offset:spacing/2},{threshold:.68,slope:-.65,offset:0}];
  for(const layer of ([{threshold:.85-richness*.65,slope:.45,offset:0},{threshold:1.05-richness*.5,slope:-.65,offset:spacing/2}])){let row=0;
   const extent=Math.abs(layer.slope)*w;
   for(let b=-extent+layer.offset;b<h+extent;b+=spacing){
    let start=null,last=null;const runs=[];
    for(let x=1;x<w-1;x++){
     const y=Math.round(b+layer.slope*x);const dark=y>1&&y<h-2&&!(quick&&focused(x,y))&&(1-blur[y*w+x]/255)>=layer.threshold;
     if(dark){if(!start)start=[x,y];last=[x,y];}
     if((!dark||x===w-2)&&start){if(Math.hypot(last[0]-start[0],last[1]-start[1])*scale>=(quick?(5-richness*4):.45))runs.push([start,last]);start=null;last=null;}
    }
    if(row++%2){runs.reverse();runs.forEach(p=>p.reverse());}
    for(const run of runs){if(hatchCount>=(quick?Math.round((featureRegion?4:12)+richness*200):12000))break;paths.push(run);hatchCount++;}
   }
  }
 }
 self.postMessage({id,protectedFlags,joinedCount:refined.joins,protectedCount:protectedFlags.filter(Boolean).length,smoothMoved:refined.moved,selectedEdges:edgeCount,pointsBefore:chosen.reduce((n,p)=>n+p.points.length,0),pointsAfter:paths.slice(0,edgeCount).reduce((n,p)=>n+p.length,0),paths,width:w,height:h,rawCount,hatchCount,truncated:Math.max(0,rawCount-chosen.length),threshold:high});
 }catch(e){self.postMessage({id:data.id,error:e.message||String(e)});}};

function distance2(a,b){return(a[0]-b[0])**2+(a[1]-b[1])**2;}
function simplify(points,epsilon){if(points.length<3)return points;const keep=new Uint8Array(points.length);keep[0]=keep[points.length-1]=1;const ranges=[[0,points.length-1]],limit=epsilon*epsilon;
 while(ranges.length){const [start,end]=ranges.pop();let max=limit,index=-1;const a=points[start],b=points[end],dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy;
  for(let i=start+1;i<end;i++){const p=points[i];const t=den?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)):0;const d=(p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2;if(d>max){max=d;index=i;}}
  if(index!==-1){keep[index]=1;ranges.push([start,index],[index,end]);}
 }return points.filter((_,i)=>keep[i]);}
