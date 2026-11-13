// Draws the pen plan on the preview canvas: the full plan, a playback moment, exclusions and the selection box.
// It reads nothing but its arguments, so the same call serves the page and tests.
// Playback keeps the finished segments on trail.canvas, a transparent canvas the caller owns, so a frame strokes
// only what the pen completed since the previous frame instead of the whole plan up to that moment.
// The trail restarts when the plan, pen, travel display or size changes, or when the moment moves backwards.
// Returns the pen position at that moment.
function drawTrail(trail,{output,pen,showTravel,scale,plan,elapsed}){const c=trail.canvas,segments=plan.segments,ctx=c.getContext('2d');
 const same=trail.plan===plan&&trail.pen===pen&&trail.showTravel===showTravel&&trail.scale===scale&&c.width===output.width&&c.height===output.height;
 if(!same||(trail.done>0&&segments[trail.done-1].end>elapsed)){if(c.width!==output.width||c.height!==output.height){c.width=output.width;c.height=output.height;}ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,c.width,c.height);Object.assign(trail,{plan,pen,showTravel,scale,done:0});}
 ctx.setTransform(1,0,0,1,0,0);ctx.translate(.5,.5);ctx.lineCap=ctx.lineJoin='round';ctx.lineWidth=pen/scale;
 // Consecutive segments of one kind share a single stroke call; each keeps its own subpath, so caps and dashes match segment-by-segment drawing.
 let index=trail.done,open=null,count=0;const flush=()=>{if(open!==null){ctx.stroke();open=null;count=0;}};
 for(;index<segments.length&&segments[index].end<=elapsed;index++){const segment=segments[index];if(!segment.draw&&!showTravel)continue;
  if(open!==segment.draw||count>=4096){flush();open=segment.draw;ctx.beginPath();ctx.strokeStyle=open?'#000000':'#4b7dcc';ctx.setLineDash(open?[]:[3/scale,2/scale]);}
  ctx.moveTo(...segment.a);ctx.lineTo(...segment.b);count++;}
 flush();ctx.setLineDash([]);trail.done=index;
 const current=segments[index];if(current&&current.start<=elapsed){const fraction=Math.min(1,(elapsed-current.start)/(current.end-current.start));return [current.a[0]+(current.b[0]-current.a[0])*fraction,current.a[1]+(current.b[1]-current.a[1])*fraction];}
 return index?segments[index-1].b:[0,0];}
// The still plan keeps its black strokes on ink.canvas, a transparent canvas the caller owns. A new plan from the same
// paths repaints only the pixel rectangles around the strokes that entered or left it, so excluding or restoring a
// stroke costs the strokes near it and not the whole plan. Selected strokes are drawn over the ink by the caller.
function drawInk(ink,{output,pen,scale,plan}){const c=ink.canvas,paths=output.paths,ctx=c.getContext('2d'),width=pen/scale,pad=width/2+1;
 const fresh=ink.paths!==paths||ink.pen!==pen||ink.scale!==scale||c.width!==output.width||c.height!==output.height;if(!fresh&&ink.plan===plan)return;
 if(ink.paths!==paths)ink.boxes=paths.map(p=>{let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;for(const [x,y]of p){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);}return [x0,y0,x1,y1];});
 if(fresh&&(c.width!==output.width||c.height!==output.height)){c.width=output.width;c.height=output.height;}
 // The pixel rectangle a stroke can touch: its box moved by the half-pixel offset and widened by half the pen and one pixel of antialiasing.
 const boxes=ink.boxes,reach=i=>{const b=boxes[i];return [Math.max(0,Math.floor(b[0]+.5-pad)),Math.max(0,Math.floor(b[1]+.5-pad)),Math.min(c.width,Math.ceil(b[2]+.5+pad)),Math.min(c.height,Math.ceil(b[3]+.5+pad))];};
 const drawn=new Set(plan.items.map(v=>v.i));let areas=[[0,0,c.width,c.height]];
 if(!fresh){const changed=[];for(const i of drawn)if(!ink.drawn.has(i))changed.push(i);for(const i of ink.drawn)if(!drawn.has(i))changed.push(i);
  areas=changed.map(reach);if(areas.length>32)areas=[areas.reduce((a,b)=>[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])])];}
 // Strokes are painted whole and unclipped, because a clip changes the antialiasing of the pixels along its edge.
 // A partial area is painted on ink.scratch and only its rectangle is copied; without a scratch canvas everything is repainted.
 const paint=(target,x0,y0,x1,y1)=>{target.setTransform(1,0,0,1,0,0);target.clearRect(0,0,c.width,c.height);target.translate(.5,.5);target.lineCap=target.lineJoin='round';target.lineWidth=width;target.strokeStyle='#000000';target.setLineDash([]);
  for(const i of drawn){const b=boxes[i];if(b[2]+.5+pad<=x0||b[0]+.5-pad>=x1||b[3]+.5+pad<=y0||b[1]+.5-pad>=y1)continue;const p=paths[i];target.beginPath();target.moveTo(p[0][0],p[0][1]);for(let j=1;j<p.length;j++)target.lineTo(p[j][0],p[j][1]);target.stroke();}};
 const scratch=ink.scratch;if(areas.length&&!scratch)areas=[[0,0,c.width,c.height]];
 for(const [x0,y0,x1,y1]of areas){if(x1<=x0||y1<=y0)continue;if(!x0&&!y0&&x1===c.width&&y1===c.height){paint(ctx,x0,y0,x1,y1);continue;}
  if(scratch.width!==c.width||scratch.height!==c.height){scratch.width=c.width;scratch.height=c.height;}paint(scratch.getContext('2d'),x0,y0,x1,y1);
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(x0,y0,x1-x0,y1-y0);ctx.drawImage(scratch,x0,y0,x1-x0,y1-y0,x0,y0,x1-x0,y1-y0);}
 Object.assign(ink,{paths,pen,scale,plan,drawn});}
export function drawPlan(c,{output,settings:s,mapping,view,pathsReference,plan,elapsed,selected,excluded,box,trail,ink}){if(c.width!==output.width||c.height!==output.height){c.width=output.width;c.height=output.height;}const ctx=c.getContext('2d'),scale=mapping?.scale||1;ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);if(view==='overlay'&&pathsReference){ctx.globalAlpha=.35;ctx.drawImage(pathsReference,0,0,c.width,c.height);ctx.globalAlpha=1;}ctx.translate(.5,.5);ctx.lineCap=ctx.lineJoin='round';ctx.lineWidth=s.pen/scale;
 if(plan&&elapsed!==null&&trail){const position=drawTrail(trail,{output,pen:s.pen,showTravel:s.showTravel,scale,plan,elapsed});ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(trail.canvas,0,0);ctx.translate(.5,.5);const segment=plan.segments[trail.done];
  if(segment&&segment.start<=elapsed&&(segment.draw||s.showTravel)){ctx.beginPath();ctx.moveTo(...segment.a);ctx.lineTo(...position);ctx.strokeStyle=segment.draw?'#000000':'#4b7dcc';ctx.setLineDash(segment.draw?[]:[3/scale,2/scale]);ctx.stroke();}ctx.setLineDash([]);ctx.beginPath();ctx.arc(...position,1.1/scale,0,Math.PI*2);ctx.fillStyle='#2859c5';ctx.fill();}
 else if(plan&&elapsed!==null){let position=[0,0];for(const segment of plan.segments){if(segment.start>elapsed)break;const fraction=Math.min(1,(elapsed-segment.start)/(segment.end-segment.start));position=[segment.a[0]+(segment.b[0]-segment.a[0])*fraction,segment.a[1]+(segment.b[1]-segment.a[1])*fraction];if(segment.draw||s.showTravel){ctx.beginPath();ctx.moveTo(...segment.a);ctx.lineTo(...position);ctx.strokeStyle=segment.draw?'#000000':'#4b7dcc';ctx.setLineDash(segment.draw?[]:[3/scale,2/scale]);ctx.stroke();}if(fraction<1)break;}ctx.setLineDash([]);ctx.beginPath();ctx.arc(...position,1.1/scale,0,Math.PI*2);ctx.fillStyle='#2859c5';ctx.fill();}
 else if(plan){if(s.showTravel){let last=[0,0];ctx.strokeStyle='#4b7dcc';ctx.lineWidth=.2/scale;ctx.setLineDash([3/scale,2/scale]);for(const {p}of plan.items){ctx.beginPath();ctx.moveTo(...last);ctx.lineTo(...p[0]);ctx.stroke();last=p.at(-1);}}ctx.setLineDash([]);ctx.lineWidth=s.pen/scale;
  if(ink){drawInk(ink,{output,pen:s.pen,scale,plan});ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(ink.canvas,0,0);ctx.translate(.5,.5);ctx.strokeStyle='#2859c5';for(const i of selected){if(!ink.drawn.has(i))continue;ctx.beginPath();output.paths[i].forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();}}
  else for(const {p,i}of plan.items){ctx.strokeStyle=selected.has(i)?'#2859c5':'#000000';ctx.beginPath();p.forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();}
  if(s.showDeleted){ctx.strokeStyle='#b57c85';ctx.setLineDash([3/scale,2/scale]);output.paths.forEach((p,i)=>{if(!excluded.has(i))return;ctx.beginPath();p.forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();});ctx.setLineDash([]);}if(s.starts){for(const {p}of plan.items){ctx.beginPath();ctx.arc(...p[0],.65/scale,0,Math.PI*2);ctx.fillStyle='#a66115';ctx.fill();}}}
 if(box){ctx.fillStyle='#2859c516';ctx.strokeStyle='#2859c5';ctx.lineWidth=.25/scale;ctx.setLineDash([2/scale,2/scale]);ctx.fillRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);ctx.strokeRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);ctx.setLineDash([]);}}
