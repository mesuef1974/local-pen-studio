import test from 'node:test';
import assert from 'node:assert/strict';
import {Workflow} from './workflow.js';
import * as g from './geometry.js';

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
test('SVG has physical units and pure selected paths',()=>{const svg=g.svg([{p:[[0,0],[100,100]]}],g.layout(101,101),.3);assert.ok(svg.includes('width="210mm"'));assert.ok(svg.includes('stroke-width="0.3"'));assert.ok(!svg.includes('<image'));assert.equal((svg.match(/<path /g)||[]).length,1);});

test('text-only review has no unrelated source reference and does not alter timing settings',()=>{const w=new Workflow();w.reviewImage({image:'generated',width:512,height:512},'');assert.equal(w.outputs[1].reference,'');assert.equal(w.original,'generated');assert.deepEqual(w.approved,[true,false]);assert.equal(w.canEnter(2),false);});
