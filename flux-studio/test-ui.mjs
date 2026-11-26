import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stageText,stageStateText,nextLabel,editLabel,saveLabel,COMPLEXITY_ERRORS,isComplexityError} from './ui-text.js';
import {defaults,renderToolPanels} from './tool-settings.js';

const read=name=>readFileSync(new URL('./'+name,import.meta.url),'utf8');
const scripts=['app.js','flux-controls.js','fidelity-panel.js','paper-preview.js','theme.js'];
// All markup that exists on the page: the static document and the tool panels.
function markup(){const panels={tools0:{innerHTML:''},tools1:{innerHTML:''},tools2:{innerHTML:''}},previous=globalThis.document;
 globalThis.document={getElementById:id=>panels[id]};try{renderToolPanels();}finally{globalThis.document=previous;}
 return read('index.html')+Object.values(panels).map(p=>p.innerHTML).join('');}

test('every element a script asks for by a fixed id exists exactly once, wherever it sits',()=>{
 const html=markup();
 for(const name of scripts){const source=read(name);
  for(const [,id]of source.matchAll(/(?:\$|getElementById)\('([A-Za-z][\w-]*)'\)/g))assert.equal(html.split(` id="${id}"`).length-1,1,`${name}: ${id}`);}
});

test('scripts reach elements by id, not by their place among other elements',()=>{
 for(const name of scripts)assert.doesNotMatch(read(name),/closest\(|querySelector\('details'\)|firstElementChild|nextElementSibling|previousElementSibling|\.children\[/,name);
});

test('each stage has complete wording',()=>{
 const keys=Object.keys(stageText(0));assert.equal(defaults.length,3);
 for(let s=0;s<3;s++){assert.deepEqual(Object.keys(stageText(s)),keys);assert.ok(Object.values(stageText(s)).every(Boolean));}
 assert.deepEqual([0,1].map(nextLabel),['مراجعة الصورة قبل الاعتماد','اعتماد الصورة وتحديد مسار القلم']);
 assert.equal(saveLabel(2),'حفظ مسارات SVG');assert.equal(saveLabel(0),saveLabel(1));assert.equal(editLabel(1),'العودة إلى محرر الصورة');
});

test('stage state text follows freshness, approval and availability',()=>{
 const base={fresh:[false,false,false],approved:[false,false],outputs:[null,null,null],source:'',canEnter:false};
 assert.deepEqual([0,1,2].map(i=>stageStateText(base,i)),['بانتظار صورة','بانتظار نسخة للمراجعة','بانتظار اعتماد الصورة']);
 assert.equal(stageStateText({...base,source:'x'},0),'جاهز للتجهيز');
 assert.equal(stageStateText({...base,canEnter:true},2),'جاهز للتشغيل');
 assert.equal(stageStateText({...base,outputs:[{},null,null]},0),'تحديث مطلوب');
 const ready={...base,fresh:[true,true,true]};
 assert.deepEqual([0,1,2].map(i=>stageStateText(ready,i)),['نسخة جاهزة','بانتظار اعتمادك','مسارات جاهزة']);
 assert.equal(stageStateText({...ready,approved:[true,true]},1),'معتمدة للقلم');
});

test('complexity fallback recognises the wording the server actually raises',()=>{
 const server=read('faithful_paths.py');
 for(const text of COMPLEXITY_ERRORS){assert.ok(server.includes(text),text);assert.ok(isComplexityError(text+'؛ تفاصيل'));}
 assert.equal(isComplexityError('تعذر فتح الملف.'),false);
});
