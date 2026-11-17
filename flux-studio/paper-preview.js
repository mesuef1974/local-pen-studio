// Shows the pen plan on its sheet of paper in the paths stage. $ looks an element up by id.
// state is an object the caller owns; it remembers which plan the sheet image shows, so an unchanged plan is not rebuilt.
// overlay is an SVG fragment in sheet millimetres drawn over the plan (a laser template's cut outline), or ''.
// clip is even-odd path data in sheet millimetres; the plan is shown only inside it (what the laser file keeps), or ''.
// clearance is how far, in millimetres, the laser file keeps the plan from that outline; the same band is blanked here.
// layout, settings and planKey are functions, called only when their result is needed: layout() may throw on invalid
// paper settings, and planKey() identifies the plan and is costly for a large one.
import * as geo from './geometry.js';
import {inkBounds} from './paper.js';
export const mm=value=>Number(value).toLocaleString('en-US',{maximumFractionDigits:1});
export function paperPair(width,height){return `⁦${mm(width)} × ${mm(height)}⁩`;}
export function renderPaperPreview($,state,{stage,view,ready,busy,layout,settings,mapping,plan,planKey,overlay='',clip='',clearance=0}){
 const visible=stage===2&&view==='paper';$('paperViewButton').hidden=stage!==2;$('paperPreview').hidden=!visible;if(!visible)return;
 $('paperSheet').hidden=!ready;$('paperWaiting').hidden=!!ready;$('paperProgress').hidden=!busy;$('paperWaitLabel').textContent=busy?'يجري حساب المسارات للمقاس المختار.':'حدّث المسارات بعد مراجعة إعدادات الورقة.';if(!ready){$('paperPlacement').textContent='';try{const m=layout();$('paperDimensions').textContent=`${paperPair(m.paperWidth,m.paperHeight)} مم`;}catch{$('paperDimensions').textContent='راجع أبعاد الورقة';}return;}
 const s=settings(),m=mapping,key=JSON.stringify([planKey(),m.paperWidth,m.paperHeight,m.x,m.y,$('paperGuides').checked,overlay,clip,clearance]);
 $('paperDimensions').textContent=`${s.paper==='custom'?'مقاس مخصص':s.paper==='Square'?'مربع':s.paper} · ${paperPair(m.paperWidth,m.paperHeight)} مم`;
 const bounds=inkBounds(plan.items,m,s.pen);$('paperPlacement').textContent=bounds?`امتداد الحبر: ${paperPair(bounds.width,bounds.height)} مم · هامش ${mm(s.margin)} مم · قلم ${mm(s.pen)} مم`:'لا توجد خطوط مختارة على الورقة.';
 requestAnimationFrame(()=>fitPaperPreview($,m));if(key===state.key)return;state.key=key;
 let svg=geo.svg(plan.items,m,s.pen);if(clip)svg=svg.replace('<g fill="none"',`<defs><clipPath id="piece"><path clip-rule="evenodd" d="${clip}"/></clipPath></defs><g clip-path="url(#piece)" fill="none"`);if($('paperGuides').checked)svg=svg.replace('</svg>',`<rect x="${s.margin}" y="${s.margin}" width="${m.paperWidth-2*s.margin}" height="${m.paperHeight-2*s.margin}" fill="none" stroke="#94a3b8" stroke-width="0.18" stroke-dasharray="1.5 1.5"/></svg>`);
 if(clip&&clearance>0)svg=svg.replace('</svg>',`<path d="${clip}" fill="none" stroke="#ffffff" stroke-width="${2*clearance}" stroke-linejoin="round"/></svg>`);
 if(overlay)svg=svg.replace('</svg>',overlay+'</svg>');
 $('paperSheet').style.aspectRatio=`${m.paperWidth} / ${m.paperHeight}`;$('paperImage').src='data:image/svg+xml;base64,'+btoa(svg);
}
// Sizes the sheet to the largest box of the paper's proportions that fits its container.
export function fitPaperPreview($,mapping){const sheet=$('paperSheet');if($('paperPreview').hidden||sheet.hidden||!mapping)return;const box=sheet.parentElement,style=getComputedStyle(box),width=box.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),height=box.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom),ratio=mapping.paperWidth/mapping.paperHeight;if(width<=0||height<=0)return;const w=Math.min(width,height*ratio);sheet.style.width=w+'px';sheet.style.height=w/ratio+'px';}
