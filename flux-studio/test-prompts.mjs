import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {composePrompt} from './flux-prompts.js';
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
