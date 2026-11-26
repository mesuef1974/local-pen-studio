// Review lens: the same spot of both versions is magnified together while the pointer is over either one.
const images=['inputImage','outputImage'].map(id=>document.getElementById(id)),ZOOM=2.5,SIZE=180;
const lenses=images.map(image=>{const lens=document.createElement('div');lens.className='lens';lens.hidden=true;lens.setAttribute('aria-hidden','true');image.parentElement.append(lens);return lens;});
const hide=()=>{for(const lens of lenses)lens.hidden=true;};
for(const source of images){
 source.addEventListener('pointerleave',hide);
 source.addEventListener('pointermove',event=>{
  if(document.body.dataset.stage!=='1'){hide();return;}
  const box=source.getBoundingClientRect(),x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height;
  images.forEach((image,i)=>{const lens=lenses[i];lens.hidden=image.hidden||!image.src;if(lens.hidden)return;
   const w=image.clientWidth,h=image.clientHeight;
   lens.style.left=image.offsetLeft+x*w-SIZE/2+'px';lens.style.top=image.offsetTop+y*h-SIZE/2+'px';
   lens.style.backgroundImage=`url("${image.src}")`;lens.style.backgroundSize=`${w*ZOOM}px ${h*ZOOM}px`;
   lens.style.backgroundPosition=`${SIZE/2-x*w*ZOOM}px ${SIZE/2-y*h*ZOOM}px`;
  });
 });
}
