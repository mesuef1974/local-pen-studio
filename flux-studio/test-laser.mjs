import test from 'node:test';
import assert from 'node:assert/strict';
import {LASER_DEFAULTS,laserSvg,pathLength,simplify} from './laser-export.js';
import {paperLayout} from './paper.js';

// One pixel is one millimetre here, so thresholds read directly.
const mapping={scale:1,x:10,y:20,paperWidth:100,paperHeight:60};
const coords=svg=>[...svg.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map(m=>[+m[1],+m[2]]);

test('laser SVG is millimetre-sized with one hairline score layer and no raster',()=>{
 const {svg,stats}=laserSvg([{p:[[0,0],[30,0]]}],mapping);
 assert.ok(svg.includes('width="100mm" height="60mm" viewBox="0 0 100 60"'));
 assert.ok(svg.includes('<g id="score" fill="none" stroke="#000000" stroke-width="0.1"'));
 assert.ok(!svg.includes('<image'));
 assert.deepEqual(coords(svg),[[10,20],[40,20]]);
 assert.deepEqual(stats,{paths:1,dropped:0,nodesBefore:2,nodes:2,lengthMm:30,droppedLengthMm:0,retracedLengthMm:0});
});

test('a segment drawn twice is burnt once, whichever stroke or direction repeats it',()=>{
 // Out along a line, back over it, then on: the return trip is cut and the rest becomes its own path.
 const back=laserSvg([{p:[[0,0],[10,0],[0,0],[0,10]]}],mapping);
 assert.deepEqual(coords(back.svg),[[10,20],[20,20],[10,20],[10,30]]);
 assert.equal((back.svg.match(/<path /g)||[]).length,2);
 assert.equal(back.stats.retracedLengthMm,10);assert.equal(back.stats.lengthMm,20);assert.equal(back.stats.dropped,0);
 // A later stroke repeating part of an earlier one, reversed, keeps only its new part.
 const later=laserSvg([{p:[[0,0],[10,0],[20,0]]},{p:[[20,0],[10,0],[10,5]]}],mapping);
 assert.deepEqual(coords(later.svg),[[10,20],[30,20],[20,20],[20,25]]);
 assert.equal(later.stats.retracedLengthMm,10);assert.equal(later.stats.paths,2);
 // A stroke that only repeats leaves nothing, and what remains between two cuts is dropped if it is a dot.
 const whole=laserSvg([{p:[[0,0],[10,0]]},{p:[[10,0],[0,0]]}],mapping);
 assert.equal(whole.stats.paths,1);assert.equal(whole.stats.retracedLengthMm,10);assert.equal(whole.stats.dropped,0);
 const dot=laserSvg([{p:[[0,0],[10,0],[10,.3]]},{p:[[0,0],[10,0],[10,.3],[10,.6]]}],mapping);
 assert.equal(dot.stats.paths,1);assert.equal(dot.stats.dropped,1);assert.ok(Math.abs(dot.stats.droppedLengthMm-.3)<1e-9);
 // Two passes a hair apart share no vertex in the plan but become one segment once simplified.
 const hair=laserSvg([{p:[[0,0],[5,.01],[10,0]]},{p:[[10,0],[5,-.01],[0,0],[0,8]]}],mapping);
 assert.deepEqual(coords(hair.svg),[[10,20],[20,20],[10,20],[10,28]]);
 assert.equal(hair.stats.retracedLengthMm,10);assert.equal(hair.stats.lengthMm,18);
 // Lines that merely cross or touch are not repeats.
 assert.equal(laserSvg([{p:[[0,0],[10,0]]},{p:[[5,-5],[5,5]]},{p:[[10,0],[10,9]]}],mapping).stats.retracedLengthMm,0);
});

test('dots and strokes shorter than the minimum are left out and counted',()=>{
 const items=[{p:[[0,0],[0,0]]},{p:[[5,5]]},{p:[[0,0],[.4,0]]},{p:[[0,0],[.5,0]]},{p:[[0,0],[9,0]]}];
 const {svg,stats}=laserSvg(items,mapping);
 assert.equal((svg.match(/<path /g)||[]).length,2);
 assert.equal(stats.paths,2);assert.equal(stats.dropped,3);
 assert.ok(Math.abs(stats.droppedLengthMm-.4)<1e-9);
 assert.equal(laserSvg(items,mapping,{minLength:0}).stats.paths,3);// zero-length strokes never burn
});

test('simplification keeps ends and corners and stays within the tolerance',()=>{
 const wobble=Array.from({length:101},(_,i)=>[i*.1,i%2?.01:0]);
 assert.deepEqual(simplify(wobble,.05),[[0,0],[10,0]]);
 const corner=[[0,0],[5,.01],[10,0],[10,5],[10,10]];
 assert.deepEqual(simplify(corner,.05),[[0,0],[10,0],[10,10]]);
 assert.deepEqual(simplify(corner,0),corner);
 const loop=[[0,0],[4,0],[4,4],[0,4],[0,0]];
 assert.deepEqual(simplify(loop,.05),loop);// coincident ends do not collapse a closed outline
 const {stats}=laserSvg([{p:wobble}],mapping);
 assert.equal(stats.nodesBefore,101);assert.equal(stats.nodes,2);assert.equal(stats.lengthMm,10);
});

test('plan order and direction are preserved',()=>{
 const {svg}=laserSvg([{p:[[20,0],[10,0]]},{p:[[0,0],[5,0]]}],mapping);
 assert.deepEqual(coords(svg),[[30,20],[20,20],[10,20],[15,20]]);
});

test('options are validated',()=>{
 assert.throws(()=>laserSvg([],mapping,{minLength:-1}));
 assert.throws(()=>laserSvg([],mapping,{tolerance:NaN}));
 assert.throws(()=>laserSvg([],mapping,{strokeWidth:0}));
 assert.throws(()=>laserSvg([],mapping,{color:'red'}));
 assert.equal(laserSvg([],mapping).stats.paths,0);
 assert.equal(LASER_DEFAULTS.minLength,.5);
 assert.equal(pathLength([[0,0],[3,4]]),5);
});

test('a product smaller than 50 mm is a valid custom sheet',()=>{
 const m=paperLayout({width:400,height:600},{paper:'custom',paperWidth:45,paperHeight:60,landscape:false,margin:3,pen:.1,drawScale:100});
 assert.equal(m.paperWidth,45);assert.equal(m.paperHeight,60);
 assert.throws(()=>paperLayout({width:400,height:600},{paper:'custom',paperWidth:19,paperHeight:60,landscape:false,margin:3,pen:.1,drawScale:100}));
});
