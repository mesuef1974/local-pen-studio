// Reads the cut outline and the guides out of a Misk laser template: an SVG in millimetres whose layers are
// <g id="cut"> (red hairline, cut through) and <g id="guide"> (blue, a reference the machine does not output),
// each holding absolute M/L/Z paths. Nothing of the file's markup is kept: the paths are parsed to numbers and
// written again, so a template cannot carry anything else into the laser file or the page.
// It reads nothing but its arguments.
export const TEMPLATE_LIMITS=Object.freeze({bytes:2_000_000,points:200_000,sizeTolerance:.05});
const CUT='fill="none" stroke="#ff0000" stroke-width="0.1"',GUIDE='fill="none" stroke="#0000ff" stroke-width="0.2" stroke-dasharray="1 1"';

const attribute=(tag,name)=>new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1];
function millimetres(value){const match=/^(\d+(?:\.\d+)?)mm$/.exec(value??'');return match?Number(match[1]):NaN;}

// One `d` attribute to [{points,closed}]. Only absolute M, L and Z are read; anything else is refused, not skipped.
function subpaths(d){
 const token=/\s*(?:([MLZ])|(-?\d+(?:\.\d+)?)\s*,?)\s*/y,paths=[];let current=null,pending=null,at=0;
 while(at<d.length){
  token.lastIndex=at;const match=token.exec(d);
  if(!match)throw Error('القالب يحوي مسارًا بصيغة غير مدعومة؛ المقبول M وL وZ بإحداثيات مطلقة.');
  at=token.lastIndex;
  if(match[1]){
   if(pending!==null)throw Error('القالب يحوي إحداثيًّا ناقصًا.');
   if(match[1]==='M'){current={points:[],closed:false};paths.push(current);}
   else if(!current?.points.length)throw Error('القالب يحوي مسارًا لا يبدأ بـM.');
   else if(match[1]==='Z'){current.closed=true;current=null;}
  }else{
   if(!current)throw Error('القالب يحوي مسارًا لا يبدأ بـM.');
   if(pending===null)pending=Number(match[2]);else{current.points.push([pending,Number(match[2])]);pending=null;}
  }
 }
 if(pending!==null)throw Error('القالب يحوي إحداثيًّا ناقصًا.');
 return paths.filter(path=>path.points.length>1);
}

// Returns {width,height,title,cut,guide}; cut and guide are lists of {points,closed} in sheet millimetres.
export function readLaserTemplate(text){
 if(typeof text!=='string'||!text.length)throw Error('ملف القالب فارغ.');
 if(text.length>TEMPLATE_LIMITS.bytes)throw Error('ملف القالب أكبر من 2 ميغابايت.');
 const head=/<svg\b[^>]*>/.exec(text)?.[0];
 if(!head)throw Error('القالب ليس ملف SVG.');
 const width=millimetres(attribute(head,'width')),height=millimetres(attribute(head,'height'));
 if(!(width>0)||!(height>0))throw Error('القالب لا يذكر عرضه وارتفاعه بالمليمتر.');
 const box=(attribute(head,'viewBox')??'').trim().split(/[\s,]+/).map(Number);
 if(box.length!==4||box[0]!==0||box[1]!==0||Math.abs(box[2]-width)>1e-6||Math.abs(box[3]-height)>1e-6)throw Error('وحدة القالب ليست المليمتر: viewBox لا يطابق العرض والارتفاع.');
 let points=0;
 const layer=id=>{
  const group=new RegExp(`<g\\b[^>]*\\sid="${id}"[^>]*>([\\s\\S]*?)</g>`).exec(text)?.[1]??'',paths=[];
  for(const [,d] of group.matchAll(/<path\b[^>]*?\sd="([^"]*)"/g))for(const path of subpaths(d)){
   points+=path.points.length;
   if(points>TEMPLATE_LIMITS.points)throw Error('القالب أعقد من الحدّ المسموح (200 ألف نقطة).');
   for(const [x,y] of path.points)if(x<-TEMPLATE_LIMITS.sizeTolerance||y<-TEMPLATE_LIMITS.sizeTolerance||x>width+TEMPLATE_LIMITS.sizeTolerance||y>height+TEMPLATE_LIMITS.sizeTolerance)throw Error('في القالب مسار يخرج عن حدود صفحته.');
   paths.push(path);
  }
  return paths;
 };
 const cut=layer('cut'),guide=layer('guide');
 if(!cut.length&&!guide.length)throw Error('القالب لا يحوي طبقة قص (cut) ولا طبقة مرجع (guide).');
 const title=(/<title>([^<]*)<\/title>/.exec(text)?.[1]??'').trim().slice(0,120);
 return {width,height,title,cut,guide};
}

export function sameSheet(template,mapping){return Math.abs(template.width-mapping.paperWidth)<=TEMPLATE_LIMITS.sizeTolerance&&Math.abs(template.height-mapping.paperHeight)<=TEMPLATE_LIMITS.sizeTolerance;}

const pathData=paths=>paths.map(({points,closed})=>points.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(3)},${y.toFixed(3)}`).join(' ')+(closed?' Z':'')).join(' ');
// The template's layers as SVG groups, in the colours the machine software tells layers apart by.
export function templateLayers(template){
 return (template.cut.length?`<g id="cut" ${CUT}><path fill-rule="evenodd" d="${pathData(template.cut)}"/></g>`:'')+(template.guide.length?`<g id="guide" ${GUIDE}><path fill-rule="evenodd" d="${pathData(template.guide)}"/></g>`:'');
}

// Even-odd test against every cut ring at once, so a hole in the piece (a keyring hole) counts as outside it.
export function insideCut(template,[x,y]){
 let inside=false;
 for(const {points} of template.cut)for(let i=0,j=points.length-1;i<points.length;j=i++){
  const [ax,ay]=points[i],[bx,by]=points[j];
  if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;
 }
 return inside;
}
