import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import * as geo from './geometry.js';
import {laserSvg} from './laser-export.js';
import {planDocument} from './plan-export.js';
import {paperLayout} from './paper.js';

// The files a user takes to a machine. Rearranging screens must not change a byte of them.
const paths=Array.from({length:40},(_,i)=>[[i*7%90,i*13%110],[i*11%90+.25,i*5%110+.5],[i*3%90,i*17%110]]);
const settings={paper:'A4',paperWidth:210,paperHeight:297,landscape:false,margin:15,drawScale:100,pen:.3,drawSpeed:30,travelSpeed:80,lift:.4};
const mapping=paperLayout({width:100,height:120},settings),items=geo.order(paths,new Set([3]),'nearest',0,mapping.scale);
const plan=geo.timeline(items,mapping.scale,settings.drawSpeed,settings.travelSpeed,settings.lift);plan.items=items;
const digest=text=>createHash('sha256').update(text).digest('hex').slice(0,16);
const files={
 pen:geo.svg(plan.items,mapping,settings.pen),
 laser:laserSvg(plan.items,mapping,{template:null}).svg,
 json:JSON.stringify(planDocument({plan,mapping,settings,output:{width:100,height:120,inputHash:'abc'},audit:null}),null,2),
};

const GOLDEN={"pen":"9fa2b63720222b56","laser":"d732f8c0059906bc","json":"956e2c6d32839099"};

test('pen SVG, laser SVG and plan JSON keep their exact bytes',()=>{
 assert.deepEqual(Object.fromEntries(Object.entries(files).map(([name,text])=>[name,digest(text)])),GOLDEN);
});

test('the page builds each file with the same call as before',()=>{
 const app=readFileSync(new URL('./app.js',import.meta.url),'utf8');
 for(const call of ["blobDownload(geo.svg(plan.items,mapping,read(2).pen),'image/svg+xml','pen-paths.svg')",
  "laserSvg(plan.items,mapping,{template:laserTemplate})","blobDownload(svg,'image/svg+xml','laser-score.svg')",
  "blobDownload(JSON.stringify(planDocument({plan,mapping,settings:read(2),output:flow.outputs[2],audit:currentAudit()}),null,2),'application/json','pen-paths.json')"])
  assert.ok(app.includes(call),call);
});
