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
