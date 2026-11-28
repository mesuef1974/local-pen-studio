import {createApi} from './account-api.js';

const api=createApi(),$=id=>document.getElementById(id);
const VIEWS=['loading','offline','login','password','projects'];
const dates=new Intl.DateTimeFormat('ar-QA-u-nu-latn',{dateStyle:'medium',timeStyle:'short'});
let user=null,createKey=null,createTitle='';

function show(view){
 for(const name of VIEWS)$(`view-${name}`).hidden=name!==view;
 $('account').hidden=!user;$('accountName').textContent=user?.full_name??'';
 $(`view-${view}`).querySelector('input,button')?.focus();
}
function say(text,failed=false){$('message').textContent=text;$('message').classList.toggle('failed',failed);}

function fail(error){
 if(error.code==='accounts_unavailable'){user=null;show('offline');say('');return;}
 if(error.status===401&&error.code!=='invalid_credentials'){user=null;show('login');say('انتهت الجلسة. سجّل الدخول من جديد.',true);return;}
 if(error.code==='password_change_required')show('password');
 say(error.message,true);
}

// One request at a time per control: a double click must not send twice.
async function run(control,action){
 if(control.disabled)return;
 control.disabled=true;say('');
 try{await action();}catch(error){fail(error);}finally{control.disabled=false;}
}

function button(text,kind,onClick){
 const element=document.createElement('button');element.type='button';element.className=`button ${kind}`;element.textContent=text;element.onclick=onClick;return element;
}

function card(project){
 const item=document.createElement('li'),title=document.createElement('strong'),when=document.createElement('time'),actions=document.createElement('div');
 title.textContent=project.title;title.dir='auto';
 when.dateTime=project.updated_at;when.textContent=dates.format(new Date(project.updated_at));
 actions.className='card-actions';
 const reset=()=>item.replaceChildren(title,when,actions);
 const rename=button('تغيير الاسم','secondary',()=>{
  const form=document.createElement('form'),input=document.createElement('input'),save=button('حفظ','primary');
  form.className='inline';input.value=project.title;input.maxLength=150;input.required=true;input.setAttribute('aria-label','اسم المشروع الجديد');
  save.type='submit';
  form.append(input,save,button('إلغاء','secondary',()=>{reset();rename.focus();}));
  form.onsubmit=event=>{event.preventDefault();run(save,async()=>{await api.renameProject(project.id,input.value);await load();say('تغيّر الاسم.');});};
  item.replaceChildren(form);input.select();
 });
 const remove=button('حذف','secondary',()=>{
  const question=document.createElement('p'),choices=document.createElement('div');
  const confirm=button('نعم، احذف','danger',()=>run(confirm,async()=>{await api.deleteProject(project.id);await load();say('حُذف المشروع.');}));
  const cancel=button('إلغاء','secondary',()=>{reset();remove.focus();});
  question.textContent=`حذف «${project.title}»؟ لا يمكن استرجاعه من هذه الصفحة.`;
  choices.className='card-actions';choices.append(confirm,cancel);
  item.replaceChildren(question,choices);cancel.focus();
 });
 actions.append(rename,remove);reset();return item;
}

async function load(){
 const projects=await api.projects();
 $('list').replaceChildren(...projects.map(card));
 $('empty').hidden=projects.length>0;
}

async function enter(account){
 user=account;
 if(account.must_change_password){show('password');return;}
 await load();show('projects');
}

async function start(){
 show('loading');say('');
 try{await enter(await api.me());}
 catch(error){
  user=null;
  if(error.status===401){show('login');return;}
  show('offline');
  if(error.code!=='accounts_unavailable')say(error.message,true);
 }
}

function onSubmit(formId,action){
 const form=$(formId);
 form.onsubmit=event=>{event.preventDefault();run(form.querySelector('[type=submit]'),()=>action(form));};
}
const field=(form,name)=>form.elements.namedItem(name);

onSubmit('view-login',async form=>{
 const account=await api.login(field(form,'username').value,field(form,'password').value);
 form.reset();await enter(account);
});
onSubmit('view-password',async form=>{
 const next=field(form,'next').value;
 if(next!==field(form,'again').value){say('كلمتا المرور الجديدتان غير متطابقتين.',true);return;}
 await api.changePassword(field(form,'current').value,next);
 form.reset();await enter(await api.me());say('تغيّرت كلمة المرور.');
});
onSubmit('create',async form=>{
 const title=field(form,'title').value.trim();
 // The same key for a retry of the same title, so a lost reply does not create a second project.
 if(!createKey||title!==createTitle){createKey=crypto.randomUUID();createTitle=title;}
 await api.createProject(title,createKey);createKey=null;
 form.reset();await load();say('أُنشئ المشروع.');
});
$('logout').onclick=()=>run($('logout'),async()=>{await api.logout();user=null;$('list').replaceChildren();show('login');say('خرجت من الحساب.');});
$('changePassword').onclick=()=>{say('');show('password');};
$('cancelPassword').onclick=start;
$('retry').onclick=start;
start();
