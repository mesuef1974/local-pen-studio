// A template's [bracketed part] is for the user to replace; it must never reach the model as written.
export function unfilledPlaceholder(catalog, style, prompt) {
 const text=prompt?.trim()||catalog.presets.find(item=>item.id===style)?.prompt||'';
 return catalog.presets.flatMap(item=>item.prompt.match(/\[[^\]]+\]/g)||[]).find(mark=>text.includes(mark))||'';
}

// Keep instruction composition identical to generation.prompts; covered by parity tests.
export function composePrompt(catalog, settings) {
 const preset=catalog.presets.find(item=>item.id===settings.style);
 const parts=[settings.prompt?.trim()||preset?.prompt||''];
 if(settings.mode!=='generate'){
  for(const [key,rule] of Object.entries(catalog.preserve))if(settings.preserve[key])parts.push(rule[1]);
  (settings.references||[]).forEach((reference,index)=>parts.push(`Reference image ${index+2}: `+catalog.roles[reference.role][1]));
 }
 for(const [key,group]of Object.entries(catalog.controls))parts.push(group.options[settings.controls[key]][1]);
 return parts.filter(Boolean).join(' ');
}

export function buildComparisonRequests(settings, sourceImage, alternatives) {
 if(settings.mode!=='edit'||!sourceImage)throw new Error('Prompt comparison requires one source image in edit mode.');
 if(!Array.isArray(alternatives)||alternatives.length<1||alternatives.length>2)throw new Error('Choose one or two alternative prompts.');
 const variants=[{letter:'A',style:settings.style,title:'الإعداد الحالي',prompt:settings.prompt},...alternatives];
 if(variants.some(item=>typeof item.prompt!=='string'||!item.prompt.trim()||typeof item.style!=='string'))throw new Error('Every comparison needs a style and a non-empty prompt.');
 if(new Set(variants.map(item=>item.style)).size!==variants.length)throw new Error('Comparison prompts must use distinct templates.');
 return variants.map(variant=>({
  letter:variant.letter,
  title:variant.title,
  style:variant.style,
  prompt:variant.prompt.trim(),
  payload:{...settings,image:sourceImage,style:variant.style,prompt:variant.prompt.trim(),
   controls:{...settings.controls},preserve:{...settings.preserve},references:(settings.references||[]).map(reference=>({...reference}))}
 }));
}
