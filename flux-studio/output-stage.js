// The output stage shows the pen and the laser side by side. It only displays; the files are built where they were.
import {laserSvg} from './laser-export.js';
const $=id=>document.getElementById(id);
const dataUrl=svg=>'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
let laserKey=null;
export function renderOutputStage({visible,tool,ready,plan,mapping,template,key,paper,pen,canvas}){
 $('outputStage').hidden=$('outputTools').hidden=$('playback').hidden=!visible;
 // One canvas draws the paths: it moves into the pen card for the simulation and back for editing.
 if(visible&&canvas.parentElement!==$('penSheet')){$('penSheet').append(canvas);canvas.style.width='';}
 else if(!visible&&canvas.parentElement===$('penSheet'))$('waiting').before(canvas);
 for(const [name,card,button]of [['pen','penCard','toolPen'],['laser','laserCard','toolLaser']]){$(card).dataset.selected=String(tool===name);$(button).setAttribute('aria-pressed',String(tool===name));}
 $('playback').dataset.tool=tool;
 if(!visible)return;
 $('penCaption').textContent=ready?`${paper} · قلم ${pen} مم`:'حدّث المسارات لمعاينة القلم.';
 const next=ready?JSON.stringify([key,template]):null;if(next===laserKey)return;laserKey=next;
 const image=$('laserPreview');image.hidden=true;$('laserCaption').textContent=ready?'':'حدّث المسارات لمعاينة الليزر.';if(!ready)return;
 try{const {svg,stats}=laserSvg(plan.items,mapping,{template});
  // The file's hairlines vanish at card size, so only the picture is drawn thicker.
  image.src=dataUrl(svg.replaceAll('stroke-width="0.1"',`stroke-width="${Math.max(mapping.paperWidth,mapping.paperHeight)/500}"`));image.hidden=!stats.paths;
  $('laserCaption').textContent=stats.paths?`${stats.paths.toLocaleString('en-US')} خطًّا · ${Math.round(stats.lengthMm).toLocaleString('en-US')} مم · ${template?'مع قالب القص':'دون حدّ قص'}`:'لا خطوط تصلح للحفر.';
 }catch(error){$('laserCaption').textContent=error.message;}
}
