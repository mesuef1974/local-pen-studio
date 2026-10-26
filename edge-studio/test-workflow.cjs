// Execute the actual page controller with controlled asynchronous API responses.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function fixture(){
 const elements=new Map(),calls=[],shell={dataset:{},classList:{},addEventListener(){}};
 const $=id=>{if(!elements.has(id))elements.set(id,{id,value:'',checked:false,hidden:false,disabled:false,naturalWidth:0,style:{},handlers:{},addEventListener(event,fn){this.handlers[event]=fn;},setAttribute(){},querySelectorAll(){return [];}});return elements.get(id);};
 const context=vm.createContext({document:{getElementById:$,querySelector:()=>shell,querySelectorAll:()=>[],addEventListener(){}},
  ResizeObserver:class{observe(){}},requestAnimationFrame(){},setTimeout,clearTimeout,
  fetch:async(url,options)=>{const gate=deferred();calls.push({url,body:JSON.parse(options.body),gate});return gate.promise;},
  console});
 vm.runInContext(fs.readFileSync('app.js','utf8')+`\nassign(defaults);$('auto').checked=true;globalThis.page={work,invalidate,values,applyPreset,setMethod(v){method=v;},setSource(){source='data:image/png;base64,test';sourceVersion++;},change(){ $('low').value='20';invalidate();},state:()=>({output,busy,pending,revision}),defaults};`,context);
 return {$,calls,shell,page:context.page};
}
const reply=id=>({ok:true,json:async()=>({image:'edge'+id,prepared:'prepared'+id,overlay:'overlay'+id,width:80,height:90,edgePixels:40,coverage:5,removedComponents:0,low:20,high:150,milliseconds:12,opencv:'test'})});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let f=fixture();f.page.setSource();let run=f.page.work();f.calls[0].gate.resolve(reply(1));await run;
 assert.equal(f.page.state().output.image,'edge1');assert.equal(f.$('save').disabled,false);assert.equal(f.shell.dataset.stale,'false');
 assert.equal(f.$('sourceImage').src,'prepared1','reference preview defaults to actual prepared input');
 f.$('sourceView').value='original';f.$('sourceView').onchange();
 assert.equal(f.$('sourceImage').src,'data:image/png;base64,test','original remains available without accumulated edits');
 f.$('sourceView').value='prepared';f.$('sourceView').onchange();assert.equal(f.$('sourceImage').src,'prepared1');
 f.$('auto').checked=false;f.$('sourceView').value='original';f.$('brightness').value='35';f.$('brightness').handlers.input();
 assert.equal(f.$('sourceView').value,'prepared','preparation changes switch reference to its processed preview');
 f.page.change();assert.equal(f.$('save').disabled,true,'changing a setting immediately disables stale export');
 f=fixture();f.page.setSource();f.$('auto').checked=false;run=f.page.work();f.page.change();await f.page.work();
 f.calls[0].gate.resolve(reply(1));await run;assert.equal(f.page.state().output,null,'obsolete response never published');
 assert.equal(f.calls.length,2,'queued explicit update must run even with auto disabled');
 assert.equal(f.calls[1].body.settings.low,20);f.calls[1].gate.resolve(reply(2));await flush();
 assert.equal(f.page.state().output.image,'edge2');assert.equal(f.$('save').disabled,false);assert.equal(f.$('progress').hidden,true);
 f=fixture();f.page.setSource();run=f.page.work();f.calls[0].gate.resolve({ok:false,json:async()=>({error:'اختبار خطأ'})});await run;
 assert.equal(f.$('error').textContent,'اختبار خطأ');assert.equal(f.$('progress').hidden,true);assert.equal(f.page.state().busy,false);
 const backend=fs.readFileSync('processing.py','utf8');for(const key of Object.keys(f.page.defaults))assert.ok(backend.includes(key),`backend setting missing: ${key}`);
 f=fixture();f.$('auto').checked=false;f.$('resolution').value='2000';f.$('ink').value='#abcdef';f.$('background').value='transparent';f.$('overlayOpacity').value='40';
 f.page.setMethod('sobel');f.page.applyPreset('vertical');let chosen=f.page.values();
 assert.equal(chosen.method,'sobel');assert.equal(chosen.direction,'x');assert.equal(chosen.resolution,2000);assert.equal(chosen.ink,'#abcdef');assert.equal(chosen.background,'transparent');assert.equal(chosen.overlayOpacity,40);
 f.page.applyPreset('portrait');assert.equal(f.page.values().noise,'bilateral');assert.equal(f.page.values().thin,true);
 f.page.applyPreset('balanced');assert.equal(f.page.values().thin,false,'preferences reset previous processing changes');assert.equal(f.page.values().direction,'xy');
 console.log('PASS: fresh results, stale export guard, latest response, serialized manual queue, error recovery, settings mapping');
})().catch(error=>{console.error(error);process.exitCode=1;});
