import {buildControls} from './lineart-controls.js';
import {fitImages,initLayout} from './lineart-layout.js';
export const $=id=>document.getElementById(id);
export function setupTools(onPaint){
 buildControls();
 const result=$('result'),frame=document.createElement('div');frame.className='brush-frame';result.before(frame);frame.append(result);const mask=document.createElement('canvas');mask.id='brushMask';mask.setAttribute('aria-label','قناع حماية أو تخفيف أو محو؛ ارسم على النتيجة');frame.append(mask);const progress=document.createElement('progress');progress.id='modelProgress';progress.className='model-progress';progress.max=3;progress.value=0;progress.hidden=true;progress.setAttribute('aria-label','مراحل معالجة الصورة المكتملة');frame.after(progress);
 const ctx=mask.getContext('2d',{willReadFrequently:true});let painting=false,last=null;const history=[];
 function snapshot(){history.push(ctx.getImageData(0,0,mask.width,mask.height));if(history.length>12)history.shift();$('undoMask').disabled=false;}
 function position(e){const r=mask.getBoundingClientRect();return [(e.clientX-r.left)*mask.width/r.width,(e.clientY-r.top)*mask.height/r.height];}
 function stroke(e){const p=position(e),mode=$('brushMode').value;ctx.globalCompositeOperation=mode==='unmask'?'destination-out':'source-over';ctx.strokeStyle={protect:'#ff0000',lighten:'#00ff00',erase:'#0000ff'}[mode]||'#000';ctx.lineWidth=Number($('brushSize').value);ctx.lineCap=ctx.lineJoin='round';ctx.beginPath();ctx.moveTo(...(last||p));ctx.lineTo(p[0]+.01,p[1]+.01);ctx.stroke();ctx.globalCompositeOperation='source-over';last=p;}
 mask.onpointerdown=e=>{if($('brushMode').value==='none'||result.hidden)return;e.preventDefault();snapshot();painting=true;last=null;mask.setPointerCapture(e.pointerId);stroke(e);};mask.onpointermove=e=>{if(painting)stroke(e);};
 const finish=()=>{if(!painting)return;painting=false;last=null;onPaint();};mask.onpointerup=finish;mask.onpointercancel=finish;
 $('undoMask').onclick=()=>{const image=history.pop();if(image){ctx.putImageData(image,0,0);onPaint();}$('undoMask').disabled=!history.length;};
 function clear(){ctx.clearRect(0,0,mask.width,mask.height);history.length=0;$('undoMask').disabled=true;}
 $('clearMask').onclick=()=>{snapshot();ctx.clearRect(0,0,mask.width,mask.height);onPaint();};$('showMask').onchange=()=>mask.style.opacity=$('showMask').checked?'.28':'0';$('brushMode').onchange=()=>mask.style.cursor=$('brushMode').value==='none'?'default':'crosshair';
 $('zoom').oninput=fitImages;
 $('brushSize').oninput=()=>$('brushSizeValue').textContent=$('brushSize').value;
 initLayout();
 return {mask,clear,resize(w,h){if(mask.width!==w||mask.height!==h){mask.width=w;mask.height=h;clear();}},url:()=>mask.toDataURL('image/png')};
}
