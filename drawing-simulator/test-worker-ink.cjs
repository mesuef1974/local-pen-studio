const fs=require('fs'),vm=require('vm'),assert=require('assert');
let result;const context={self:{postMessage:r=>result=r},Math,Float32Array,Uint8Array,Map,Set};vm.createContext(context);
context.importScripts=()=>vm.runInContext(fs.readFileSync(__dirname+'/path-refinement.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/trace-worker.js','utf8'),context);
const paths=[[[2,3],[4,3],[6,4]],[[7,4],[9,4],[11,4]]];
context.self.onmessage({data:{id:1,width:16,height:16,pixels:new Uint8Array(16*16*4).fill(255),basePaths:paths,preserveInk:true,executionLevel:100,protectFeatures:false,shading:false,epsilon:2,joinGapMm:5,curveSmoothMm:5,paper:{width:20,height:20,margin:1},featureRegion:null}});
assert(!result.error);assert.equal(result.joinedCount,0);assert.equal(result.pointsBefore,result.pointsAfter);
const canonical=p=>JSON.stringify(p.map(x=>JSON.stringify(x)).sort());assert.equal(canonical(result.paths),canonical(paths));
console.log('PASS: preserveInk overrides joining, smoothing and simplification without changing coordinates');
