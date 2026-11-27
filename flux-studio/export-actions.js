// The download buttons. app.js owns the state; state() returns the plan, its paper mapping and the laser template.
import * as geo from './geometry.js';
import {planDocument} from './plan-export.js';
import {LASER_DEFAULTS} from './laser-export.js';

// Building a laser file for a large plan takes long enough to freeze the page, so it runs in a worker.
function laserInWorker(items,mapping,options){return new Promise((resolve,reject)=>{const worker=new Worker(new URL('./laser-worker.js',import.meta.url),{type:'module'}),fail=message=>{worker.terminate();reject(Error(message));};worker.onmessage=({data})=>{if(data.error)return fail(data.error);worker.terminate();resolve(data);};worker.onerror=()=>fail('تعذر إنشاء ملف الليزر.');worker.postMessage({items,mapping,options});});}

export function createExportActions({$,flow,state,download,read,settingsValid,outputReady,stageResult,currentAudit}){
let laserBusy=false;
function blobDownload(text,type,name){const url=URL.createObjectURL(new Blob([text],{type}));download(url,name);setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('downloadStage').onclick=()=>{if(flow.stage<2&&flow.fresh[flow.stage])download(stageResult(),['edited-image.png','approved-image.png'][flow.stage]);};
$('downloadPen').onclick=()=>{const {plan,mapping}=state();if(outputReady())blobDownload(geo.svg(plan.items,mapping,read(2).pen),'image/svg+xml','pen-paths.svg');};
$('downloadLaser').onclick=async()=>{const {plan,mapping,template:laserTemplate}=state();if(laserBusy||!flow.fresh[2]||!plan?.items.length||!settingsValid(2))return;const count=n=>n.toLocaleString('en-US'),note=$('laserExportNote');note.hidden=false;note.textContent='جارٍ إعداد ملف الليزر…';laserBusy=true;let svg,stats;try{({svg,stats}=await laserInWorker(plan.items,mapping,{template:laserTemplate}));}catch(e){note.textContent=e.message;return;}finally{laserBusy=false;}if(state().plan!==plan){note.textContent='تغيّرت المسارات أثناء الإعداد؛ أعد التصدير.';return;}if(!stats.paths){note.textContent='لا خطوط تصلح للحفر: كل الضربات أقصر من 0.5 مم.';return;}blobDownload(svg,'image/svg+xml','laser-score.svg');
 const layers=!laserTemplate?'لا يتضمن حدّ القص.':[laserTemplate.cut.length?'حدّ القص من القالب طبقة حمراء (cut)':'',laserTemplate.guide.length?'مرجع القالب طبقة زرقاء (guide) تُطفأ في برنامج الآلة':''].filter(Boolean).join('، و')+'.'+(laserTemplate.cut.length?'':' القالب بلا حدّ قص.')+(Math.round(stats.clippedLengthMm)>0?` قُصّ الرسم على حدّ القص مع إبعاده ${LASER_DEFAULTS.cutClearance} مم عنه: حُذف ${count(Math.round(stats.clippedLengthMm))} مم تقع خارجه أو في ثقب أو عند الحافة.`:'')+(laserTemplate.engrave.length?' حفر القالب (engrave) لا يُكتب في الملف، والرسم يمتدّ في موضعه.':'');
 note.textContent=`ملف الليزر: ${count(stats.paths)} خطًّا بطول ${count(Math.round(stats.lengthMm))} مم و${count(stats.nodes)} نقطة (كانت ${count(stats.nodesBefore)}). حُذف ${count(stats.dropped)} ضربة أقصر من 0.5 مم${Math.round(stats.retracedLengthMm)>0?`، و${count(Math.round(stats.retracedLengthMm))} مم من مقاطع مكرَّرة كانت ستُحرق مرتين`:''}. الحفر طبقة واحدة بخط أسود 0.1 مم لوضع «الخط» في برنامج الآلة؛ ${layers}`;};
$('downloadJson').onclick=()=>{const {plan,mapping}=state();if(!flow.fresh[2]||!plan?.items.length||!settingsValid(2))return;blobDownload(JSON.stringify(planDocument({plan,mapping,settings:read(2),output:flow.outputs[2],audit:currentAudit()}),null,2),'application/json','pen-paths.json');};
}
