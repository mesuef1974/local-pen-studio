const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('const methodPresets = {'),end=source.indexOf('const presetKeptFields=',start);
assert.ok(start>=0&&end>start);
const catalog=vm.runInNewContext(source.slice(start,end)+';methodPresets');
let count=0;
for(const [method,recipes] of Object.entries(catalog)){
 assert.ok(recipes.length>=8,method+' needs at least eight preferences');
 assert.equal(new Set(recipes.map(r=>r[0])).size,recipes.length,'duplicate recipe key');
 for(const [key,label,description,settings] of recipes){
  assert.ok(key&&label&&description);assert.equal(settings.method,undefined,'presets must never change detector');
  for(const kept of ['resolution','ink','background','overlayOpacity'])assert.equal(settings[kept],undefined,'preserve output preference: '+kept);
  count++;
 }
}
assert.equal(count,52);
if(process.argv.includes('--json'))process.stdout.write(JSON.stringify(catalog));
else console.log('PASS: 52 method-specific presets, unique keys, detector and output preferences preserved');
