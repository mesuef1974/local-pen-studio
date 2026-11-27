import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read=name=>readFileSync(new URL(name,import.meta.url),'utf8').replace(/\/\*[\s\S]*?\*\//g,'');
const literal=/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|(?<![-\w])(?:white|black)(?![-\w])/g;
const tokens=read('./brand/masar/identity/tokens/tokens.css');
const sheets=['./workspace.css','./flux.css','./screens.css'].map(read);
sheets.push(read('./platform-adoption.html').match(/<style>([\s\S]*?)<\/style>/)[1]);

test('app stylesheets take every colour from the identity tokens',()=>{
 for(const css of sheets){
  // Declarations only: id selectors such as #add are not colours. Custom properties define the sheet and mark.
  const values=[...css.matchAll(/(?<![\w-])([a-z-]+)\s*:\s*([^;{}]*)(?=[;}])/g)].filter(m=>!m[1].startsWith('--'));
  assert.deepEqual(values.flatMap(m=>m[2].match(literal)??[]),[]);
 }
});

test('every referenced identity token exists',()=>{
 for(const css of sheets)for(const [,name] of css.matchAll(/var\((--masar-[\w-]+)/g))assert.ok(tokens.includes(name+':'),name);
});

const palette=block=>Object.fromEntries([...block.matchAll(/(--masar-[\w-]+):(#[0-9A-Fa-f]{6})/g)].map(m=>[m[1].slice(8),m[2]]));
const light=palette(tokens.slice(tokens.indexOf(':root{'),tokens.indexOf('@media')));
const dark={...light,...palette(tokens.slice(tokens.indexOf(':root[data-theme="dark"]')))};
const luminance=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
const contrast=(a,b)=>{const [x,y]=[luminance(a),luminance(b)].sort((p,q)=>q-p);return (x+.05)/(y+.05);};

test('text roles reach AA contrast on every surface in both modes',()=>{
 for(const [mode,c] of [['light',light],['dark',dark]]){
  const pairs=[['on-brand','brand'],['error','error-soft'],['warning','warning-soft'],['info','info-soft'],['brand-text','brand-soft']];
  for(const fg of ['text','text-muted','brand-text','error','warning'])for(const bg of ['bg','surface'])pairs.push([fg,bg]);
  pairs.push(['text','raised'],['text','brand-soft']);
  for(const [fg,bg] of pairs)assert.ok(contrast(c[fg],c[bg])>=4.5,`${mode}: ${fg} on ${bg} = ${contrast(c[fg],c[bg]).toFixed(2)}`);
 }
});

test('app text is at least 13px and touch targets at least 44px',()=>{
 for(const css of [read('./workspace.css'),read('./screens.css')]){
  assert.deepEqual(css.match(/(?<![\w-])font(?:-size)?:\s*(?:\d{3} )?(?:\d|1[0-2])px/g)??[],[]);
  assert.deepEqual(css.match(/min-height:(?:2[4-9]|3\d|4[0-3])px/g)??[],[]);
 }
});
