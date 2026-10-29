document.addEventListener('DOMContentLoaded',()=>{
  const scriptUrl=new URL(document.currentScript?.src||'assets/portal.js',location.href);
  const portalRoot=new URL('../',scriptUrl);
  let activeController=null;
  let navigationId=0;

  const updateCurrentLink=()=>{
    const current=new URL(location.href);
    document.querySelectorAll('.nav a').forEach(link=>{
      const destination=new URL(link.href,location.href);
      if(destination.pathname===current.pathname) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    });
  };

  const handleOptionalImages=scope=>{
    scope.querySelectorAll('img.optional-local-image').forEach(img=>{
      img.addEventListener('error',()=>{
        const figure=img.closest('figure');
        if(!figure)return;
        figure.classList.add('is-unavailable');
        img.hidden=true;
        const note=document.createElement('p');
        note.className='image-fallback';
        note.textContent='الصورة المحلية غير متاحة في هذه النسخة؛ افتح رابط المصدر أسفلها.';
        figure.prepend(note);
      },{once:true});
    });
  };

  const navigate=async(url,{push=true}={})=>{
    const id=++navigationId;
    activeController?.abort();
    const controller=new AbortController();
    activeController=controller;
    const main=document.querySelector('main#main');
    if(main)main.setAttribute('aria-busy','true');
    try{
      const response=await fetch(url.href,{signal:controller.signal,headers:{Accept:'text/html'}});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const markup=await response.text();
      const nextDocument=new DOMParser().parseFromString(markup,'text/html');
      const nextMain=nextDocument.querySelector('main#main');
      if(id!==navigationId)return;
      if(!nextMain)throw new Error('Missing main content');
      main?.replaceWith(nextMain);
      document.title=nextDocument.title;
      document.documentElement.lang=nextDocument.documentElement.lang||'ar';
      document.documentElement.dir=nextDocument.documentElement.dir||'rtl';
      if(push)history.pushState({portal:true},'',url.href);
      updateCurrentLink();
      handleOptionalImages(nextMain);
      const heading=nextMain.querySelector('h1');
      if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
      document.documentElement.style.scrollBehavior='auto';
      window.scrollTo(0,0);
      requestAnimationFrame(()=>document.documentElement.style.removeProperty('scroll-behavior'));
    }catch(error){
      if(error.name==='AbortError')return;
      if(id===navigationId)location.assign(url.href);
    }finally{
      if(id===navigationId){
        document.querySelector('main#main')?.removeAttribute('aria-busy');
        activeController=null;
      }
    }
  };

  document.addEventListener('click',event=>{
    const link=event.target.closest?.('a[href]');
    if(!link||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    if(link.target&&link.target!=='_self'||link.hasAttribute('download')||location.protocol==='file:')return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith(portalRoot.pathname)||!url.pathname.endsWith('.html'))return;
    if(url.pathname===location.pathname){
      if(url.hash)return;
      return;
    }
    event.preventDefault();
    navigate(url);
  });

  window.addEventListener('popstate',()=>navigate(new URL(location.href),{push:false}));
  updateCurrentLink();
  handleOptionalImages(document);
});
