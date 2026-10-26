const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('image-editor.js','utf8');
const cropSource=source.slice(source.indexOf(' function rect(a,b){'),source.indexOf(' function drawStroke'));
const context=vm.createContext({canvas:{width:300,height:200},tool:'crop',$:()=>({value:'0.8'})});
vm.runInContext(cropSource+';globalThis.crop=rect;',context);
for(const [start,end]of [[[50,50],[150,150]],[[150,150],[50,50]],[[50,150],[150,50]],[[150,50],[50,150]]]){
 const [x,y,w,h]=context.crop(start,end);
 assert.equal(w/h,.8);assert.ok(x>=0&&y>=0&&x+w<=300&&y+h<=200);
 assert.ok(start[0]===x||start[0]===x+w);assert.ok(start[1]===y||start[1]===y+h);
}
const pixels=new Uint8ClampedArray(10*8*4);let mask={width:10,height:8,getContext:()=>({getImageData:()=>({data:pixels})})};
const boundSource=source.slice(source.indexOf(' function actualSelectionBounds(){'),source.indexOf(' function setSelection('));
const boundsContext=vm.createContext({selection:mask});vm.runInContext(boundSource+';globalThis.bounds=actualSelectionBounds;',boundsContext);
assert.equal(boundsContext.bounds(),null);
pixels[(2*10+3)*4]=255;pixels[(5*10+7)*4]=255;
assert.deepEqual(Array.from(boundsContext.bounds()),[3,2,5,4]);
console.log('PASS: fixed-aspect cropping in four directions, empty and exact selection bounds');
