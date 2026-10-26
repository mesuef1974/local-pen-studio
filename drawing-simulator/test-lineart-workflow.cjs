// Run the real page controller with a small DOM and controlled API responses.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function fixture(inferenceGate=null){
 const elements=new Map(),calls=[],timers=new Map();let timerId=0;
 const checkbox=new Set(['auto','binary']);
 function $(id){if(!elements.has(id))elements.set(id,{id,value:'0',type:checkbox.has(id)?'checkbox':'number',checked:false,hidden:id==='result',disabled:false,textContent:'',src:'',
  addEventListener(){},setAttribute(){},closest(){return {};},getContext(){return {clearRect(){}};}});return elements.get(id);}
 const started=deferred();
 const context=vm.createContext({$,createImageEditor:()=>({open(){}}),setupTools:()=>({clear(){},resize(){},url:()=>''}),
  setActivity:phase=>context.document.body.dataset.activity=phase,setSummary(){},
  document:{body:{dataset:{stage:'source'}},dispatchEvent(){},addEventListener(){}},
  CustomEvent:class{},URLSearchParams,location:{search:''},
  setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);},
  fetch:async(path,options)=>{const body=JSON.parse(options.body);calls.push({path,body});let data;
   if(path==='/api/lineart'){started.resolve();if(inferenceGate)await inferenceGate.promise;data={image:'raw-'+body.image,width:80,height:80,seconds:1,device:'test'};}
   else if(body.action==='pre')data={image:'prepared-'+body.settings.brightness,width:80,height:80,newlyClippedHighlightsPercent:0};
   else data={image:'cleaned-'+body.image+'-'+body.settings.strength,removedComponents:0,protectedPixels:0,inkPixelsBefore:1,inkPixelsAfter:1};
   return {ok:true,json:async()=>data};}});
 const source=fs.readFileSync('lineart.js','utf8').replace(/^import .*;\r?\n/gm,'');
 vm.runInContext(source+`\nresetInputFields();$('resolution').value='768';$('strength').value='100';$('threshold').value='180';globalThis.controller={run,invalidate,prepareInput,setSource(){source='source';sourceVersion++;$('original').hidden=false;},state:()=>({raw,result,cacheKey,busy,revision})};`,context);
 return {$,calls,timers,started,context,controller:context.controller};
}
(async()=>{
 let f=fixture();f.controller.setSource();await f.$('run').onclick();
 assert.equal(f.calls.filter(c=>c.path==='/api/lineart').length,1,'manual button must invoke inference');
 assert.ok(f.controller.state().result);assert.equal(f.$('modelProgress').value,3);assert.equal(f.context.document.body.dataset.resultStale,'false');
 f.controller.invalidate();assert.equal(f.context.document.body.dataset.resultStale,'true');
 assert.equal(f.$('resultNotice').hidden,false,'old output must be explicitly marked stale');
 await f.$('run').onclick();assert.equal(f.calls.filter(c=>c.path==='/api/lineart').length,1,'post changes reuse model output');

 const gate=deferred();f=fixture(gate);f.controller.setSource();const first=f.controller.run();await f.started.promise;
 f.$('strength').value='140';f.controller.invalidate();gate.resolve();await first;
 assert.ok(f.controller.state().raw,'unchanged input may cache the in-flight model result');
 assert.equal(f.controller.state().result,'','old cleanup must not be published');
 await f.controller.run();assert.equal(f.calls.filter(c=>c.path==='/api/lineart').length,1);
 assert.ok(f.controller.state().result.endsWith('-140'),'latest cleanup must be used');

 const otherGate=deferred();f=fixture(otherGate);f.controller.setSource();const obsolete=f.controller.run();await f.started.promise;
 f.$('brightness').value='20';f.controller.invalidate(true);otherGate.resolve();await obsolete;
 assert.equal(f.controller.state().raw,'','changed input must reject the old model result');
 await f.controller.run();assert.ok(f.controller.state().raw.includes('prepared-20'));
 assert.equal(f.calls.filter(c=>c.path==='/api/lineart').length,2);
 f=fixture();f.controller.setSource();const healthyFetch=f.context.fetch;let rejected=false;
 f.context.fetch=async(path,options)=>{if(path==='/api/lineart'&&!rejected){rejected=true;return {ok:false,status:429,json:async()=>({error:'busy'})};}return healthyFetch(path,options);};
 await f.controller.run();assert.equal(f.context.document.body.dataset.activity,'pending');assert.equal(f.timers.size,1);
 const retry=[...f.timers.values()][0];f.timers.clear();await retry();assert.ok(f.controller.state().result,'busy model must retry even in manual mode');
 f=fixture();f.controller.setSource();f.context.fetch=async()=>({ok:false,status:429,json:async()=>({error:'busy'})});
 await f.controller.run();assert.equal(f.timers.size,1);f.controller.invalidate();assert.equal(f.timers.size,0,'changing settings cancels obsolete retries');
 console.log('PASS: manual update, stale indication, cached inference, rejection of obsolete input, busy retry and cancellation');
})().catch(error=>{console.error(error);process.exitCode=1;});
