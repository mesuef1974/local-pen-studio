// A browser snapshot holds images as data URLs; a project state refers to uploaded files instead (asset:<sha256>).
// Images also hide inside strings (a candidate's requestKey is JSON), so every string is searched.
const INLINE=/data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}/g,REFERENCE=/asset:[0-9a-f]{64}/g;

async function mapStrings(value,replace){
 if(typeof value==='string')return replace(value);
 if(Array.isArray(value)){const list=[];for(const item of value)list.push(await mapStrings(item,replace));return list;}
 if(!value||typeof value!=='object')return value;
 const copy={};for(const [key,item]of Object.entries(value))copy[key]=await mapStrings(item,replace);return copy;
}
async function replaceAll(text,pattern,convert){
 const found=text.match(pattern);if(!found)return text;
 const made=new Map();for(const match of found)if(!made.has(match))made.set(match,await convert(match));
 return text.replace(pattern,match=>made.get(match));
}
function decode(url){
 const binary=atob(url.slice(url.indexOf(',')+1));
 return {type:url.slice(5,url.indexOf(';')),bytes:Uint8Array.from(binary,char=>char.charCodeAt(0))};
}
function encode({bytes,type}){
 const data=new Uint8Array(bytes);let binary='';
 for(let at=0;at<data.length;at+=0x8000)binary+=String.fromCharCode(...data.subarray(at,at+0x8000));
 return `data:${type};base64,${btoa(binary)}`;
}

// upload(bytes,type) resolves to the sha256; `uploaded` remembers it so a second save sends only new images.
export async function toState(snapshot,upload,uploaded=new Map()){
 const send=async url=>{if(!uploaded.has(url)){const {bytes,type}=decode(url);uploaded.set(url,await upload(bytes,type));}return `asset:${uploaded.get(url)}`;};
 // A running job belongs to this machine's memory, not to the project.
 const state=await mapStrings(JSON.parse(JSON.stringify({...snapshot,pendingGeneration:null})),text=>replaceAll(text,INLINE,send));
 if(JSON.stringify(state).includes('data:image/'))throw Error('في العمل صورة بصيغة لا تُحفظ في المشروع؛ المقبول PNG أو JPEG أو WebP.');
 return state;
}

// download(sha256) resolves to {bytes,type}. A project that was never saved gives null.
export async function fromState(state,download,uploaded=new Map()){
 if(state?.version!==1)return null;
 const made=new Map();
 const load=async reference=>{if(!made.has(reference)){const sha=reference.slice(6),url=encode(await download(sha));made.set(reference,url);uploaded.set(url,sha);}return made.get(reference);};
 return mapStrings(state,text=>replaceAll(text,REFERENCE,load));
}
