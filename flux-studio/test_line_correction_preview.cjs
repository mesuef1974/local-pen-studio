// Offline DOM/canvas contract test. Does not claim real browser or screenshot coverage.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
if(!process.argv[2])throw new Error('Pass generated preview HTML path.');
const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(Buffer.from(script.match(/atob\('([^']+)'\)/)[1],'base64').toString());
const ids=['sample','previous','next','background','opacity','showLines','showChanges','focus','regions',
           'side','zoom','opacityValue','zoomValue','status','before','after','operations',
           'downloadPng','downloadReport','summaryRows','beforeFullscreen','afterFullscreen'];
let fullscreenCalls=0,reportClicks=0;
const calls=[];
const ctx=new Proxy({}, {get:(_,method)=>(...args)=>calls.push([method,...args]),set:(_,key,value)=>{calls.push(['set',key,value]);return true;}});
const elements=Object.fromEntries(ids.map(id=>[id,{
    value: id==='zoom'?'100':id==='opacity'?'90':id==='background'?'negative':'',
    checked:['showLines','showChanges','focus'].includes(id),style:{},listeners:{},children:[],
    parentElement:{async requestFullscreen(){fullscreenCalls++;}},
    append(child){this.children.push(child);},getContext(){return ctx;},
    addEventListener(event,fn){this.listeners[event]=fn;}
}]));
const sandbox={
    console,Blob,setTimeout:()=>0,
    URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},
    atob:value=>Buffer.from(value,'base64').toString(),
    Image:class{async decode(){assert(this.src.startsWith('data:image/png;base64,'));}},
    document:{getElementById:id=>elements[id],querySelector:()=>({classList:{toggle(){}}}),
        createElement:()=>({append(){},getContext(){return ctx;},click(){reportClicks++;}})}
};
vm.runInNewContext(script,sandbox);
const flush=()=>new Promise(setImmediate);
(async()=>{
    await flush();
    assert(calls.some(c=>c[0]==='set'&&c[1]==='globalCompositeOperation'&&c[2]==='source-in'));
    assert(calls.some(c=>c[0]==='set'&&c[1]==='fillStyle'&&c[2]==='#00ff66'));
    assert(calls.some(c=>c[0]==='set'&&c[1]==='shadowBlur'&&c[2]===4));
    assert.equal(elements.sample.children.length,data.samples.length);
    assert.equal(elements.summaryRows.children.length,data.samples.length);
    for(const row of data.samples){
        elements.sample.value=row.id;
        for(const mode of ['negative','gray','color','white','evidence']){
            elements.background.value=mode;
            await elements.sample.listeners.change();
            assert(!elements.status.textContent.startsWith('تعذر العرض'));
            assert.equal(elements.before.width,row.focus[2]-row.focus[0]);
            assert.equal(elements.after.height,row.focus[3]-row.focus[1]);
            assert.equal(elements.downloadPng.href,data.images[row.images.afterTransparent]);
        }
        elements.focus.checked=false;await elements.focus.listeners.change();
        assert.equal(elements.before.width,row.width);
        elements.focus.checked=true;
    }
    elements.showLines.checked=false;elements.showChanges.checked=false;
    elements.background.value='white';calls.length=0;await elements.showLines.listeners.change();
    assert(!calls.some(c=>c[0]==='drawImage'));
    elements.zoom.value='800';await elements.zoom.listeners.input();
    assert.equal(elements.after.style.width,'800%');
    elements.sample.value=data.samples[0].id;await elements.sample.listeners.change();
    assert(elements.previous.disabled);
    elements.next.listeners.click();await flush();
    assert.equal(elements.sample.value,data.samples[1].id);
    elements.beforeFullscreen.listeners.click();await flush();assert.equal(fullscreenCalls,1);
    elements.downloadReport.listeners.click();assert.equal(reportClicks,1);
    console.log(`PASS: ${data.samples.length} samples × five backgrounds; focus, layers, zoom, navigation, downloads and fullscreen invocation. Mock DOM/canvas only.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
