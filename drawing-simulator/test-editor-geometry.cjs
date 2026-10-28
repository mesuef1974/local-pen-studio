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
context.tool='circle';
for(const [start,end]of [[[30,40],[170,100]],[[170,100],[30,40]]]){
 const [, ,w,h]=context.crop(start,end);assert.equal(w,h);
}
assert.match(source,/\['circle','دائرة · O'/);assert.match(source,/\['circle','ellipse'\]\.includes\(tool\)/);
console.log('PASS: circle tool stays round and participates in shape drawing');
let compositeAtDraw='';
const targetContext={globalCompositeOperation:'source-over',drawImage(){compositeAtDraw=this.globalCompositeOperation;}};
const mergeContext=vm.createContext({hasSelection:false,tool:'erase',activeDocument:()=>({canvas:{getContext:()=>targetContext}}),localSelection:()=>null,renderComposite:()=>{},
 layer:{width:10,height:10,getContext:()=>({globalCompositeOperation:'source-over',drawImage:()=>{},clearRect:()=>{}})}});
const mergeSource=source.slice(source.indexOf(' function mergeLayer(){'),source.indexOf(' function choose('));
vm.runInContext(mergeSource+';mergeLayer();',mergeContext);
assert.equal(compositeAtDraw,'destination-out');assert.equal(targetContext.globalCompositeOperation,'source-over');
console.log('PASS: eraser removes pixels with destination-out and restores normal compositing');

const resizeSource=source.slice(source.indexOf(' function resizeRect('),source.indexOf(' async function restore('));
const resizeContext=vm.createContext({canvas:{width:800,height:600}});vm.runInContext(resizeSource+';globalThis.resizeRect=resizeRect;',resizeContext);
const scaled=resizeContext.resizeRect({x:20,y:30,width:100,height:50},'se',[10000,10000]);
assert.ok(scaled.width<=3200&&scaled.height<=3200);assert.ok(Math.abs(scaled.width/scaled.height-2)<0.001);
console.log('PASS: layer resize preserves aspect ratio and caps raster size');

const layerItems=[{id:'base'},{id:'one'},{id:'two'}],layerOps=[];
const reorderSource=source.slice(source.indexOf(' function reorderDocument('),source.indexOf(' function moveDocument('));
const reorderContext=vm.createContext({documents:layerItems,save:label=>layerOps.push(label),renderComposite:()=>{},renderLayers:()=>{}});
vm.runInContext(reorderSource+';reorderDocument("base","two");',reorderContext);
assert.deepEqual(layerItems.map(item=>item.id),['one','two','base']);assert.equal(layerOps.length,1);
console.log('PASS: layer ordering moves the selected layer in front without merging');

const pixels=new Uint8ClampedArray(10*8*4);let mask={width:10,height:8,getContext:()=>({getImageData:()=>({data:pixels})})};
const boundSource=source.slice(source.indexOf(' function actualSelectionBounds(){'),source.indexOf(' function setSelection('));
const boundsContext=vm.createContext({selection:mask});vm.runInContext(boundSource+';globalThis.bounds=actualSelectionBounds;',boundsContext);
assert.equal(boundsContext.bounds(),null);
pixels[(2*10+3)*4]=255;pixels[(5*10+7)*4]=255;
assert.deepEqual(Array.from(boundsContext.bounds()),[3,2,5,4]);
console.log('PASS: fixed-aspect cropping in four directions, empty and exact selection bounds');
let releaseRestore;const pendingRestore=new Promise(resolve=>{releaseRestore=resolve;});
const controls={edCommit:{disabled:false},edError:{}};
const historyContext=vm.createContext({history:[{},{}],future:[],busy:false,$:id=>controls[id],state:()=>({}),updateHistory:()=>{},restore:()=>pendingRestore});
const historySource=source.slice(source.indexOf(' async function undo(){'),source.indexOf(' function alphaMask(){'));
vm.runInContext(historySource+';globalThis.undoAction=undo;',historyContext);
const firstUndo=historyContext.undoAction(),secondUndo=historyContext.undoAction();
assert.equal(historyContext.history.length,1);assert.equal(historyContext.future.length,1);assert.equal(controls.edCommit.disabled,true);
releaseRestore();Promise.all([firstUndo,secondUndo]).then(()=>{assert.equal(historyContext.busy,false);assert.equal(controls.edCommit.disabled,false);console.log('PASS: repeated undo cannot race an unfinished image restore');}).catch(error=>{console.error(error);process.exitCode=1;});
const cancelSource=source.slice(source.indexOf('overlay.onpointercancel=()=>'),source.indexOf(' async function command('));
const cancelContext=vm.createContext({overlay:{},drag:{painting:true,future:[{redo:true}]},history:[{},{}],future:[],layer:{width:10,height:10,getContext:()=>({clearRect:()=>{}})},redraw:()=>{},updateHistory:()=>{}});
vm.runInContext(cancelSource,cancelContext);cancelContext.overlay.onpointercancel();
assert.equal(cancelContext.drag,null);assert.equal(cancelContext.history.length,1);assert.equal(cancelContext.future[0].redo,true);
console.log('PASS: cancelling a pointer gesture discards its uncommitted stroke and restores redo');
