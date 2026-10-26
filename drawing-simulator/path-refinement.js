/* Conservative geometric refinement. Does not infer facial identity. */
function refinePenPaths(input,options){
 const flags=input.map((_,i)=>Boolean(options.protectedFlags?.[i]));
 const paths=input.map(p=>p.map(q=>q.slice())),gap=options.joinGapPixels||0;
 const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
 const direction=(a,b)=>{const d=distance(a,b);return d?[(b[0]-a[0])/d,(b[1]-a[1])/d]:[0,0];};
 const dot=(a,b)=>a[0]*b[0]+a[1]*b[1];
 const closed=p=>p.length>2&&distance(p[0],p[p.length-1])<.01;
 const cosine=Math.cos(25*Math.PI/180),gapCosine=Math.cos(35*Math.PI/180);
 let joins=0;
 for(let i=0;gap>0&&i<paths.length;i++){
  let a=paths[i];if(closed(a))continue;
  while(true){let best=-1,reverse=false,reverseA=false,bestGap=gap+1;
   for(const flipA of [false,true]){
   const tail=flipA?a[0]:a[a.length-1],u=flipA?direction(a[Math.min(2,a.length-1)],tail):direction(a[Math.max(0,a.length-3)],tail);
   for(let j=i+1;j<paths.length;j++){
    const b=paths[j];if(closed(b))continue;
    for(const flip of [false,true]){
     const head=flip?b[b.length-1]:b[0],second=flip?b[Math.max(0,b.length-3)]:b[Math.min(2,b.length-1)];
     const d=distance(tail,head);if(d>gap||d>=bestGap)continue;
     const v=direction(head,second);if(dot(u,v)<cosine)continue;
     if(d>.25){const bridge=direction(tail,head);if(dot(u,bridge)<gapCosine||dot(bridge,v)<gapCosine)continue;}
     let supported=true;
     for(let k=1;k<5;k++)if(options.evidence(tail[0]+(head[0]-tail[0])*k/5,tail[1]+(head[1]-tail[1])*k/5)<4){supported=false;break;}
     if(!supported)continue;best=j;reverse=flip;reverseA=flipA;bestGap=d;
    }
   }
   }
   if(best<0)break;
   if(reverseA)a.reverse();
   flags[i]=flags[i]||flags[best];flags.splice(best,1);
   let b=paths.splice(best,1)[0];if(reverse)b=b.slice().reverse();
   if(bestGap<.01)b=b.slice(1);a.push(...b);joins++;
  }
 }
 const maximum=options.smoothPixels||0;
 let moved=0;
 const result=paths.map(path=>path.map((p,i)=>{
  if(!maximum||i===0||i===path.length-1)return p;
  const previous=path[i-1],next=path[i+1];
  // Preserve sharp corners; bound every moved point in source-pixel units.
  if(dot(direction(previous,p),direction(p,next))<Math.cos(45*Math.PI/180))return p;
  const target=[(previous[0]+2*p[0]+next[0])/4,(previous[1]+2*p[1]+next[1])/4];
  const d=distance(p,target);if(d<1e-8)return p;
  const t=Math.min(1,maximum/d);moved++;
  return[p[0]+(target[0]-p[0])*t,p[1]+(target[1]-p[1])*t];
 }));
 return {paths:result,joins,moved,protectedFlags:flags};
}
