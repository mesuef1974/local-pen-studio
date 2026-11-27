import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stageText,stageStateText,nextLabel,editLabel,saveLabel,COMPLEXITY_ERRORS,isComplexityError,remainingChecksText} from './ui-text.js';
import {defaults,renderToolPanels} from './tool-settings.js';
import {Workflow} from './workflow.js';

const read=name=>readFileSync(new URL('./'+name,import.meta.url),'utf8');
const scripts=['paths-stage.js','generation-stage.js','export-actions.js','output-stage.js','lens.js','app.js','flux-controls.js','fidelity-panel.js','paper-preview.js','theme.js'];
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
 for(let s=0;s<4;s++){assert.deepEqual(Object.keys(stageText(s)),keys);assert.ok(Object.values(stageText(s)).every(Boolean));}
 assert.deepEqual([0,1].map(nextLabel),['راجِع الصورة','اعتمد الصورة']);
 assert.deepEqual([nextLabel(2),nextLabel(3),nextLabel(3,'laser')],['إلى الإخراج','صدّر SVG للقلم','صدّر SVG لليزر']);assert.equal(saveLabel,'حفظ نتيجة المرحلة');assert.equal(editLabel(1),'العودة إلى محرر الصورة');
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

test('the review checklist starts empty and any change to the image clears it',()=>{
 const flow=new Workflow(),image={image:'x',width:2,height:2};flow.reviewImage(image);
 assert.deepEqual(flow.checks,[false,false,false,false]);
 flow.checks.fill(true);flow.invalidate(2);assert.ok(flow.checks.every(Boolean));
 for(const change of [()=>flow.invalidate(0),()=>flow.invalidate(1),()=>flow.reviewImage(image),()=>flow.import('y','y')]){flow.checks=flow.checks.map(()=>true);change();assert.ok(flow.checks.every(done=>!done));}
 assert.deepEqual([4,2,1,0].map(remainingChecksText),['بقي 4 بنود قبل الاعتماد','بقي بندان قبل الاعتماد','بقي بند واحد قبل الاعتماد','اكتملت قائمة الفحص']);
 assert.match(read('app.js'),/flow\.checks\.includes\(false\)\|\|!flow\.approve\(1\)/);
});

test('every path export lives in the output stage and nowhere else',()=>{
 const html=read('index.html'),cards=html.slice(html.indexOf(' id="outputStage"'),html.indexOf(' id="generationReview"'));
 for(const id of ['downloadPen','downloadJson','downloadLaser','laserTemplateOpen'])assert.ok(cards.includes(` id="${id}"`),id);
 assert.match(read('app.js'),/\$\('downloadStage'\)\.hidden=s===2;/);
 assert.deepEqual([stageStateText({canEnter:false},3),stageStateText({canEnter:true},3)],['بانتظار المسارات','جاهز للتصدير']);
});

test('a failed import leaves the current work untouched',()=>{
 const body=read('app.js').match(/^async function load\(.*$/m)[0];
 const before=body.slice(0,body.indexOf("api('/api/import'"));
 for(const destructive of ['invalidate(','generation.candidate=null','flow.stage=0'])assert.ok(!before.includes(destructive),destructive);
});
