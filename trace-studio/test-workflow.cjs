const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function fixture(){const map=new Map(),calls=[],timers=new Map();let n=0;const $=id=>{if(!map.has(id))map.set(id,{value:'',checked:false,hidden:false,disabled:false,naturalWidth:0,style:{},textContent:'',insertAdjacentHTML(){},setAttribute(){},addEventListener(){}});return map.get(id);};
 const shell={dataset:{},addEventListener(){},classList:{}};
 const context=vm.createContext({createPreparation:()=>({load:async()=>{}}),document:{getElementById:$,querySelector:()=>shell,querySelectorAll:()=>[],addEventListener(){}},ResizeObserver:class{observe(){}},requestAnimationFrame(){},setTimeout(fn){timers.set(++n,fn);return n;},clearTimeout(id){timers.delete(id);},fetch:async(path,options)=>{const gate=deferred();calls.push({path,body:JSON.parse(options.body),gate});return gate.promise;}});
 vm.runInContext(fs.readFileSync('app.js','utf8').replace(/^import .*;\r?\n/gm,'')+`\nfor(const [id,value]of Object.entries(defaults))$(id).value=value;$('auto').checked=true;globalThis.page={run,values,applyRecipe,setSource(){working=original='png';meta={ready:true,transparent:true,colored:false};},change(){schedule();},state:()=>({output,revision,busy,approved})};`,context);return {$,page:context.page,calls,timers,shell};}
const response={ok:true,json:async()=>({preview:'rendered-png',width:80,height:90,segments:10,layers:4,vectorBytes:1000,seconds:1,downloads:{'vector.svg':'/v'}})};
(async()=>{let f=fixture();f.page.setSource();f.page.applyRecipe('fine');assert.equal(f.calls.length,0,'no automatic first trace before review');assert.equal(f.page.values().median,1);assert.equal(f.page.values().component,5);
 f.$('run').onclick();f.calls[0].gate.resolve(response);await new Promise(r=>setImmediate(r));assert.equal(f.$('saveSvg').disabled,false);assert.equal(f.shell.dataset.stale,'false');
 f.page.change();assert.equal(f.$('saveSvg').disabled,true);assert.equal(f.timers.size,1,'auto update only after first approved conversion');
 f=fixture();f.page.setSource();const run=f.page.run();f.page.change();f.calls[0].gate.resolve(response);await run;assert.equal(f.page.state().output,null,'outdated conversion must not be published');assert.equal(f.$('saveSvg').disabled,true);
 f=fixture();f.$('resolution').value='1024';f.page.applyRecipe('smooth');assert.equal(f.page.values().resolution,1024);assert.equal(f.page.values().alphamax,1.3);
 f.page.applyRecipe('original');assert.equal(f.page.values().alphamax,1.15);assert.equal(f.page.values().resolution,1024);
 console.log('PASS: review before first conversion, recipe settings, stale export guard, obsolete result, preserved resolution');
})().catch(error=>{console.error(error);process.exitCode=1;});
