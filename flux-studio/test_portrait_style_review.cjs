// Local contract test only; image decoding and Canvas are mocked, not a browser screenshot.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
if(!process.argv[2])throw new Error('Pass the generated comparison.html.');
const text=fs.readFileSync(process.argv[2],'utf8'),script=text.match(/<script>([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(Buffer.from(script.match(/atob\('([^']+)'\)/)[1],'base64').toString());
assert.equal(data.groups.length,6);assert.equal(data.cases.length,18);
const calls=[],downloads=[];
const ctx=new Proxy({}, {get:(_,name)=>(...args)=>calls.push([name,...args]),set:(_,key,value)=>{calls.push(['set',key,value]);return true;}});
const elements={};
for(const id of ['stage','glow','export','status',...data.cases.flatMap(c=>['canvas-'+c.id,'approve-'+c.id,'save-'+c.id,'message-'+c.id])]){
    elements[id]={value:id==='stage'?'final':'',checked:id==='glow',disabled:false,hidden:id.startsWith('canvas-'),listeners:{},
        getContext(){return ctx;},toDataURL(){return 'data:image/png;base64,AA==';},
        addEventListener(event,fn){this.listeners[event]=fn;}};
}
let saved=null;
const sandbox={console,Blob,Date,setTimeout:()=>0,atob:s=>Buffer.from(s,'base64').toString(),
    localStorage:{getItem(){return saved;},setItem(key,value){saved=value;}},
    URL:{createObjectURL(blob){downloads.push(blob);return 'blob:mock';},revokeObjectURL(){}},
    Image:class{async decode(){assert(this.src.startsWith('data:image/png;base64,'));}},
    document:{getElementById:id=>elements[id],createElement:()=>({getContext(){return ctx;},toDataURL(){return 'data:image/png;base64,AA==';},click(){}})}};
vm.runInNewContext(script,sandbox);
const flush=()=>new Promise(setImmediate);
(async()=>{
    await flush();
    const valid=data.cases.filter(c=>c.state==='complete'&&c.lineValid);
    assert(valid.length>0);
    for(const c of data.cases){const checkbox=elements['approve-'+c.id];assert.equal(checkbox.checked,false);assert.equal(checkbox.disabled,!valid.includes(c));if(valid.includes(c)){assert.equal(elements['canvas-'+c.id].width,c.width);assert.equal(elements['canvas-'+c.id].height,c.height);}}
    const first=valid[0],checkbox=elements['approve-'+first.id];checkbox.checked=true;checkbox.listeners.change();
    assert(saved.includes('"automaticAction":false'));assert(saved.includes(first.baseHash));assert(!saved.includes('renderedPNG'));
    elements.stage.value='raw';await elements.stage.listeners.change();
    for(const c of valid)assert(elements['approve-'+c.id].disabled);
    elements.stage.value='final';await elements.stage.listeners.change();assert(checkbox.checked);
    elements.glow.checked=false;await elements.glow.listeners.change();assert(!checkbox.checked);
    elements.glow.checked=true;await elements.glow.listeners.change();assert(checkbox.checked);
    await elements.export.listeners.click();assert.equal(downloads.length,1);
    let exported=JSON.parse(await downloads[0].text());assert.equal(exported.automaticAction,false);assert.equal(exported.selections.length,1);
    assert(exported.selections[0].renderedPNG.startsWith('data:image/png;base64,'));
    assert.equal(exported.selections[0].snapshotMethod,'native canvas at selection');
    // Simulate reopening: persisted metadata survives; a fresh native render is explicitly labelled.
    vm.runInNewContext(script,{...sandbox});await flush();await elements.export.listeners.click();
    exported=JSON.parse(await downloads.at(-1).text());assert.equal(exported.selections[0].snapshotMethod,'re-render at export from persisted selection settings');
    console.log(`PASS: six source groups, 18 slots, ${valid.length} ready line outputs; initial unchecked, full-frame rendering, stage guard, persistence, glow isolation, exact snapshot export fields. Mock DOM/Canvas only.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
