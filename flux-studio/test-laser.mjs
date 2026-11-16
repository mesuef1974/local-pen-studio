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
 assert.deepEqual(stats,{paths:1,dropped:0,nodesBefore:2,nodes:2,lengthMm:30,droppedLengthMm:0});
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
