// The paths stage: the pen plan, stroke exclusions, playback, fidelity audit, paper preview and laser template.
import * as geo from './geometry.js';
import {paperLayout as physicalPaperLayout} from './paper.js';
import {auditWebGPU} from './webgpu-audit.js';
import {drawPlan} from './path-canvas.js';
import {cutPathData,readLaserTemplate,sameSheet,templateLayers} from './laser-template.js';
import {LASER_DEFAULTS} from './laser-export.js';
import {fmt,lighterPlan} from './stage-metrics.js';
import {renderFidelity as showFidelity} from './fidelity-panel.js';
import {renderPaperPreview as showPaperPreview,fitPaperPreview as fitPaperSheet} from './paper-preview.js';

export const LONG_PLAN_WARNING_SECONDS=600;

export function createPathsStage({$,flow,gate,ui,api,read,assign,error,update,settingsValid,onChange,updateView,generationLocked}){
let excluded=new Set(),selected=new Set(),past=[],future=[],plan=null,mapping=null,pathsReference=null,box=null;
let playing=false,elapsed=null,lastFrame=0,frameHandle=0;const playbackTrail={canvas:document.createElement('canvas'),done:0};const planInk={canvas:document.createElement('canvas'),scratch:document.createElement('canvas')};
let fidelityCache=null;
const paperView={key:null};
let laserTemplate=null;// a Misk template's cut outline and guides, or null; it sets the sheet and goes into the laser file
$('selectStroke').onclick=()=>{if(gate.busy||!flow.fresh[2])return;const input=$('strokeIndex'),index=Number(input.value)-1;if(input.value===''||!input.validity.valid||!Number.isInteger(index)||index<0||index>=flow.outputs[2].paths.length){input.setAttribute('aria-invalid','true');$('selectionInfo').textContent='أدخل رقم ضربة صحيحًا ضمن المسارات المستخرجة.';return;}input.setAttribute('aria-invalid','false');selected=new Set([index]);if(ui.view==='paper'){ui.view='result';updateView();}drawPaths();updateSelection();};
function renderPaperPreview(){showPaperPreview($,paperView,{stage:flow.stage,view:ui.view,ready:!!(flow.fresh[2]&&plan&&settingsValid(2)),busy:gate.busy,layout:paperLayout,settings:()=>read(2),mapping,plan,planKey:auditKey,...(laserTemplate&&mapping&&sameSheet(laserTemplate,mapping)?{overlay:templateLayers(laserTemplate),clip:cutPathData(laserTemplate),clearance:LASER_DEFAULTS.cutClearance}:{})});}
function fitPaperPreview(){fitPaperSheet($,mapping);}
function auditKey(){if(!flow.fresh[2]||!plan)return null;const s=read(2);return JSON.stringify([flow.versions[2],s.threshold,s.pen,mapping.scale,plan.items.map(v=>v.i).sort((a,b)=>a-b),$('webgpuAudit').checked]);}
function currentAudit(){const key=auditKey();return key!==null&&fidelityCache?.key===key?fidelityCache.data:null;}
function renderFidelity(){const visible=flow.stage===2;showFidelity($,{visible,data:visible?currentAudit():null,gpu:$('webgpuAudit').checked,locked:gate.busy||generationLocked()||!flow.fresh[2]||!plan,fresh:flow.fresh[2]});}
async function auditPaths(){if(gate.busy||generationLocked()||!flow.fresh[2]||!plan||!settingsValid(2))return;const key=auditKey(),s=read(2),gpu=$('webgpuAudit').checked;gate.busy=true;stopPlayback();update();try{const input={image:flow.outputs[1].image,paths:plan.items.map(v=>v.p),mmPerPixel:mapping.scale,penMm:s.pen,inkThreshold:s.threshold};const data=gpu?await auditWebGPU({...input,canvas:$('fidelityRenderCanvas')}):await api('/api/path-audit',input);if(key===auditKey())fidelityCache={key,data};error();}catch(e){error(e.message);}finally{gate.busy=false;update();gate.drain();}}
// Rebuilding the paths renumbers every line, so manual exclusions cannot survive it.
function discardExclusions(){if(!excluded.size)return true;if(!window.confirm(`هذا التغيير يعيد بناء المسارات ويلغي استبعاد ${excluded.size} من الخطوط. هل تتابع؟`))return false;excluded.clear();past=[];future=[];return true;}
function paperLayout(){return physicalPaperLayout(flow.outputs[1]||{width:1,height:1},read(2));}
function replan(){stopPlayback();if(!flow.fresh[2]||!flow.outputs[2]||!settingsValid(2)){plan=null;return;}const s=read(2);mapping=paperLayout();const items=geo.order(flow.outputs[2].paths,excluded,s.order,s.minimum,mapping.scale);plan=geo.timeline(items,mapping.scale,s.drawSpeed,s.travelSpeed,s.lift);plan.items=items;elapsed=null;$('playhead').value=100;drawPaths();}
function loadPathReference(){const image=new Image();const input=flow.outputs[1]?.image;image.src=input||'';image.onload=()=>{if(flow.outputs[1]?.image===input){pathsReference=image;if(flow.stage===2)drawPaths();}};}
function drawPaths(){const output=flow.outputs[2];if(!output)return;const c=$('pathCanvas');drawPlan(c,{output,settings:read(2),mapping,view:ui.exporting?'result':ui.view,pathsReference,plan,elapsed,selected,excluded,box,trail:playbackTrail,ink:planInk});if(plan)$('playTime').textContent=fmt(elapsed??plan.seconds)+' / '+fmt(plan.seconds);}
function stopPlayback(){playing=false;cancelAnimationFrame(frameHandle);frameHandle=0;lastFrame=0;$('play').textContent='تشغيل المحاكاة';}
function playbackFrame(now){if(!playing||!plan||!flow.fresh[2])return;if(lastFrame)elapsed=Math.min(plan.seconds,elapsed+(now-lastFrame)/1000*Number($('playRate').value));lastFrame=now;$('playhead').value=plan.seconds?100*elapsed/plan.seconds:100;drawPaths();if(elapsed>=plan.seconds){stopPlayback();return;}frameHandle=requestAnimationFrame(playbackFrame);}
$('play').onclick=()=>{if(gate.busy||!plan||!flow.fresh[2]||!settingsValid(2))return;if(playing){stopPlayback();return;}if(elapsed===null||elapsed>=plan.seconds)elapsed=0;playing=true;lastFrame=0;$('play').textContent='إيقاف مؤقت';frameHandle=requestAnimationFrame(playbackFrame);};$('stop').onclick=()=>{stopPlayback();elapsed=null;$('playhead').value=100;drawPaths();};$('playhead').oninput=()=>{if(!plan)return;stopPlayback();elapsed=plan.seconds*Number($('playhead').value)/100;drawPaths();};
function remember(){past.push({excluded:new Set(excluded),selected:new Set(selected)});if(past.length>30)past.shift();future=[];}
function editHidden(){if(!selected.size)return;remember();const restore=[...selected].every(i=>excluded.has(i));for(const i of selected)restore?excluded.delete(i):excluded.add(i);replan();update();}
$('toggleSelected').onclick=editHidden;$('selectAll').onclick=()=>{selected=new Set(plan?.items.map(v=>v.i)||[]);drawPaths();updateSelection();};$('clearSelection').onclick=()=>{selected.clear();drawPaths();updateSelection();};$('restorePaths').onclick=()=>{if(!excluded.size)return;remember();excluded.clear();replan();update();};
function historyStep(redo=false){const from=redo?future:past,to=redo?past:future;if(!from.length)return;to.push({excluded:new Set(excluded),selected:new Set(selected)});const state=from.pop();excluded=state.excluded;selected=state.selected;replan();update();}
$('undo').onclick=()=>historyStep();$('redo').onclick=()=>historyStep(true);
function updateSelection(){for(const id of ['selectAll','clearSelection','toggleSelected','undo','redo','restorePaths','selectStroke','strokeIndex'])$(id).disabled=gate.busy||!flow.fresh[2];$('strokeIndex').max=Math.max(1,flow.outputs[2]?.paths.length||0);$('selectionInfo').textContent=selected.size?`${selected.size} خط محدد · ${(Array.from(selected).reduce((n,i)=>n+geo.length(flow.outputs[2].paths[i]),0)*(mapping?.scale||1)).toFixed(1)} مم`:'انقر خطًا، أو اسحب مستطيلًا. الأداة تختار الضربات كاملة.';$('toggleSelected').disabled=gate.busy||!selected.size||!flow.fresh[2];$('undo').disabled=gate.busy||!flow.fresh[2]||!past.length;$('redo').disabled=gate.busy||!flow.fresh[2]||!future.length;$('restorePaths').disabled=gate.busy||!flow.fresh[2]||!excluded.size;}
const canvas=$('pathCanvas');let startPoint=null,addSelection=false;
function point(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width-.5,(e.clientY-r.top)*canvas.height/r.height-.5];}
canvas.onpointerdown=e=>{if(ui.exporting||gate.busy||!flow.fresh[2]||playing)return;elapsed=null;startPoint=point(e);addSelection=e.shiftKey||e.ctrlKey||e.metaKey;canvas.setPointerCapture(e.pointerId);if(read(2).click==='box')box=[...startPoint,...startPoint];};
canvas.onpointermove=e=>{if(!startPoint||!box)return;const p=point(e);box=[Math.min(startPoint[0],p[0]),Math.min(startPoint[1],p[1]),Math.max(startPoint[0],p[0]),Math.max(startPoint[1],p[1])];drawPaths();};
canvas.onpointerup=e=>{if(!startPoint)return;const p=point(e),s=read(2);if(s.click==='box'&&box&&Math.hypot(p[0]-startPoint[0],p[1]-startPoint[1])>3){if(!addSelection)selected.clear();flow.outputs[2].paths.forEach((path,i)=>{if(!excluded.has(i)&&geo.intersectsBox(path,box))selected.add(i);});}else{const hidden=s.showDeleted?new Set():excluded,index=geo.nearestPath(flow.outputs[2].paths,...p,8*canvas.width/canvas.getBoundingClientRect().width,hidden);if(!addSelection)selected.clear();if(index>=0){if(addSelection&&selected.has(index))selected.delete(index);else selected.add(index);if(s.click==='toggle')editHidden();}}startPoint=null;box=null;drawPaths();updateSelection();};canvas.onpointercancel=()=>{startPoint=null;box=null;drawPaths();};
$('laserTemplateOpen').onclick=()=>{if(!gate.busy&&flow.stage===2)$('laserTemplateFile').click();};
// The template is drawn for one sheet size, so loading it makes that the custom sheet; a wide pen margin would leave a small piece no room.
$('laserTemplateFile').onchange=async()=>{const file=$('laserTemplateFile').files[0];$('laserTemplateFile').value='';if(!file)return;const note=$('laserExportNote');try{if(file.size>2_000_000)throw Error('ملف القالب أكبر من 2 ميغابايت.');const template=readLaserTemplate(await file.text());if(Math.min(template.width,template.height)<20||Math.max(template.width,template.height)>1200)throw Error('مقاس القالب خارج مجال الورق المخصص (20 إلى 1200 مم).');if(!discardExclusions())return;laserTemplate=template;note.hidden=true;assign(2,{paper:'custom',paperWidth:+template.width.toFixed(1),paperHeight:+template.height.toFixed(1),landscape:template.width>template.height,margin:Math.min(read(2).margin,3)});onChange(2,'paper');update();}catch(e){note.hidden=false;note.textContent=e.message;}};
$('laserTemplateClear').onclick=()=>{laserTemplate=null;$('laserExportNote').hidden=true;update();};
// Reading the canvas back forces every stroke of the plan to be drawn at once (about 0.3 s for 12,000 strokes),
// so the stage thumbnail waits until the settings stop changing instead of holding up each update.
let pathThumbTimer=0,pathThumbUrl='';
function refreshPathThumb(){clearTimeout(pathThumbTimer);pathThumbTimer=setTimeout(()=>{if(playing||flow.stage!==2||!flow.fresh[2]||!plan?.items.length)return;$('pathCanvas').toBlob(blob=>{if(!blob)return;if(pathThumbUrl)URL.revokeObjectURL(pathThumbUrl);pathThumbUrl=URL.createObjectURL(blob);$('thumb2').src=pathThumbUrl;$('thumb2').hidden=false;},'image/png');},300);}
let lighter=null,lighterFor=null;
function renderLighten(){if($('longPlanWarning').hidden)return;if(lighterFor!==plan){lighterFor=plan;const s=read(2),scale=mapping.scale;lighter=lighterPlan({items:plan.items,current:s.minimum,limit:LONG_PLAN_WARNING_SECONDS,measure:item=>geo.length(item.p)*scale,timeline:kept=>geo.timeline(kept,scale,s.drawSpeed,s.travelSpeed,s.lift)});}
 $('lightenPaths').hidden=!lighter;$('lightenPaths').disabled=gate.busy;$('lightenInfo').textContent=lighter?`يستبعد ${lighter.dropped} ضربة أقصر من ${lighter.minimum} مم؛ الزمن المتوقع نحو ${fmt(lighter.seconds)}${lighter.reaches?'':'، وما زال فوق 10 دقائق'}.`:'لا تخفيف إضافيًا باستبعاد الخطوط القصيرة.';}
$('lightenPaths').onclick=()=>{if(gate.busy||!lighter)return;assign(2,{minimum:lighter.minimum});onChange(2,'minimum');update();};
$('webgpuAudit').onchange=()=>{fidelityCache=null;update();};
$('auditPaths').onclick=auditPaths;
// Leaving a stage: stop the simulation and show the whole drawing again.
function rewind(){stopPlayback();elapsed=null;$('playhead').value=100;}
function clearEdits(){excluded.clear();selected.clear();past=[];future=[];}
function reset(){plan=null;fidelityCache=null;clearEdits();}
// The server measures a freshly built plan, so that result stands in for a manual audit.
function seedAudit(result){if(result.fidelity&&plan?.items.length===result.paths.length&&auditKey()!==null)fidelityCache={key:auditKey(),data:result.fidelity};}
return {
 get plan(){return plan;},set plan(value){plan=value;},get mapping(){return mapping;},set mapping(value){mapping=value;},
 get excluded(){return excluded;},set excluded(value){excluded=value;},get selected(){return selected;},
 get laserTemplate(){return laserTemplate;},set laserTemplate(value){laserTemplate=value;},
 paperLayout,replan,loadPathReference,drawPaths,stopPlayback,discardExclusions,renderPaperPreview,fitPaperPreview,renderFidelity,renderLighten,refreshPathThumb,updateSelection,auditKey,currentAudit,rewind,clearEdits,reset,seedAudit
};
}
