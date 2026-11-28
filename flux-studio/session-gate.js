// The studio computes only for a signed-in account (the server enforces it); send everyone else to sign in.
// The work in this browser is saved in IndexedDB and is still there after coming back.
export async function needsSignIn(fetchImpl=(...args)=>globalThis.fetch(...args)){
 try{
  const response=await fetchImpl('/api/auth/me',{credentials:'same-origin',cache:'no-store'});
  if(!response.ok||(await response.json()).must_change_password!==false)return true;
  // (Re)issues the CSRF cookie that compute requests echo; an older session may not have it.
  await fetchImpl('/api/auth/csrf',{credentials:'same-origin',cache:'no-store'});
  return false;
 }catch{return true;}
}

if(globalThis.document)needsSignIn().then(needed=>{if(needed)location.replace('/projects?next=studio');});
