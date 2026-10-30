import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {composePrompt,buildComparisonRequests} from './flux-prompts.js';
const catalog=JSON.parse(readFileSync(new URL('./flux-catalog.json',import.meta.url),'utf8'));
const settings=(extra={})=>({style:'ink',prompt:'',mode:'edit',references:[],controls:Object.fromEntries(Object.keys(catalog.controls).map(k=>[k,'auto'])),preserve:{identity:true,pose:true,clothes:true},...extra});

test('browser preview matches the actual backend instruction for presets, controls, roles and modes',()=>{
 const cases=catalog.presets.map(p=>settings({style:p.id,mode:p.mode,prompt:p.prompt}));
 for(const [key,group]of Object.entries(catalog.controls))for(const value of Object.keys(group.options))cases.push(settings({controls:{...settings().controls,[key]:value}}));
 cases.push(settings({mode:'multi',references:[{role:'style'},{role:'object'}]}));
 cases.push(settings({mode:'generate',prompt:'An elegant black outline drawing of a sailing boat.'}));
 cases.push(settings({preserve:{identity:false,pose:false,clothes:false},prompt:'Change only the lighting.'}));
 const result=spawnSync('python',['-c','import json,sys; from generation import prompts; print(json.dumps([prompts(s) for s in json.load(sys.stdin)]))'],{cwd:new URL('.',import.meta.url),input:JSON.stringify(cases),encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);
 assert.deepEqual(cases.map(s=>composePrompt(catalog,s)),JSON.parse(result.stdout));
});

test('editable prompt replaces preset text and text-only mode omits reference constraints',()=>{
 const prompt=composePrompt(catalog,settings({prompt:'Change only the lighting.'}));
 assert.ok(prompt.startsWith('Change only the lighting.'));
 assert.ok(!prompt.includes('Redraw the main reference as'));
 const generated=composePrompt(catalog,settings({mode:'generate',prompt:'Draw a boat.'}));
 assert.equal(generated,'Draw a boat.');
});

test('object preset follows each reference role without assuming reference image 2 is the object',()=>{
 const combined=composePrompt(catalog,settings({style:'reference-object',mode:'multi',references:[{role:'style'},{role:'object'}]}));
 assert.ok(combined.includes('Integrate each reference assigned the object/product role'));
 assert.ok(combined.includes('Reference image 2: Use this reference only to change rendering'));
 assert.ok(combined.includes('Reference image 3: Use this reference for the appearance and geometry of the object'));
 assert.ok(!combined.includes('reference image 2 as the reference object'));

 const reordered=composePrompt(catalog,settings({style:'reference-object',mode:'multi',references:[{role:'object'},{role:'style'}]}));
 assert.ok(reordered.includes('Reference image 2: Use this reference for the appearance and geometry of the object'));
 assert.ok(reordered.includes('Reference image 3: Use this reference only to change rendering'));
});

test('style preset uses style references for rendering only and keeps source content',()=>{
 const prompt=composePrompt(catalog,settings({style:'reference-style',mode:'multi',references:[{role:'style'},{role:'composition'}]}));
 assert.ok(prompt.includes('exclusive source of all image content'));
 assert.ok(prompt.includes('If image 1 contains no person or face, the result must contain no person, face, body or clothing'));
 assert.ok(prompt.includes('Preserve facial identity only when a face is present there'));
 assert.ok(prompt.includes('Reference image 2: Use this reference only to change rendering'));
 assert.ok(prompt.includes('Reference image 3: Use this reference as guidance for scene layout'));
 assert.ok(!prompt.includes('reference image 2 only as an artistic style guide'));
});

test('catalog separates path-review prompts from art, editing, reference and text tasks',()=>{
 assert.equal(catalog.presets.length,24);
 assert.equal(new Set(catalog.presets.map(p=>p.id)).size,24);
 const category=id=>catalog.presets.find(p=>p.id===id)?.category;
 assert.equal(category('ink'),'رسم خطي للمراجعة قبل المسارات');
 assert.equal(category('caricature'),'الرسم الفني');
 assert.equal(category('relight'),'تعديل الصور');
 assert.equal(category('reference-style'),'مراجع متعددة');
 assert.equal(category('generate-lines'),'التوليد من النص');
});

test('A/B/C comparison keeps source and generation controls identical while varying one prompt',()=>{
 const base=settings({style:'ink',prompt:'Base prompt',mode:'edit',seed:17,resolution:768,aspect:'source',controls:{...settings().controls,shading:'none'},preserve:{identity:true,pose:true,clothes:true}});
 const variants=buildComparisonRequests(base,'data:image/png;base64,source',[
  {letter:'B',style:'minimal',title:'Minimal',prompt:'Alternative B'},
  {letter:'C',style:'pencil-light',title:'Light pencil',prompt:'Alternative C'}]);
 assert.deepEqual(variants.map(v=>v.letter),['A','B','C']);
 for(const variant of variants){assert.equal(variant.payload.image,'data:image/png;base64,source');assert.equal(variant.payload.seed,17);assert.equal(variant.payload.resolution,768);assert.deepEqual(variant.payload.controls,base.controls);assert.deepEqual(variant.payload.preserve,base.preserve);assert.equal(variant.payload.mode,'edit');}
 assert.deepEqual(variants.map(v=>v.payload.prompt),['Base prompt','Alternative B','Alternative C']);
 assert.notEqual(variants[0].payload.controls,base.controls);
 assert.throws(()=>buildComparisonRequests({...base,mode:'generate'},'source',[{style:'minimal',prompt:'B'}]),/edit mode/);
 assert.throws(()=>buildComparisonRequests(base,'source',[{style:'ink',prompt:'Duplicate'}]),/distinct templates/);
});

test('comparison defaults to two independent requests and offers a third as optional',()=>{
 const controls=readFileSync(new URL('./flux-controls.js',import.meta.url),'utf8');
 const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
 assert.match(controls,/defaultAlternative=catalog\.presets\.find\(item=>item\.id==='minimal'/);
 assert.match(html,/ينشئ نسختين افتراضيًا/);
 assert.match(html,/يمكنك إضافة نسخة C/);
});

test('final prompt saving is local and similarity notice states its weights and validation gate',()=>{
 const controls=readFileSync(new URL('./flux-controls.js',import.meta.url),'utf8');
 const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
 assert.match(controls,/prompt=\$\('effectivePrompt'\)\.value\.trim\(\)/);
 assert.match(controls,/finalPrompt:true/);
 assert.match(html,/الوجه 50%، المحيط والوضعية 30%، التكوين والقصّ 20%/);
 assert.match(html,/لن تظهر نسبة فعلية حتى تُنفّذ طريقة القياس وتُعاير وتُختبر/);
});
