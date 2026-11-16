// Writes a pen plan as a laser score file: millimetre SVG, one hairline layer, in plan order.
// A laser burns what a pen would merely touch, so strokes shorter than minLength (dots included) are dropped,
// and each polyline is simplified within `tolerance` so the machine software is not fed sub-spot segments.
// It reads nothing but its arguments.
export const LASER_DEFAULTS=Object.freeze({minLength:.5,tolerance:.05,strokeWidth:.1,color:'#000000'});

const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
export function pathLength(points){let total=0;for(let i=1;i<points.length;i++)total+=distance(points[i-1],points[i]);return total;}

function offLine(p,a,b){
 const dx=b[0]-a[0],dy=b[1]-a[1],span=dx*dx+dy*dy;
 if(!span)return distance(p,a);// a closed loop: its ends coincide, so measure from that point
 const t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/span));
 return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);
}

// Ramer–Douglas–Peucker, iterative: plans reach tens of thousands of points per stroke. Ends are always kept.
export function simplify(points,tolerance){
 if(points.length<3||!(tolerance>0))return points.slice();
 const keep=new Uint8Array(points.length),stack=[[0,points.length-1]];keep[0]=keep[points.length-1]=1;
 while(stack.length){
  const [first,last]=stack.pop();let worst=0,index=-1;
  for(let i=first+1;i<last;i++){const d=offLine(points[i],points[first],points[last]);if(d>worst){worst=d;index=i;}}
  if(worst>tolerance){keep[index]=1;stack.push([first,index],[index,last]);}
 }
 return points.filter((_,i)=>keep[i]);
}

// Returns {svg,stats}. stats counts what the laser file kept and what it left out of the plan.
export function laserSvg(items,mapping,options={}){
 const {minLength,tolerance,strokeWidth,color}={...LASER_DEFAULTS,...options};
 for(const value of [minLength,tolerance,strokeWidth])if(typeof value!=='number'||!Number.isFinite(value)||value<0)throw Error('أدخل قيمًا صحيحة غير سالبة لتصدير الليزر.');
 if(!(strokeWidth>0))throw Error('سماكة خط الليزر يجب أن تكون أكبر من صفر.');
 if(!/^#[0-9a-f]{6}$/i.test(color))throw Error('لون طبقة الليزر يُكتب بصيغة #rrggbb.');
 const stats={paths:0,dropped:0,nodesBefore:0,nodes:0,lengthMm:0,droppedLengthMm:0},parts=[];
 for(const {p} of items){
  const points=[];
  for(const [x,y] of p){const point=[x*mapping.scale+mapping.x,y*mapping.scale+mapping.y],last=points.at(-1);if(!last||last[0]!==point[0]||last[1]!==point[1])points.push(point);}
  stats.nodesBefore+=p.length;
  const length=pathLength(points);
  if(points.length<2||length<minLength||!(length>0)){stats.dropped++;stats.droppedLengthMm+=length;continue;}
  const kept=simplify(points,tolerance);
  stats.paths++;stats.nodes+=kept.length;stats.lengthMm+=pathLength(kept);
  parts.push(`<path d="${kept.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(3)},${y.toFixed(3)}`).join(' ')}"/>`);
 }
 const {paperWidth:w,paperHeight:h}=mapping;
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${w}mm" height="${h}mm" viewBox="0 0 ${w} ${h}"><title>laser score paths</title><g id="score" fill="none" stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round">${parts.join('')}</g></svg>`;
 return {svg,stats};
}
