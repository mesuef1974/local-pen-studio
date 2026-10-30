// Offline DOM/canvas contract test. Does not claim real browser or screenshot coverage.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
if(!process.argv[2])throw new Error('Pass generated preview HTML path.');
const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(Buffer.from(script.match(/atob\('([^']+)'\)/)[1],'base64').toString());
const ids=['approve-before','approve-after','approve-final','selectionStatus','downloadSelections','sample','previous','next','background','opacity','showLines','showChanges','focus','regions',
           'side','zoom','opacityValue','zoomValue','status','before','after','operations',
           'includeGlow','final','finalFullscreen','downloadFinal','downloadPng','downloadReport','summaryRows','beforeFullscreen','afterFullscreen'];
let fullscreenCalls=0,reportClicks=0;
const calls=[];
const ctx=new Proxy({}, {get:(_,method)=>(...args)=>calls.push([method,...args]),set:(_,key,value)=>{calls.push(['set',key,value]);return true;}});
const elements=Object.fromEntries(ids.map(id=>[id,{
    value: id==='zoom'?'100':id==='opacity'?'90':id==='background'?'negative':'',
    checked:['showLines','showChanges','includeGlow'].includes(id),style:{},listeners:{},children:[],
    parentElement:{async requestFullscreen(){fullscreenCalls++;}},
    append(child){this.children.push(child);},getContext(){return ctx;},toDataURL(){return 'data:image/png;base64,AA==';},
    addEventListener(event,fn){this.listeners[event]=fn;}
}]));
const sandbox={
    console,Blob,setTimeout:()=>0,localStorage:{saved:null,getItem(){return this.saved;},setItem(key,value){this.saved=value;}},
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
    assert(calls.some(c=>c[0]==='set'&&c[1]==='shadowBlur'&&c[2]===4));
    assert.equal(elements.sample.children.length,data.samples.length);
    assert.equal(elements.summaryRows.children.length,data.samples.length);
    for(const row of data.samples){
        elements.sample.value=row.id;elements.focus.checked=true;
        for(const mode of ['negative','gray','color','white','evidence']){
            elements.background.value=mode;
            await elements.sample.listeners.change();
            assert(!elements.status.textContent.startsWith('تعذر العرض'));
            assert.equal(elements.before.width,row.focus[2]-row.focus[0]);
            assert.equal(elements.after.height,row.focus[3]-row.focus[1]);
            assert.equal(elements.final.width,row.width);
            assert.equal(elements.downloadFinal.download,row.id+'-final-black.png');
            assert.equal(elements.downloadFinal.href,data.images[row.images.finalBlack]);
            assert.equal(elements.downloadPng.href,data.images[row.images.afterTransparent]);
            const originals=calls.filter(c=>c[0]==='drawImage'&&c.length===10).slice(-2);
            assert.equal(originals.length,2);
            for(const draw of originals)assert.equal(draw[1].src,data.images[row.images.source]);
        }
        elements.focus.checked=false;await elements.focus.listeners.change();
        assert.equal(elements.before.width,row.width);
        elements.focus.checked=true;
    }
    elements.showLines.checked=false;elements.showChanges.checked=false;
    elements.background.value='white';calls.length=0;await elements.showLines.listeners.change();
    assert.equal(calls.filter(c=>c[0]==='drawImage').length,3);
    elements.zoom.value='800';await elements.zoom.listeners.input();
    assert.equal(elements.after.style.width,'800%');
    elements.sample.value=data.samples[0].id;await elements.sample.listeners.change();
    assert(elements.previous.disabled);
    elements.next.listeners.click();await flush();
    assert.equal(elements.sample.value,data.samples[1].id);
    elements.beforeFullscreen.listeners.click();await flush();assert.equal(fullscreenCalls,1);
    elements.downloadReport.listeners.click();assert.equal(reportClicks,1);elements.downloadFinal.listeners.click({preventDefault(){}});assert.equal(reportClicks,2);elements.includeGlow.checked=false;await elements.includeGlow.listeners.change();
    for(const role of ['before','after','final'])assert.equal(elements['approve-'+role].checked,false);
    const chosen=elements.sample.value;elements['approve-final'].checked=true;elements['approve-final'].listeners.change();
    assert(sandbox.localStorage.saved.includes('"automaticAction":false'));
    elements.sample.value=data.samples[0].id;await elements.sample.listeners.change();assert.equal(elements['approve-final'].checked,false);
    elements.sample.value=chosen;await elements.sample.listeners.change();assert.equal(elements['approve-final'].checked,true);
    elements.includeGlow.checked=!elements.includeGlow.checked;await elements.includeGlow.listeners.change();assert.equal(elements['approve-final'].checked,false);
    elements.includeGlow.checked=!elements.includeGlow.checked;await elements.includeGlow.listeners.change();assert.equal(elements['approve-final'].checked,true);
    elements['approve-final'].checked=false;elements['approve-final'].listeners.change();assert.equal(elements['approve-final'].checked,false);
    elements.downloadSelections.listeners.click();assert.equal(reportClicks,3);
    console.log(`PASS: ${data.samples.length} samples; two true-colour originals and final black output; focus, zoom, navigation, downloads and fullscreen invocation. Mock DOM/canvas only.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
