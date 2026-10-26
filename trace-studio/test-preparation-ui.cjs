const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function fixture(gate){const elements=new Map(),calls=[],accepted=[],timers=new Map();let n=0;const defaults={'prepBackground':'auto','prepStyle':'tones','prep-levels':12,'prep-denoise':45,'prep-contrast':110,'prep-brightness':0,'prep-tolerance':25};
const $=id=>{if(!elements.has(id))elements.set(id,{id,value:defaults[id]??'',disabled:id==='stageTrace',checked:false,hidden:false,naturalWidth:0,style:{},dataset:{},setAttribute(){},insertAdjacentHTML(){}});return elements.get(id);};
const context=vm.createContext({document:{getElementById:$,body:{dataset:{}},querySelectorAll:()=>[],addEventListener(){}},FileReader:class{readAsDataURL(file){this.result=file.data;this.onload();}},ResizeObserver:class{observe(){}},requestAnimationFrame(){},setTimeout(fn){timers.set(++n,fn);return n;},clearTimeout(id){timers.delete(id);}});
vm.runInContext(fs.readFileSync('preparation-ui.js','utf8').replace('export function','function')+';globalThis.setup=createPreparation;',context);
const ready={width:80,height:100,ready:true,transparent:true,colored:false};
const api=async(path,body)=>{calls.push({path,body});if(path==='/api/import')return {image:'normalized-photo',meta:{...ready,ready:false,transparent:false,colored:true}};if(gate)await gate.promise;return {image:'prepared-photo',meta:ready,seconds:1,backgroundCached:false};};
const controller=context.setup(api,{error(){},invalidate(){},busy(){},download(){},accept(...values){accepted.push(values);}});
return {$,controller,calls,accepted};}
(async()=>{let f=fixture();await f.controller.load({size:10,name:'photo.jpg',data:'jpeg'});assert.equal(f.$('approvePreparation').disabled,true,'raw photo must not enter Trace');assert.equal(f.calls.length,1);
 await f.$('prepRun').onclick();assert.equal(f.$('approvePreparation').disabled,false);f.$('approvePreparation').onclick();assert.equal(f.accepted.length,1);assert.equal(f.accepted[0][0],'prepared-photo');assert.equal(f.accepted[0][1],'normalized-photo','original remains separate');
 f.$('prep-brightness').value=20;f.$('prep-brightness').oninput();assert.equal(f.$('approvePreparation').disabled,true);assert.equal(f.$('stageTrace').disabled,true);
 const gate=deferred();f=fixture(gate);await f.controller.load({size:10,name:'photo.webp',data:'webp'});const run=f.$('prepRun').onclick();f.$('prep-denoise').value=75;f.$('prep-denoise').oninput();gate.resolve();await run;assert.equal(f.$('approvePreparation').disabled,true,'stale preparation cannot be approved');
 console.log('PASS: photo import, mandatory preparation approval, original preserved, dirty and obsolete preparations blocked');
})().catch(e=>{console.error(e);process.exitCode=1;});
