import test from 'node:test';
import assert from 'node:assert/strict';
import {isApprovedVector,MAX_APPROVED_PATHS} from './approved-vectors.mjs';

function vector(count){
 return {width:2,height:2,paths:Array.from({length:count},()=>[[0,0],[1,1]])};
}

test('approved-vector import limit accepts the supported boundaries',()=>{
 assert.equal(MAX_APPROVED_PATHS,10_000);
 for(const count of [6_000,6_001,10_000])
  assert.equal(isApprovedVector(vector(count),2,2),true,`${count} paths`);
 assert.equal(isApprovedVector(vector(10_001),2,2),false,'10,001 paths');
});

test('approved-vector import still rejects malformed geometry',()=>{
 assert.equal(isApprovedVector({...vector(1),width:3},2,2),false);
 assert.equal(isApprovedVector({width:2,height:2,paths:[[[0,0],[2,1]]]},2,2),false);
 assert.equal(isApprovedVector({width:2,height:2,paths:[[[0,0],[Number.NaN,1]]]},2,2),false);
});
