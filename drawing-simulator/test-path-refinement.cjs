const fs=require('fs'),vm=require('vm'),assert=require('assert');
const scope={};vm.createContext(scope);vm.runInContext(fs.readFileSync(__dirname+'/path-refinement.js','utf8'),scope);
const opts={joinGapPixels:1.2,smoothPixels:0,evidence:()=>10,protectedFlags:[true,false]};
for(const a of [[[0,0],[2,0],[4,0]],[[4,0],[2,0],[0,0]]]){
 for(const b of [[[5,0],[7,0],[9,0]],[[9,0],[7,0],[5,0]]]){
  const r=scope.refinePenPaths([a,b],opts);assert.equal(r.paths.length,1);assert.equal(r.joins,1);assert.equal(r.protectedFlags[0],true);
 }
}
assert.equal(scope.refinePenPaths([[[0,0],[2,0],[4,0]],[[5,0],[7,0],[9,0]]],{...opts,evidence:()=>0}).joins,0);
assert.equal(scope.refinePenPaths([[[0,0],[2,0],[4,0]],[[4,1],[4,3],[4,5]]],opts).joins,0);
console.log('PASS: four endpoint orientations, protection propagation, unsupported bridges and corners rejected');
