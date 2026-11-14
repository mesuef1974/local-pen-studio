export function length(path){let total=0;for(let i=1;i<path.length;i++)total+=Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]);return total;}
export function layout(width,height,paperWidth=210,paperHeight=297,margin=15){const scale=Math.min((paperWidth-2*margin)/Math.max(1,width-1),(paperHeight-2*margin)/Math.max(1,height-1));return {scale,x:(paperWidth-(width-1)*scale)/2,y:(paperHeight-(height-1)*scale)/2,paperWidth,paperHeight};}
// Reserve both the pixel cell and the round pen footprint inside the paper margins.
export function inkLayout(width,height,paperWidth=210,paperHeight=297,margin=15,pen=.2){if(![width,height,paperWidth,paperHeight,margin,pen].every(Number.isFinite)||Math.min(width,height)<=0||margin<0||pen<=0||Math.min(paperWidth,paperHeight)<=2*margin+pen)throw Error('أبعاد الورقة أو الهامش أو القلم لا تترك مساحة رسم صحيحة.');const scale=Math.min((paperWidth-2*margin-pen)/width,(paperHeight-2*margin-pen)/height);return {scale,x:(paperWidth-(width-1)*scale)/2,y:(paperHeight-(height-1)*scale)/2,paperWidth,paperHeight};}
export function travel(items){let total=0,last=[0,0];for(const {p}of items){total+=Math.hypot(p[0][0]-last[0],p[0][1]-last[1]);last=p.at(-1);}return total;}
// Path endpoints in a uniform grid. take() returns what a scan of every remaining path would return:
// the closest endpoint, the earliest path on ties, and its start before its end.
// Endpoint 2*index is a path's start and 2*index+1 its end; coordinates and cell contents live in flat arrays.
function endpointGrid(items){const count=items.length,ex=new Float64Array(2*count),ey=new Float64Array(2*count);let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
 for(let index=0;index<count;index++){const p=items[index].p,a=p[0],b=p[p.length-1];ex[2*index]=a[0];ey[2*index]=a[1];ex[2*index+1]=b[0];ey[2*index+1]=b[1];x0=Math.min(x0,a[0],b[0]);y0=Math.min(y0,a[1],b[1]);x1=Math.max(x1,a[0],b[0]);y1=Math.max(y1,a[1],b[1]);}
 const side=Math.max(1,Math.ceil(Math.sqrt(count))),cell=Math.max((x1-x0)/side,(y1-y0)/side,1e-9),columns=Math.floor((x1-x0)/cell)+1,rows=Math.floor((y1-y0)/cell)+1,taken=new Uint8Array(count);
 const column=x=>Math.min(columns-1,Math.max(0,Math.floor((x-x0)/cell))),row=y=>Math.min(rows-1,Math.max(0,Math.floor((y-y0)/cell)));
 // Each cell owns a slice of codes, in ascending code order; live[] is how many of them are still untaken.
 const home=new Int32Array(2*count),start=new Int32Array(columns*rows+1),live=new Int32Array(columns*rows),codes=new Int32Array(2*count);
 for(let code=0;code<2*count;code++){home[code]=row(ey[code])*columns+column(ex[code]);start[home[code]+1]++;}
 for(let k=0;k<columns*rows;k++)start[k+1]+=start[k];
 for(let code=0;code<2*count;code++)codes[start[home[code]]+live[home[code]]++]=code;
 let lx=0,ly=0,score=Infinity,best=-1;
 function scan(x,y){if(x<0||y<0||x>=columns||y>=rows)return;const k=y*columns+x,from=start[k],to=from+live[k];let kept=from;
  for(let at=from;at<to;at++){const code=codes[at];if(taken[code>>1])continue;codes[kept++]=code;const dx=ex[code]-lx,dy=ey[code]-ly,distance=dx*dx+dy*dy;if(distance<score||(distance===score&&code<best)){score=distance;best=code;}}live[k]=kept-from;}
 return {take(last){lx=last[0];ly=last[1];score=Infinity;best=-1;const cx=column(lx),cy=row(ly),reach=Math.max(cx,columns-1-cx,cy,rows-1-cy);
  // Every cell of ring r is at least (r-1) cells away, so the search stops once that exceeds the best found.
  for(let ring=0;ring<=reach;ring++){const near=Math.max(0,ring-1)*cell*(1-1e-9);if(near*near>score)break;
   if(!ring){scan(cx,cy);continue;}
   for(let x=cx-ring;x<=cx+ring;x++){scan(x,cy-ring);scan(x,cy+ring);}
   for(let y=cy-ring+1;y<cy+ring;y++){scan(cx-ring,y);scan(cx+ring,y);}}
  taken[best>>1]=1;return {index:best>>1,reverse:(best&1)===1};}};}
// A path keeps one reversed copy and one list of its segment lengths, so replanning after an edit neither copies nor measures it again.
const reversedCopies=new WeakMap(),segmentLengths=new WeakMap();
function reversed(path){let copy=reversedCopies.get(path);if(!copy){copy=path.slice().reverse();reversedCopies.set(path,copy);reversedCopies.set(copy,path);}return copy;}
function lengths(path){let list=segmentLengths.get(path);if(!list){list=new Float64Array(Math.max(0,path.length-1));for(let i=1;i<path.length;i++)list[i-1]=Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]);segmentLengths.set(path,list);}return list;}
export function order(paths,excluded=new Set(),mode='nearest',minimum=0,scale=1){const items=[];for(let i=0;i<paths.length;i++){const p=paths[i];if(!excluded.has(i)&&(minimum<=0&&scale>=0||length(p)*scale>=minimum))items.push({p,i});}if(mode==='longest'){const sizes=new Map(items.map(v=>[v,length(v.p)]));return items.sort((a,b)=>sizes.get(b)-sizes.get(a));}if(mode!=='nearest'||items.length<2)return items;
 const grid=endpointGrid(items),ordered=[];let last=[0,0];for(let count=0;count<items.length;count++){const {index,reverse}=grid.take(last),v=items[index],p=reverse?reversed(v.p):v.p;ordered.push({i:v.i,p});last=p[p.length-1];}return travel(ordered)<=travel(items)?ordered:items;}
// The totals are summed in the same order as the playback segments, which are only built when playback first asks for them.
export function timeline(items,scale,drawSpeed=30,travelSpeed=80,lift=.4){if(![scale,drawSpeed,travelSpeed,lift].every(Number.isFinite)||scale<=0||drawSpeed<=0||travelSpeed<=0||lift<0)throw Error('أدخل مقياسًا وسرعات موجبة وزمن رفع غير سالب.');let seconds=0,ink=0,movement=0,last=[0,0];
 for(const {p}of items){const t=Math.hypot(p[0][0]-last[0],p[0][1]-last[1])*scale,list=lengths(p);movement+=t;if(t/travelSpeed>0)seconds+=t/travelSpeed;if(lift>0)seconds+=lift;for(let i=0;i<list.length;i++){const n=list[i]*scale;ink+=n;if(n/drawSpeed>0)seconds+=n/drawSpeed;}last=p[p.length-1];}
 let segments=null;function build(){let at=0,from=[0,0];const built=[];function add(a,b,duration,draw){if(duration>0){built.push({a,b,start:at,end:at+duration,draw});at+=duration;}}
  for(const {p}of items){const list=lengths(p);add(from,p[0],Math.hypot(p[0][0]-from[0],p[0][1]-from[1])*scale/travelSpeed,false);add(p[0],p[0],lift,false);for(let i=1;i<p.length;i++)add(p[i-1],p[i],list[i-1]*scale/drawSpeed,true);from=p[p.length-1];}return built;}
 return {get segments(){return segments||(segments=build());},seconds,ink,movement,count:items.length};}
export function nearestPath(paths,x,y,radius,hidden=new Set()){let found=-1,best=radius;paths.forEach((p,i)=>{if(hidden.has(i))return;for(let k=1;k<p.length;k++){const a=p[k-1],b=p[k],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);if(d<best){best=d;found=i;}}});return found;}
export function intersectsBox(path,box){const [x1,y1,x2,y2]=box;for(let i=1;i<path.length;i++){const a=path[i-1],b=path[i];let low=0,high=1;const dx=b[0]-a[0],dy=b[1]-a[1];let hit=true;for(const [p,q]of [[-dx,a[0]-x1],[dx,x2-a[0]],[-dy,a[1]-y1],[dy,y2-a[1]]]){if(!p){if(q<0){hit=false;break;}}else{const r=q/p;if(p<0)low=Math.max(low,r);else high=Math.min(high,r);if(low>high){hit=false;break;}}}if(hit)return true;}return false;}
export function svg(items,mapping,pen=.3){const d=items.map(({p})=>`<path d="${p.map(([x,y],i)=>`${i?'L':'M'}${(x*mapping.scale+mapping.x).toFixed(3)},${(y*mapping.scale+mapping.y).toFixed(3)}`).join(' ')}"/>`).join('');return `<svg xmlns="http://www.w3.org/2000/svg" width="${mapping.paperWidth}mm" height="${mapping.paperHeight}mm" viewBox="0 0 ${mapping.paperWidth} ${mapping.paperHeight}"><g fill="none" stroke="black" stroke-width="${pen}" stroke-linecap="round" stroke-linejoin="round">${d}</g></svg>`;}
