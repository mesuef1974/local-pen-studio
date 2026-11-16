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
test('timeline totals equal the playback segments, which are built once and only when asked',()=>{
 const paths=[[[90,0],[100,3]],[[10,0],[20,0],[20,0],[23,4]],[[50,0],[40,0]],[[7,7],[7,7]]],items=g.order(paths),again=g.order(paths);assert.deepEqual(items.map(v=>v.i),[3,1,2,0]);
 // A reversed stroke is the same copy on every plan, and the caller's paths stay untouched.
 assert.deepEqual(items[2].p,[[40,0],[50,0]]);assert.equal(items[2].p,again[2].p);assert.deepEqual(paths[2],[[50,0],[40,0]]);
 for(const [scale,draw,move,lift]of [[1,10,20,.5],[.175,30,80,.4],[2,200,200,0]]){const plan=g.timeline(items,scale,draw,move,lift),segments=plan.segments;assert.equal(plan.segments,segments);
  // The reference sums every segment the way the timeline did before its totals and segments were separated.
  let seconds=0,ink=0,movement=0,last=[0,0],count=0;const step=(a,b,duration,drawn)=>{if(duration>0){const s=segments[count++];assert.deepEqual([s.a,s.b,s.start,s.end,s.draw],[a,b,seconds,seconds+duration,drawn]);seconds+=duration;}};
  for(const {p}of items){const t=Math.hypot(p[0][0]-last[0],p[0][1]-last[1])*scale;movement+=t;step(last,p[0],t/move,false);step(p[0],p[0],lift,false);for(let i=1;i<p.length;i++){const n=Math.hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1])*scale;ink+=n;step(p[i-1],p[i],n/draw,true);}last=p.at(-1);}
  assert.equal(count,segments.length);assert.deepEqual([plan.seconds,plan.ink,plan.movement,plan.count],[seconds,ink,movement,4]);assert.equal(segments.at(-1).end,plan.seconds);}
});
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

import {planDocument} from './plan-export.js';
import {fmt,stageSummary} from './stage-metrics.js';
import {renderFidelity} from './fidelity-panel.js';
import {renderPaperPreview,paperPair} from './paper-preview.js';
// A page stand-in: every id resolves to one remembered plain object.
function fakePage(){const nodes=new Map();return id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,dataset:{},style:{},attributes:{},setAttribute(k,v){this.attributes[k]=v;},getAttribute(k){return this.attributes[k]??this[k]??null;}});return nodes.get(id);};}
test('plan document places paths in paper millimetres and keeps only audit numbers',()=>{const mapping={scale:.5,x:10,y:20,paperWidth:210,paperHeight:297},plan={items:[{p:[[0,0],[2,4]],i:0}],seconds:12.5};
 const doc=planDocument({plan,mapping,settings:{margin:15,paper:'A4',drawScale:100,pen:.3,drawSpeed:30,travelSpeed:80,lift:.4},output:{width:100,height:200,inputHash:'abc'},audit:{inkIoU:91.5,scope:'ink mask',renderer:'cairo',target:'data:image/png;base64,AAAA',webgpuAdapter:{vendor:'x'}}});
 assert.deepEqual(doc.paths,[[[10,20],[11,22]]]);assert.deepEqual(doc.audit,{inkIoU:91.5,scope:'ink mask',renderer:'cairo'});assert.deepEqual(doc.imagePlacement,{origin:'first pixel center',x:10,y:20,frameLeftMm:9.75,frameTopMm:19.75,mmPerPixel:.5,sourceWidth:100,sourceHeight:200});
 assert.deepEqual(Object.keys(doc),['version','simulationOnly','units','paper','coordinateSpace','imagePlacement','penWidth','speeds','homeMm','estimatedSeconds','audit','referenceHash','paths']);assert.equal(doc.referenceHash,'abc');
 const bare=planDocument({plan,mapping,settings:{},output:{width:1,height:1},audit:null});assert.equal(bare.audit,null);assert.equal(bare.referenceHash,null);});
test('stage summary reports each stage and never shows figures of a stale result',()=>{assert.equal(fmt(125.4),'2:05');assert.equal(fmt(-3),'0:00');
 const stale=stageSummary({stage:0,ready:false,out:{width:5},plan:null,approved:false,excludedCount:0});assert.deepEqual(stale.values,['—','—','—','—']);assert.ok(stale.info.includes('تحديثًا'));
 assert.deepEqual(stageSummary({stage:2,ready:true,out:{paths:[]},plan:null,approved:true,excludedCount:0}).values,['—','—','—','—']);
 const first=stageSummary({stage:0,ready:true,out:{generated:true,seed:42,seconds:7,meta:{width:512,height:768}},plan:null,approved:false,excludedCount:0});assert.equal(first.values[0],'512 × 768');assert.equal(first.values[2],'FLUX.2 Klein 4B');assert.ok(first.info.includes('42'));
 assert.equal(stageSummary({stage:1,ready:true,out:{width:4,height:6},plan:null,approved:true,excludedCount:0}).values[3],'معتمدة');
 const paths=stageSummary({stage:2,ready:true,out:{paths:[1,2,3]},plan:{count:2,ink:1500,movement:2500,seconds:61,items:[{p:[[0,0],[1,1]]},{p:[[0,0],[1,1],[2,2]]}]},approved:true,excludedCount:1});assert.deepEqual(paths.values,['2','1.50 م','2.50 م','1:01']);assert.equal(paths.info,'3 مستخرج · 1 مستبعد يدويًا · 5 نقطة · دون تسارع أو تحقق حركي');});
test('fidelity panel hides outside the paths stage and shows no stale measurement',()=>{const $=fakePage();renderFidelity($,{visible:false,data:null,gpu:false,locked:true,fresh:false});assert.equal($('fidelityPanel').hidden,true);assert.equal($('fidelityState').textContent,undefined);
 renderFidelity($,{visible:true,data:null,gpu:false,locked:true,fresh:false});assert.equal($('fidelityPanel').hidden,false);assert.equal($('fidelityResults').hidden,true);assert.equal($('auditPaths').disabled,true);assert.ok($('fidelityState').textContent.startsWith('حدّث المسارات'));
 renderFidelity($,{visible:true,data:{penMm:.3,missingInkPercent:1.234,extraInkPercent:.5,coloredPixelsPercent:0,inkIoU:90,inkRecall:95.555,inkPrecision:80,grayErrorInkRegion:null,target:'t',reconstruction:'r',difference:'d'},gpu:false,locked:false,fresh:true});
 assert.equal($('fidelityResults').hidden,false);assert.equal($('fidelityRecall').textContent,'95.56%');assert.equal($('fidelityGray').textContent,'غير محسوب');assert.equal($('fidelityRender').src,'r');assert.ok($('fidelityState').textContent.includes('الحبر المفقود 1.23%'));assert.equal($('fidelityRenderCanvas').hidden,true);});
test('paper preview builds the sheet once per plan and waits while paths are stale',()=>{const frames=[];globalThis.requestAnimationFrame=f=>frames.push(f);try{const $=fakePage(),state={key:null},mapping=g.inkLayout(100,100,210,297,15,.3);Object.assign(mapping,{paperWidth:210,paperHeight:297});
  const plan={items:[{p:[[0,0],[99,99]],i:0}]};let keys=0;const options={stage:2,view:'paper',ready:true,busy:false,layout:()=>mapping,settings:()=>({paper:'A4',pen:.3,margin:15}),mapping,plan,planKey:()=>{keys++;return 'k';}};
  renderPaperPreview($,state,{...options,view:'compare'});assert.equal($('paperPreview').hidden,true);assert.equal(keys,0);
  renderPaperPreview($,state,{...options,ready:false,layout:()=>{throw Error('bad');}});assert.equal($('paperSheet').hidden,true);assert.equal($('paperDimensions').textContent,'راجع أبعاد الورقة');assert.equal(keys,0);
  renderPaperPreview($,state,options);assert.equal($('paperSheet').hidden,false);assert.equal($('paperDimensions').textContent,`A4 · ${paperPair(210,297)} مم`);const first=$('paperImage').src;assert.ok(atob(first.split(',')[1]).includes('<path '));assert.equal($('paperSheet').style.aspectRatio,'210 / 297');
  $('paperImage').src='kept';renderPaperPreview($,state,options);assert.equal($('paperImage').src,'kept');
  $('paperGuides').checked=true;renderPaperPreview($,state,options);assert.ok(atob($('paperImage').src.split(',')[1]).includes('stroke-dasharray="1.5 1.5"'));assert.equal(frames.length,3);}finally{delete globalThis.requestAnimationFrame;}});
test('replanning after an edit keeps the unchanged start and matches a fresh plan',()=>{
 let seed=29;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
 const cases={scattered:Array.from({length:600},()=>{const x=random()*1000,y=random()*1000;return [[x,y],[x+random()*30-15,y+random()*30-15]];}),
  lattice:Array.from({length:400},()=>{const x=Math.floor(random()*10),y=Math.floor(random()*10);return [[x,y],[x+Math.floor(random()*3),y+Math.floor(random()*3)]];})};
 for(const [name,paths]of Object.entries(cases)){
  // A fresh array has no previous run, so it is planned from scratch.
  const fresh=(hidden,minimum=0)=>g.order(paths.slice(),hidden,'nearest',minimum);
  const first=g.order(paths,new Set());assert.equal(g.reusedSteps(paths),0,name);
  const late=first.at(-20).i,hidden=new Set([late]);
  assert.deepEqual(g.order(paths,hidden),fresh(hidden),`${name} hide`);assert.ok(g.reusedSteps(paths)>=first.length-20,`${name} hide keeps the start`);
  assert.deepEqual(g.order(paths,new Set()),first,`${name} show again`);assert.ok(g.reusedSteps(paths)>0,`${name} show keeps a start`);
  for(let round=0;round<12;round++){const edit=new Set();for(let k=0;k<1+round%4;k++)edit.add(Math.floor(random()*paths.length));
   assert.deepEqual(g.order(paths,edit),fresh(edit),`${name} round ${round}`);}
  assert.deepEqual(g.order(paths,new Set([1]),'nearest',8),fresh(new Set([1]),8),`${name} minimum`);
  // A path replaced in place is planned again, even when it is not hidden.
  const before=paths[first[5].i];paths[first[5].i]=[[0,0],[0.5,0.5]];
  assert.deepEqual(g.order(paths,new Set()),fresh(new Set()),`${name} replaced`);paths[first[5].i]=before;
  assert.deepEqual(g.order(paths,new Set()),first,`${name} restored`);}
});
