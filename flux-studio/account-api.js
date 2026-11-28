// Calls to the account and project API, served on the studio's own origin.
export class ApiError extends Error{
 constructor(status,code,message){super(message);this.status=status;this.code=code;}
}

export function createApi(fetchImpl=(...args)=>globalThis.fetch(...args)){
 const send=async(path,options)=>{
  let response;try{response=await fetchImpl(path,{credentials:'same-origin',...options});}catch{throw new ApiError(0,'offline','تعذر الاتصال بالخادم المحلي.');}
  if(response.status===204)return null;
  let data;try{data=await response.json();}catch{throw new ApiError(response.status,'bad_reply','وصل رد غير مفهوم من الخادم.');}
  // django-ninja reports field errors as a list; the studio's own refusals use `error`.
  if(!response.ok)throw new ApiError(response.status,data?.code||'',typeof data?.detail==='string'?data.detail:data?.error||'تعذر تنفيذ الطلب.');
  return data;
 };
 const post=async(path,body)=>{
  // Asked each time: signing in rotates the token.
  const {csrf_token}=await send('/api/auth/csrf');
  return send(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf_token},body:JSON.stringify(body??{})});
 };
 const project=id=>`/api/projects/${encodeURIComponent(id)}`;
 const uploadAsset=async(bytes,type)=>{
  const {csrf_token}=await send('/api/auth/csrf');
  return (await send('/api/assets',{method:'POST',headers:{'Content-Type':type,'X-CSRFToken':csrf_token},body:bytes})).sha256;
 };
 const downloadAsset=async sha=>{
  let response;try{response=await fetchImpl(`/api/assets/${encodeURIComponent(sha)}`,{credentials:'same-origin'});}catch{throw new ApiError(0,'offline','تعذر الاتصال بالخادم المحلي.');}
  if(!response.ok)throw new ApiError(response.status,'asset','تعذر تنزيل إحدى صور المشروع.');
  return {bytes:await response.arrayBuffer(),type:response.headers.get('Content-Type')};
 };
 return {
  me:()=>send('/api/auth/me'),
  login:(username,password)=>post('/api/auth/login',{username,password}),
  logout:()=>post('/api/auth/logout'),
  changePassword:(current_password,new_password)=>post('/api/auth/change-password',{current_password,new_password}),
  projects:()=>send('/api/projects'),
  createProject:(title,client_key)=>post('/api/projects',{title,client_key}),
  renameProject:(id,title)=>post(`${project(id)}/rename`,{title}),
  deleteProject:id=>post(`${project(id)}/delete`),
  project:id=>send(project(id)),
  saveState:(id,revision,state)=>post(`${project(id)}/state`,{revision,state}),
  uploadAsset,downloadAsset,
 };
}
