import {requestJson} from './api-client.js';
import {describe,fileName} from './cut-view.js';

const $=id=>document.getElementById(id),form=$('cutForm'),message=$('message');
let links=[];

function say(text,failed=false){message.textContent=text;message.classList.toggle('failed',failed);}

function offer(anchor,svg,name){
 const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));links.push(url);anchor.href=url;anchor.download=name;
}

function show(piece,name){
 links.forEach(url=>URL.revokeObjectURL(url));links=[];
 const {facts,warnings}=describe(piece);
 $('preview').src=piece.preview;$('facts').textContent=facts;
 $('warnings').replaceChildren(...warnings.map(text=>Object.assign(document.createElement('li'),{textContent:text})));
 offer($('mirrored'),piece.mirroredSvg,fileName(name,true));offer($('plain'),piece.svg,fileName(name,false));
 $('result').hidden=false;
}

// A changed field makes the shown files stale, so they are hidden until rebuilt.
form.addEventListener('input',()=>{$('result').hidden=true;say('');});

form.addEventListener('submit',async event=>{
 event.preventDefault();
 const data=new FormData(form),name=String(data.get('name'));
 const body={name,font:data.get('font'),sizeMm:Number(data.get('sizeMm')),directTop:data.has('directTop')};
 const fields=[...form.elements];
 fields.forEach(field=>{field.disabled=true;});$('result').hidden=true;say('جارٍ إنشاء القطعة…');
 try{show(await requestJson('/api/cut-piece',body),name);say('جاهزة.');}
 catch(error){say(error.message,true);}
 finally{fields.forEach(field=>{field.disabled=false;});}
});
