import test from 'node:test';
import assert from 'node:assert/strict';
import {LASER_DEFAULTS,laserSvg,pathLength,simplify} from './laser-export.js';
import {clipToCut,cutPathData,insideCut,readLaserTemplate,sameSheet,templateLayers} from './laser-template.js';
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
 assert.deepEqual(stats,{paths:1,dropped:0,nodesBefore:2,nodes:2,lengthMm:30,droppedLengthMm:0,retracedLengthMm:0,clippedLengthMm:0});
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

// A Misk template as its generator writes it: millimetres, one path per layer, absolute M/L/Z.
const sheet=(body,size='width="40.00mm" height="30.00mm" viewBox="0 0 40.00 30.00"')=>`<svg xmlns="http://www.w3.org/2000/svg" ${size}>\n  <title>ميدالية اختبار</title>\n${body}</svg>`;
const cutLayer='  <g id="cut"><path fill="none" stroke="#ff0000" stroke-width="0.1" fill-rule="evenodd" d="M2.000,2.000 L38.000,2.000 L38.000,28.000 L2.000,28.000 Z M5.000,5.000 L9.000,5.000 L9.000,9.000 L5.000,9.000 Z"/></g>\n';
const guideLayer='  <g id="guide"><path fill="none" stroke="#0000ff" stroke-width="0.2" stroke-dasharray="1 1" fill-rule="evenodd" d="M4.000,4.000 L36.000,4.000 L36.000,26.000 L4.000,26.000 Z"/></g>\n';
const engraveLayer='  <g id="engrave"><path fill="#000000" stroke="none" fill-rule="evenodd" d="M10.000,10.000 L20.000,10.000 L20.000,20.000 Z"/></g>\n';
const templateMapping={scale:1,x:0,y:0,paperWidth:40,paperHeight:30};

test('a Misk template gives its sheet, cut outline and guides, and its engraving is read but not written back',()=>{
 const template=readLaserTemplate(sheet(engraveLayer+cutLayer+guideLayer));
 assert.equal(template.width,40);assert.equal(template.height,30);assert.equal(template.title,'ميدالية اختبار');
 assert.equal(template.cut.length,2);assert.equal(template.guide.length,1);
 assert.deepEqual(template.engrave,[{points:[[10,10],[20,10],[20,20]],closed:true}]);
 assert.deepEqual(template.cut[1],{points:[[5,5],[9,5],[9,9],[5,9]],closed:true});
 assert.ok(sameSheet(template,templateMapping));assert.ok(!sameSheet(template,{...templateMapping,paperWidth:40.2}));
 const layers=templateLayers(template);
 assert.ok(layers.startsWith('<g id="cut" fill="none" stroke="#ff0000" stroke-width="0.1"><path fill-rule="evenodd" d="M2.000,2.000 L38.000,2.000'));
 assert.ok(layers.includes('<g id="guide" fill="none" stroke="#0000ff" stroke-width="0.2" stroke-dasharray="1 1">'));
 assert.ok(!layers.includes('engrave')&&!layers.includes('#000000'));// the drawing takes the engraving's place
 assert.equal(readLaserTemplate(sheet(engraveLayer)).engrave.length,1);// an engraving alone is a template
 assert.equal(readLaserTemplate(sheet(guideLayer)).cut.length,0);
 assert.equal(cutPathData(template),'M2.000,2.000 L38.000,2.000 L38.000,28.000 L2.000,28.000 Z M5.000,5.000 L9.000,5.000 L9.000,9.000 L5.000,9.000 Z');
 assert.equal(cutPathData(readLaserTemplate(sheet(guideLayer))),'');
});

test('the laser file carries the template layers after the score and clips the drawing to the cut',()=>{
 const template=readLaserTemplate(sheet(cutLayer+guideLayer));
 // One line inside the piece, one into the hole, one off the piece.
 const {svg,stats}=laserSvg([{p:[[12,12],[30,12]]},{p:[[6,6],[6,20]]},{p:[[20,20],[39,20]]}],templateMapping,{template,cutClearance:0});
 // The first is whole; the second keeps what is past the hole (y 9 to 20); the third stops at the outline (x 38).
 assert.equal(stats.paths,3);assert.equal(stats.clippedLengthMm,4);assert.equal(stats.lengthMm,18+11+18);
 assert.deepEqual(coords(svg).slice(0,6),[[12,12],[30,12],[6,9],[6,20],[20,20],[38,20]]);
 // A line through the hole comes out as two, one fully off the piece as none, and a bend at the outline stays joined.
 assert.deepEqual(clipToCut(template,[[3,7],[12,7]]),[[[3,7],[5,7]],[[9,7],[12,7]]]);
 assert.deepEqual(clipToCut(template,[[0,0],[1,1]]),[]);
 assert.deepEqual(clipToCut(template,[[10,12],[20,12],[20,25]]),[[[10,12],[20,12],[20,25]]]);
 const off=laserSvg([{p:[[0,0],[1,0]]},{p:[[1.8,12],[2.3,12]]}],templateMapping,{template,cutClearance:0});
 assert.equal(off.stats.paths,0);assert.equal(off.stats.dropped,1);// what is left on the piece is a dot
 assert.ok(svg.indexOf('<g id="score"')<svg.indexOf('<g id="cut"')&&svg.indexOf('<g id="cut"')<svg.indexOf('<g id="guide"'));
 assert.equal((svg.match(/<g /g)||[]).length,3);
 const full=laserSvg([{p:[[12,12],[30,12]]}],templateMapping,{template:readLaserTemplate(sheet(engraveLayer+cutLayer+guideLayer))}).svg;
 assert.deepEqual([...full.matchAll(/<g id="(\w+)"/g)].map(m=>m[1]),['score','cut','guide']);
 assert.ok(insideCut(template,[20,15]));assert.ok(!insideCut(template,[7,7]));assert.ok(!insideCut(template,[1,1]));
 assert.throws(()=>laserSvg([{p:[[0,0],[9,0]]}],{...templateMapping,paperWidth:210,paperHeight:297},{template}),/لا يطابق القالب/);
 assert.equal(laserSvg([{p:[[0,0],[9,0]]}],templateMapping,{template:readLaserTemplate(sheet(guideLayer))}).stats.clippedLengthMm,0);// no outline, nothing to clip to
});

test('lines stay a clearance away from the cut outline and run across the template engraving',()=>{
 const template=readLaserTemplate(sheet(cutLayer)),near=runs=>runs.map(run=>run.map(([x,y])=>[+x.toFixed(6),+y.toFixed(6)]));
 // The outline is the rectangle 2..38 by 2..28 with a hole 5..9 by 5..9.
 assert.deepEqual(near(clipToCut(template,[[2.5,15],[39,15]],1)),[[[3,15],[37,15]]]);// both ends pulled in
 assert.deepEqual(near(clipToCut(template,[[7,3.5],[7,20]],1)),[[[7,3.5],[7,4]],[[7,10],[7,20]]]);// between the two margins above the hole, then below it
 assert.deepEqual(near(clipToCut(template,[[2,2],[12,12]],1)),[[[3,3],[4.292893,4.292893]],[[9.707107,9.707107],[12,12]]]);// round the hole's corners
 assert.deepEqual(near(clipToCut(template,[[12,12],[20,12],[20,20]],1)),[[[12,12],[20,12],[20,20]]]);// clear of every edge
 assert.deepEqual(near(clipToCut(template,[[20,2.5],[30,2.5]],1)),[]);// a line running inside the margin
 const {svg,stats}=laserSvg([{p:[[20,20],[39,20]]}],templateMapping,{template});// one millimetre unless told otherwise
 assert.deepEqual(coords(svg).slice(0,2),[[20,20],[37,20]]);assert.equal(+stats.clippedLengthMm.toFixed(6),2);
 assert.equal(LASER_DEFAULTS.cutClearance,1);assert.throws(()=>laserSvg([],templateMapping,{template,cutClearance:-1}));
 // The engraving is the triangle (10,10) (20,10) (20,20): it is not written, so a line through it stays whole.
 const engraved=readLaserTemplate(sheet(engraveLayer+cutLayer));
 const over=laserSvg([{p:[[12,14],[30,14]]}],templateMapping,{template:engraved});
 assert.deepEqual(coords(over.svg).slice(0,2),[[12,14],[30,14]]);
 assert.equal(over.stats.lengthMm,18);assert.equal(over.stats.clippedLengthMm,0);assert.equal(over.stats.paths,1);
 assert.ok(!over.svg.includes('engrave'));assert.ok(!('coveredLengthMm' in over.stats));
});

test('a template that is not millimetre M/L/Z geometry is refused whole',()=>{
 for(const bad of [
  '','<p>not svg</p>',
  sheet(cutLayer,'width="40" height="30" viewBox="0 0 40 30"'),// no unit
  sheet(cutLayer,'width="40mm" height="30mm" viewBox="0 0 400 300"'),// user units are not millimetres
  sheet('<g id="other"><path d="M2,2 L5,5 Z"/></g>'),// no layer it knows
  sheet('<g id="engrave"><path d="M2,2 Q3,3 5,5 Z"/></g>'),// curves in the engraving
  sheet('<g id="cut"><path d="M2,2 C3,3 4,4 5,5 Z"/></g>'),// curves
  sheet('<g id="cut"><path d="m2,2 l5,5"/></g>'),// relative
  sheet('<g id="cut"><path d="M2,2 L5"/></g>'),// odd coordinate
  sheet('<g id="cut"><path d="L2,2 L5,5"/></g>'),// no start
  sheet('<g id="cut"><path d="M2,2 L50,5 Z"/></g>'),// off the sheet
  sheet('<g id="cut"><path d="M2,2 L5,5&quot;/><script>x</script>"/></g>'),
 ])assert.throws(()=>readLaserTemplate(bad));
 assert.throws(()=>readLaserTemplate(sheet(cutLayer)+' '.repeat(2_000_000)));
 // Markup beside the paths never reaches the output.
 const hostile=readLaserTemplate(sheet('<g id="cut" onload="x()"><path onclick="y()" d="M2,2 L5,5 Z"/></g>').replace('ميدالية اختبار','a</title><script>'));
 assert.ok(!/onload|onclick|script/.test(templateLayers(hostile)));assert.ok(!hostile.title.includes('<'));
});
