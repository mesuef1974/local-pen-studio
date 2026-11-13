import test from 'node:test';
import assert from 'node:assert/strict';
import {Workflow} from './workflow.js';
import * as g from './geometry.js';
import {defaults,recipes,ids,renderToolPanels} from './tool-settings.js';
import {drawPlan} from './path-canvas.js';

test('raw image enters review unchanged and cannot reach paths before approval',()=>{const w=new Workflow();w.import('original','photo');const stale=w.versions[1];w.reviewImage({image:'raw-flux',width:576,height:768});assert.equal(w.original,'original');assert.equal(w.outputs[0].image,'raw-flux');assert.equal(w.outputs[1].image,'raw-flux');assert.equal(w.outputs[1].reference,'original');assert.equal(w.outputs[1].direct,true);assert.equal(w.stage,1);assert.equal(w.canEnter(2),false);assert.equal(w.approve(1),true);assert.equal(w.canEnter(2),true);assert.equal(w.publish(1,stale,{image:'late'}),false);w.invalidate(0);assert.equal(w.canEnter(2),false);});
test('pen footprint and outer pixel cells remain within physical paper margins',()=>{for(const [w,h]of [[576,768],[320,768],[768,256]])for(const pen of [.1,.2,1.2]){const m=g.inkLayout(w,h,210,297,15,pen);for(const [x,y]of [[-.5,-.5],[w-.5,h-.5]]){const px=x*m.scale+m.x,py=y*m.scale+m.y;assert.ok(px-pen/2>=15-1e-9&&px+pen/2<=195+1e-9);assert.ok(py-pen/2>=15-1e-9&&py+pen/2<=282+1e-9);}}});

test('stages require an explicit fresh approval',()=>{const w=new Workflow();w.import('source','photo');assert.equal(w.canEnter(1),false);assert.equal(w.publish(1,w.versions[1],{}),false);w.publish(0,w.versions[0],{image:'prepared'});assert.equal(w.canEnter(1),false);w.approve(0);assert.equal(w.canEnter(1),true);w.publish(1,w.versions[1],{image:'lines'});assert.equal(w.canEnter(2),false);w.approve(1);assert.equal(w.canEnter(2),true);});
test('upstream changes invalidate every dependent stage and late response',()=>{const w=new Workflow();w.import('a','a');w.publish(0,w.versions[0],{});w.approve(0);const version=w.versions[1];w.invalidate(0);assert.equal(w.publish(1,version,{}),false);assert.deepEqual(w.fresh,[false,false,false]);assert.deepEqual(w.approved,[false,false]);});
test('review edits preserve submitted draft but block pen stage',()=>{const w=new Workflow();w.import('a','a');w.publish(0,w.versions[0],{});w.approve(0);w.publish(1,w.versions[1],{});w.approve(1);w.invalidate(1);assert.equal(w.canEnter(1),true);assert.equal(w.canEnter(2),false);assert.equal(w.approved[0],true);});
test('new image cannot inherit old results or approvals',()=>{const w=new Workflow();w.import('a','a');w.publish(0,w.versions[0],{});w.approve(0);w.import('b','b');assert.equal(w.source,'b');assert.equal(w.original,'b');assert.equal(w.stage,0);assert.deepEqual(w.outputs,[null,null,null]);assert.equal(w.canEnter(1),false);});
test('nearest endpoint ordering preserves all geometry and never worsens initial travel',()=>{const paths=[[[90,0],[100,0]],[[10,0],[20,0]],[[50,0],[40,0]]],copy=JSON.stringify(paths),items=g.order(paths);assert.equal(JSON.stringify(paths),copy);assert.deepEqual(items.map(v=>v.i),[1,2,0]);assert.deepEqual(items[1].p,[[40,0],[50,0]]);assert.ok(g.travel(items)<=g.travel(paths.map((p,i)=>({p,i}))));});
test('excluded and short strokes never enter the export plan',()=>{const paths=[[[0,0],[10,0]],[[0,0],[1,0]],[[0,0],[20,0]]];assert.deepEqual(g.order(paths,new Set([2]),'original',2).map(v=>v.i),[0]);});
test('paper centering and margin respect physical dimensions',()=>{const m=g.layout(101,101,210,297,15);assert.equal(m.scale,1.8);assert.equal(m.x,15);assert.equal(m.y,58.5);});
test('time includes drawing, movement and lifting',()=>{const result=g.timeline([{p:[[10,0],[20,0]]},{p:[[20,10],[20,20]]}],1,10,20,.5);assert.equal(result.ink,20);assert.equal(result.movement,20);assert.equal(result.seconds,4);assert.ok(result.segments.every((v,i,a)=>!i||v.start===a[i-1].end));});
test('box selection includes crossing segments without vertices inside',()=>{assert.equal(g.intersectsBox([[-10,5],[20,5]],[0,0,10,10]),true);assert.equal(g.intersectsBox([[-10,-5],[20,-5]],[0,0,10,10]),false);});
test('grid nearest ordering matches the exhaustive scan, ties included',()=>{
 // The scan this replaced: every remaining path is examined at every step.
 function exhaustive(paths){const items=paths.map((p,i)=>({p,i})),remaining=items.slice(),ordered=[];let last=[0,0];while(remaining.length){let best=0,reverse=false,score=Infinity;remaining.forEach((v,i)=>{for(const end of [0,v.p.length-1]){const q=v.p[end],distance=(q[0]-last[0])**2+(q[1]-last[1])**2;if(distance<score){score=distance;best=i;reverse=end!==0;}}});const v=remaining.splice(best,1)[0];ordered.push({i:v.i,p:reverse?v.p.slice().reverse():v.p});last=ordered.at(-1).p.at(-1);}return g.travel(ordered)<=g.travel(items)?ordered:items;}
 let seed=11;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
 const cases={
  scattered:Array.from({length:700},()=>{const x=random()*1000,y=random()*1000;return [[x,y],[x+random()*30-15,y+random()*30-15],[x+random()*30-15,y+random()*30-15]];}),
  // Integer lattice: many equal distances, duplicate paths and closed loops.
  lattice:Array.from({length:500},()=>{const x=Math.floor(random()*12),y=Math.floor(random()*12),closed=random()<.3;return [[x,y],[x+1,y],closed?[x,y]:[x+Math.floor(random()*3),y+Math.floor(random()*3)]];}),
  clustered:Array.from({length:400},(_,i)=>{const far=i%50===0,x=far?5000+random():random()*4,y=far?-3000+random():random()*4;return [[x,y],[x+random(),y+random()]];}),
  line:Array.from({length:120},()=>{const x=random()*100;return [[x,7],[x+random(),7]];}),
  single:[[[3,4],[5,6]]]};
 for(const [name,paths]of Object.entries(cases)){const copy=JSON.stringify(paths);assert.deepEqual(g.order(paths),exhaustive(paths),name);assert.equal(JSON.stringify(paths),copy,name);}
 // Excluded strokes: the scan runs on the kept paths, then its indices map back to the full list.
 const hidden=new Set([0,3,4,99]),kept=cases.lattice.map((p,i)=>i).filter(i=>!hidden.has(i));
 assert.deepEqual(g.order(cases.lattice,hidden),exhaustive(kept.map(i=>cases.lattice[i])).map(v=>({i:kept[v.i],p:v.p})));
 const longest=g.order(cases.scattered,new Set(),'longest');for(let i=1;i<longest.length;i++)assert.ok(g.length(longest[i-1].p)>=g.length(longest[i].p));
});
test('tool panels render one control per setting with its default value',()=>{
 const panels={tools0:{innerHTML:''},tools1:{innerHTML:''},tools2:{innerHTML:''}},previous=globalThis.document;
 globalThis.document={getElementById:id=>panels[id]};try{renderToolPanels();}finally{globalThis.document=previous;}
 assert.equal(defaults.length,3);assert.equal(recipes.length,3);assert.equal(ids[2].pen,'s2_pen');
 for(const step of [0,2])for(const [key,value]of Object.entries(defaults[step])){const id=ids[step][key],html=panels['tools'+step].innerHTML;assert.equal(html.split(`id="${id}"`).length,2,id);if(typeof value==='number')assert.ok(html.includes(`id="${id}" type="range"`)||html.includes(`value="${value}"`),id);}
 assert.ok(panels.tools1.innerHTML.includes('approval-guide'));assert.ok(panels.tools0.innerHTML.startsWith('<details'));
});
test('path canvas draws only its arguments: plan, selection, exclusions and playback',()=>{
 function canvas(){const calls=[],ctx=new Proxy({},{get:(target,name)=>name in target?target[name]:(...args)=>calls.push([name,...args]),set:(target,name,value)=>{target[name]=value;calls.push(['set '+name,value]);return true;}});return {width:0,height:0,calls,getContext:()=>ctx};}
 const output={width:40,height:30,paths:[[[1,1],[5,1]],[[2,8],[9,8]],[[3,20],[3,25]]]},plan={items:[{i:0,p:output.paths[0]},{i:1,p:output.paths[1]}],segments:[{a:[0,0],b:[1,1],start:0,end:1,draw:false},{a:[1,1],b:[5,1],start:1,end:3,draw:true}],seconds:3};
 const settings={pen:.2,showTravel:true,showDeleted:true,starts:true},base={output,settings,mapping:{scale:.2},view:'compare',pathsReference:null,plan,elapsed:null,selected:new Set([1]),excluded:new Set([2]),box:null};
 const full=canvas();drawPlan(full,base);assert.deepEqual([full.width,full.height],[40,30]);
 const strokes=full.calls.filter(c=>c[0]==='stroke').length;assert.equal(strokes,2+2+1);// travel moves, plan strokes, one excluded stroke
 assert.ok(full.calls.some(c=>c[0]==='set strokeStyle'&&c[1]==='#2859c5'));assert.equal(full.calls.filter(c=>c[0]==='arc').length,2);
 const plain=canvas();drawPlan(plain,{...base,settings:{pen:.2,showTravel:false,showDeleted:false,starts:false}});assert.equal(plain.calls.filter(c=>c[0]==='stroke').length,2);assert.equal(plain.calls.filter(c=>c[0]==='arc').length,0);
 const moment=canvas();drawPlan(moment,{...base,elapsed:2});assert.deepEqual(moment.calls.filter(c=>c[0]==='lineTo').at(-1),['lineTo',3,1]);assert.equal(moment.calls.filter(c=>c[0]==='arc').length,1);
 // With a trail, a frame strokes only the segments finished since the previous frame, and the picture matches the direct drawing.
 const long={...plan,segments:[...plan.segments,{a:[5,1],b:[2,8],start:3,end:4,draw:false},{a:[2,8],b:[9,8],start:4,end:6,draw:true}],seconds:6},trail={canvas:canvas(),done:0},lines=c=>c.calls.filter(v=>v[0]==='lineTo').length;
 const first=canvas();drawPlan(first,{...base,plan:long,elapsed:2,trail});assert.equal(trail.done,1);assert.equal(lines(trail.canvas),1);assert.equal(first.calls.filter(c=>c[0]==='drawImage').length,1);assert.deepEqual(first.calls.filter(c=>c[0]==='lineTo').at(-1),['lineTo',3,1]);assert.deepEqual(first.calls.find(c=>c[0]==='arc').slice(1,3),[3,1]);
 const later=canvas();drawPlan(later,{...base,plan:long,elapsed:5,trail});assert.equal(trail.done,3);assert.equal(lines(trail.canvas),3);assert.deepEqual(later.calls.find(c=>c[0]==='arc').slice(1,3),[5.5,8]);
 drawPlan(canvas(),{...base,plan:long,elapsed:6,trail});assert.equal(trail.done,4);assert.equal(lines(trail.canvas),4);assert.equal(trail.canvas.calls.filter(c=>c[0]==='clearRect').length,1);
 const hidden={...settings,showTravel:false};drawPlan(canvas(),{...base,settings:hidden,plan:long,elapsed:6,trail});assert.equal(trail.canvas.calls.filter(c=>c[0]==='clearRect').length,2);assert.equal(lines(trail.canvas),4+2);
 drawPlan(canvas(),{...base,settings:hidden,plan:long,elapsed:1.5,trail});assert.equal(trail.done,1);assert.equal(trail.canvas.calls.filter(c=>c[0]==='clearRect').length,3);assert.equal(lines(trail.canvas),6);
 // With an ink layer, a new plan from the same paths repaints only around the strokes that entered or left it; selection is drawn over the layer.
 const ink={canvas:canvas(),scratch:canvas()},strokesOn=c=>c.calls.filter(v=>v[0]==='stroke').length,clears=()=>ink.canvas.calls.filter(v=>v[0]==='clearRect'),far=[[30,2],[36,2]],wide={...output,paths:[...output.paths,far]},both={items:[{i:0,p:wide.paths[0]},{i:1,p:wide.paths[1]},{i:3,p:far}]},still={...base,output:wide,settings:{pen:.2,showTravel:false,showDeleted:false,starts:false},ink};
 const inked=canvas();drawPlan(inked,{...still,plan:both});assert.equal(strokesOn(ink.canvas),3);assert.deepEqual(clears().at(-1),['clearRect',0,0,40,30]);assert.equal(inked.calls.filter(c=>c[0]==='drawImage').length,1);assert.equal(strokesOn(inked),1);// only the selected stroke, over the layer
 drawPlan(canvas(),{...still,plan:both});assert.equal(strokesOn(ink.canvas),3);// the same plan repaints nothing
 drawPlan(canvas(),{...still,plan:{items:both.items.slice(0,2)}});assert.equal(clears().length,2);assert.deepEqual(clears().at(-1),['clearRect',29,1,9,3]);assert.equal(strokesOn(ink.canvas),3);// the far stroke left; nothing else is near it
 drawPlan(canvas(),{...still,plan:{items:both.items.slice(0,2)},selected:new Set([3])});assert.equal(ink.drawn.has(3),false);
 drawPlan(canvas(),{...still,plan:both});assert.equal(clears().length,3);assert.equal(strokesOn(ink.canvas),3);assert.equal(strokesOn(ink.scratch),1);assert.equal(ink.canvas.calls.filter(c=>c[0]==='drawImage').length,2);// it returned alone, painted whole on the scratch and copied
 drawPlan(canvas(),{...still,settings:{...still.settings,pen:.4},plan:both});assert.deepEqual(clears().at(-1),['clearRect',0,0,40,30]);assert.equal(strokesOn(ink.canvas),6);// another pen repaints everything
 const boxed=canvas();drawPlan(boxed,{...base,plan:null,box:[1,2,6,9]});assert.deepEqual(boxed.calls.find(c=>c[0]==='strokeRect'),['strokeRect',1,2,5,7]);
 const overlay=canvas();drawPlan(overlay,{...base,view:'overlay',pathsReference:{}});assert.equal(overlay.calls.filter(c=>c[0]==='drawImage').length,1);
});
test('SVG has physical units and pure selected paths',()=>{const svg=g.svg([{p:[[0,0],[100,100]]}],g.layout(101,101),.3);assert.ok(svg.includes('width="210mm"'));assert.ok(svg.includes('stroke-width="0.3"'));assert.ok(!svg.includes('<image'));assert.equal((svg.match(/<path /g)||[]).length,1);});

test('text-only review has no unrelated source reference and does not alter timing settings',()=>{const w=new Workflow();w.reviewImage({image:'generated',width:512,height:512},'');assert.equal(w.outputs[1].reference,'');assert.equal(w.original,'generated');assert.deepEqual(w.approved,[true,false]);assert.equal(w.canEnter(2),false);});
