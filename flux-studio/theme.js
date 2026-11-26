// Theme choice. Without one the system preference applies; the choice is a per-viewer convenience.
(()=>{
 const root=document.documentElement,key='masar-theme',system=matchMedia('(prefers-color-scheme: dark)');
 try{const saved=localStorage.getItem(key);if(saved==='light'||saved==='dark')root.dataset.theme=saved;}catch{}
 const dark=()=>root.dataset.theme?root.dataset.theme==='dark':system.matches;
 addEventListener('DOMContentLoaded',()=>{
  const button=document.getElementById('themeToggle'),show=()=>button.setAttribute('aria-pressed',String(dark()));
  button.onclick=()=>{root.dataset.theme=dark()?'light':'dark';try{localStorage.setItem(key,root.dataset.theme);}catch{}show();};
  system.addEventListener('change',show);show();
 });
})();
