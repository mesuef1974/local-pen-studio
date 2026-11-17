// Reads the layers of a Misk laser template: an SVG in millimetres whose layers are <g id="engrave"> (black fill,
// engraved as an area; read but not written back, the drawing takes its place), <g id="cut"> (red hairline, cut through) and <g id="guide"> (blue, a reference the machine
// does not output), each holding absolute M/L/Z paths. A layer's paths are read as one even-odd shape, which is how
// Misk writes them: one path per layer. Nothing of the file's markup is kept: the paths are parsed to numbers and
// written again, so a template cannot carry anything else into the laser file or the page.
// It reads nothing but its arguments.
export const TEMPLATE_LIMITS=Object.freeze({bytes:2_000_000,points:200_000,sizeTolerance:.05});
const CUT='fill="none" stroke="#ff0000" stroke-width="0.1"',GUIDE='fill="none" stroke="#0000ff" stroke-width="0.2" stroke-dasharray="1 1"';

const attribute=(tag,name)=>new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1];
function millimetres(value){const match=/^(\d+(?:\.\d+)?)mm$/.exec(value??'');return match?Number(match[1]):NaN;}

// One `d` attribute to [{points,closed}]. Only absolute M, L and Z are read; anything else is refused, not skipped.
function subpaths(d){
 const token=/\s*(?:([MLZ])|(-?\d+(?:\.\d+)?)\s*,?)\s*/y,paths=[];let current=null,pending=null,at=0;
 while(at<d.length){
  token.lastIndex=at;const match=token.exec(d);
  if(!match)throw Error('القالب يحوي مسارًا بصيغة غير مدعومة؛ المقبول M وL وZ بإحداثيات مطلقة.');
  at=token.lastIndex;
  if(match[1]){
   if(pending!==null)throw Error('القالب يحوي إحداثيًّا ناقصًا.');
   if(match[1]==='M'){current={points:[],closed:false};paths.push(current);}
   else if(!current?.points.length)throw Error('القالب يحوي مسارًا لا يبدأ بـM.');
   else if(match[1]==='Z'){current.closed=true;current=null;}
  }else{
   if(!current)throw Error('القالب يحوي مسارًا لا يبدأ بـM.');
   if(pending===null)pending=Number(match[2]);else{current.points.push([pending,Number(match[2])]);pending=null;}
  }
 }
 if(pending!==null)throw Error('القالب يحوي إحداثيًّا ناقصًا.');
 return paths.filter(path=>path.points.length>1);
}

// Returns {width,height,title,engrave,cut,guide}; each layer is a list of {points,closed} in sheet millimetres.
export function readLaserTemplate(text){
 if(typeof text!=='string'||!text.length)throw Error('ملف القالب فارغ.');
 if(text.length>TEMPLATE_LIMITS.bytes)throw Error('ملف القالب أكبر من 2 ميغابايت.');
 const head=/<svg\b[^>]*>/.exec(text)?.[0];
 if(!head)throw Error('القالب ليس ملف SVG.');
 const width=millimetres(attribute(head,'width')),height=millimetres(attribute(head,'height'));
 if(!(width>0)||!(height>0))throw Error('القالب لا يذكر عرضه وارتفاعه بالمليمتر.');
 const box=(attribute(head,'viewBox')??'').trim().split(/[\s,]+/).map(Number);
 if(box.length!==4||box[0]!==0||box[1]!==0||Math.abs(box[2]-width)>1e-6||Math.abs(box[3]-height)>1e-6)throw Error('وحدة القالب ليست المليمتر: viewBox لا يطابق العرض والارتفاع.');
 let points=0;
 const layer=id=>{
  const group=new RegExp(`<g\\b[^>]*\\sid="${id}"[^>]*>([\\s\\S]*?)</g>`).exec(text)?.[1]??'',paths=[];
  for(const [,d] of group.matchAll(/<path\b[^>]*?\sd="([^"]*)"/g))for(const path of subpaths(d)){
   points+=path.points.length;
   if(points>TEMPLATE_LIMITS.points)throw Error('القالب أعقد من الحدّ المسموح (200 ألف نقطة).');
   for(const [x,y] of path.points)if(x<-TEMPLATE_LIMITS.sizeTolerance||y<-TEMPLATE_LIMITS.sizeTolerance||x>width+TEMPLATE_LIMITS.sizeTolerance||y>height+TEMPLATE_LIMITS.sizeTolerance)throw Error('في القالب مسار يخرج عن حدود صفحته.');
   paths.push(path);
  }
  return paths;
 };
 const engrave=layer('engrave'),cut=layer('cut'),guide=layer('guide');
 if(!engrave.length&&!cut.length&&!guide.length)throw Error('القالب لا يحوي طبقة حفر (engrave) ولا قص (cut) ولا مرجع (guide).');
 const title=(/<title>([^<]*)<\/title>/.exec(text)?.[1]??'').trim().slice(0,120);
 return {width,height,title,engrave,cut,guide};
}

export function sameSheet(template,mapping){return Math.abs(template.width-mapping.paperWidth)<=TEMPLATE_LIMITS.sizeTolerance&&Math.abs(template.height-mapping.paperHeight)<=TEMPLATE_LIMITS.sizeTolerance;}

const pathData=paths=>paths.map(({points,closed})=>points.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(3)},${y.toFixed(3)}`).join(' ')+(closed?' Z':'')).join(' ');
// The cut outline as path data for an even-odd clip, or '' when the template has none.
export function cutPathData(template){return pathData(template.cut);}
// The template's cut outline and guides as SVG groups, in the colours the machine software tells layers apart by.
export function templateLayers(template){
 return (template.cut.length?`<g id="cut" ${CUT}><path fill-rule="evenodd" d="${pathData(template.cut)}"/></g>`:'')+(template.guide.length?`<g id="guide" ${GUIDE}><path fill-rule="evenodd" d="${pathData(template.guide)}"/></g>`:'');
}

// Even-odd test against every ring at once, so a hole in the piece (a keyring hole) counts as outside it.
function insideRings(rings,[x,y]){
 let inside=false;
 for(const {points} of rings)for(let i=0,j=points.length-1;i<points.length;j=i++){
  const [ax,ay]=points[i],[bx,by]=points[j];
  if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;
 }
 return inside;
}
export function insideCut(template,point){return insideRings(template.cut,point);}

// A layer's edges in a coarse grid over the sheet, so a stroke is only tested against the outline near it. A cell no
// edge passes through is wholly inside the shape or wholly outside; which one is found once, at its centre, when first asked.
const GRID=64,indexCache=new WeakMap();
function ringIndex(template,rings){
 let index=indexCache.get(rings);
 if(index)return index;
 const edges=[],cellW=template.width/GRID,cellH=template.height/GRID,cells=Array.from({length:GRID*GRID},()=>[]);
 const column=x=>Math.max(0,Math.min(GRID-1,Math.floor(x/cellW))),row=y=>Math.max(0,Math.min(GRID-1,Math.floor(y/cellH)));
 for(const {points} of rings)for(let i=0,j=points.length-1;i<points.length;j=i++){
  const c=points[j],d=points[i],id=edges.push([c,d])-1;
  for(let r=row(Math.min(c[1],d[1]));r<=row(Math.max(c[1],d[1]));r++)for(let q=column(Math.min(c[0],d[0]));q<=column(Math.max(c[0],d[0]));q++)cells[r*GRID+q].push(id);
 }
 index={edges,cells,column,row,cellW,cellH,state:new Int8Array(GRID*GRID),seen:new Uint32Array(edges.length),stamp:0};
 indexCache.set(rings,index);return index;
}
// The range of t where lo < p + q·t < hi, or null when there is none.
function between(p,q,lo,hi){if(!q)return p>lo&&p<hi?[-Infinity,Infinity]:null;const s=(lo-p)/q,e=(hi-p)/q;return s<e?[s,e]:[e,s];}

// The parts of a polyline on one side of a shape: inside it (`inside` true) or outside it. With a margin, whatever
// comes within that distance of the shape's outline is left out as well. Each segment is split where it crosses the
// outline, or where it enters the margin, and a part is kept by where its midpoint lies. Returns the kept polylines in
// drawing order.
function clip(template,rings,points,inside,margin){
 const index=ringIndex(template,rings),{edges,cells,column,row,state}=index,runs=[];let run=null;
 for(let i=1;i<points.length;i++){
  const a=points[i-1],b=points[i],dx=b[0]-a[0],dy=b[1]-a[1],span=dx*dx+dy*dy,cuts=[0,1],gone=[];
  const minX=Math.min(a[0],b[0])-margin,maxX=Math.max(a[0],b[0])+margin,minY=Math.min(a[1],b[1])-margin,maxY=Math.max(a[1],b[1])+margin;
  const stamp=++index.stamp;let near=false;
  for(let r=row(minY);r<=row(maxY);r++)for(let q=column(minX);q<=column(maxX);q++)for(const id of cells[r*GRID+q]){
   near=true;
   if(index.seen[id]===stamp)continue;
   index.seen[id]=stamp;
   const [c,d]=edges[id];
   if(Math.max(c[0],d[0])<minX||Math.min(c[0],d[0])>maxX||Math.max(c[1],d[1])<minY||Math.min(c[1],d[1])>maxY)continue;
   const ex=d[0]-c[0],ey=d[1]-c[1];
   if(margin){// where the segment is within `margin` of this edge: a disc at each end and the band between them
    for(const end of [c,d]){
     const fx=a[0]-end[0],fy=a[1]-end[1],half=dx*fx+dy*fy,disc=half*half-span*(fx*fx+fy*fy-margin*margin);
     if(disc>0&&span>0){const root=Math.sqrt(disc);gone.push([(-half-root)/span,(-half+root)/span]);}
    }
    const length=Math.hypot(ex,ey);
    if(length){
     const ux=ex/length,uy=ey/length,fx=a[0]-c[0],fy=a[1]-c[1];
     const along=between(fx*ux+fy*uy,dx*ux+dy*uy,0,length),across=between(fy*ux-fx*uy,dy*ux-dx*uy,-margin,margin);
     if(along&&across){const from=Math.max(along[0],across[0]),to=Math.min(along[1],across[1]);if(from<to)gone.push([from,to]);}
    }
   }else{
    const den=dx*ey-dy*ex;
    if(!den)continue;// parallel: a line along the outline is decided by its midpoint like any other
    const t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den,u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/den;
    if(t>0&&t<1&&u>=0&&u<=1)cuts.push(t);
   }
  }
  if(!near){// no outline in any cell the segment and its margin touch: it is wholly on one side
   const x=a[0]+dx/2,y=a[1]+dy/2;let within=false;
   if(x>=0&&y>=0&&x<=template.width&&y<=template.height){
    const cell=row(y)*GRID+column(x);
    if(!state[cell])state[cell]=insideRings(rings,[(column(x)+.5)*index.cellW,(row(y)+.5)*index.cellH])?1:2;
    within=state[cell]===1;
   }
   if(within!==inside)run=null;else if(run)run.push(b);else{run=[a,b];runs.push(run);}
   continue;
  }
  const parts=[];
  if(margin){
   gone.sort((p,q)=>p[0]-q[0]);let t=0;
   for(const [from,to] of gone){if(to<=t||from>=1)continue;if(from>t)parts.push([t,from]);t=to;}
   if(t<1)parts.push([t,1]);
  }else{cuts.sort((p,q)=>p-q);for(let k=1;k<cuts.length;k++)parts.push([cuts[k-1],cuts[k]]);}
  const at=t=>t===0?a:t===1?b:[a[0]+dx*t,a[1]+dy*t];let reached=0;// how far along this segment the current run goes
  for(const [from,to] of parts){
   if(to-from<1e-12)continue;// the same crossing found on two edges that meet at a vertex
   const mid=(from+to)/2;
   if(insideRings(rings,[a[0]+dx*mid,a[1]+dy*mid])!==inside){run=null;continue;}
   if(run&&from-reached<1e-12)run.push(at(to));else{run=[at(from),at(to)];runs.push(run);}
   reached=to;
  }
  if(reached<1)run=null;
 }
 return runs;
}
// What of a polyline lies on the piece (inside the cut outline, a hole being outside), at least `margin` from the outline.
export function clipToCut(template,points,margin=0){return clip(template,template.cut,points,true,margin);}
