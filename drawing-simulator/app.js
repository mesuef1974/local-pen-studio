const $=id=>document.getElementById(id);
const source=$('sourceCanvas'),preview=$('previewCanvas'),simulation=$('simulationCanvas');
const state={hasImage:false,rawPaths:[],paths:[],worker:null,job:0,imageSerial:0,analysisSerial:0,busy:false,lmBusy:false,stream:null,view:'split',segments:[],totalTime:0,time:0,nextSegment:0,running:false,lastTick:0,frame:0};
const ink=document.createElement('canvas'),travel=document.createElement('canvas');
const prepOriginalCanvas=document.createElement('canvas');
let prepVersion=0,prepBusy=false,prepHasImage=false,prepApproved=false,prepImageURL='',prepDirty=false;
let timeout;
let featureRegion={x:.34,y:.27,width:.36,height:.34};
let approvedVectors=null;
function clearApprovedVectors(){delete document.body.dataset.approvedVectors;approvedVectors=null;for(const id of ['lineMode','lineDenoise','detail','minLength'])$(id).disabled=false;}
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
function controls(){const ready=state.paths.length>0;for(const id of ['playBtn','resetBtn','exportSvg','exportJson'])$(id).disabled=!ready;$('processBtn').disabled=!state.hasImage||state.busy;$('analyzeBtn').disabled=!state.hasImage||!$('lmModel').value||state.lmBusy;}
function paper(){const landscape=$('orientation').value==='landscape';return{width:landscape?297:210,height:landscape?210:297,margin:Math.min(50,Math.max(5,Number($('margin').value)||15))};}
function paintPaper(canvas){const ctx=canvas.getContext('2d'),p=paper();canvas.width=p.width/210*595;canvas.height=p.height/210*595;ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.strokeStyle='#e6e8e1';ctx.lineWidth=.6;ctx.setLineDash([4,5]);const s=canvas.width/p.width;ctx.strokeRect(p.margin*s,p.margin*s,(p.width-2*p.margin)*s,(p.height-2*p.margin)*s);ctx.setLineDash([]);return ctx;}
function penWidth(){return Math.max(.2,Math.min(1.2,Number($('penWidth').value)||.5));}
function drawPath(ctx,path,scale,color='#233e39',width=penWidth()){if(path.length<2)return;ctx.beginPath();ctx.moveTo(path[0][0]*scale,path[0][1]*scale);for(let i=1;i<path.length;i++)ctx.lineTo(path[i][0]*scale,path[i][1]*scale);ctx.strokeStyle=color;ctx.lineWidth=Math.max(.5,width*scale);ctx.lineCap='round';ctx.lineJoin='round';ctx.stroke();}
function setView(view){state.view=view;$('splitView').hidden=view!=='split';$('simulationView').hidden=view!=='simulation';document.querySelectorAll('[data-view]').forEach(b=>{const selected=b.dataset.view===view;b.classList.toggle('active',selected);b.setAttribute('aria-pressed',String(selected));});}
function stopAnimation(){state.running=false;cancelAnimationFrame(state.frame);$('playBtn').textContent='▶ تشغيل';}
function clearResults(){stopAnimation();state.rawPaths=[];state.detectedPaths=[];state.lineStats=null;state.paths=[];state.segments=[];$('pathDiagnostics').textContent='تنتظر اللوحة اكتمال حساب الخطوط…';state.time=0;state.totalTime=0;state.nextSegment=0;for(const id of ['strokeCount','inkLength','travelLength','estimatedTime'])$(id).textContent='—';$('progress').value=0;$('progressText').textContent='0%';paintPaper(preview);paintPaper(simulation);controls();}
function invalidate(auto=true){if(state.worker){state.worker.terminate();state.worker=null;}clearTimeout(timeout);state.job++;state.busy=false;clearResults();if(state.hasImage){status('تغيرت الإعدادات؛ تتحدث المعاينة تلقائيًا…');$('statusBadge').textContent='جارٍ تحديث المعاينة';}if(auto)scheduleDrawing();}
function setSource(image,name,fromPrep=false){invalidate(false);stopCamera();state.analysisSerial++;const max=approvedVectors?2000:1200,ratio=Math.min(1,max/Math.max(image.width,image.height));source.width=Math.max(3,Math.round(image.width*ratio));source.height=Math.max(3,Math.round(image.height*ratio));const ctx=source.getContext('2d',{willReadFrequently:true});ctx.fillStyle='white';ctx.fillRect(0,0,source.width,source.height);ctx.drawImage(image,0,0,source.width,source.height);if(!fromPrep)beginPreparation(image,name);state.hasImage=true;$('emptySource').hidden=true;$('imageName').textContent=name;$('resolution').textContent=`${source.width} × ${source.height}`;$('statusBadge').textContent='الصورة جاهزة';$('lmResult').textContent='هذه صورة جديدة. اضغط تحليل الصورة إذا أردت رأي نموذج الرؤية.';status('الصورة جاهزة. اعتمدها للرسم لتحديث المسارات تلقائيًا.');controls();}
async function loadImageFile(file){const serial=++state.imageSerial;if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)){status('اختر صورة PNG أو JPG أو WebP.',true);return;}if(file.size>12*1024*1024){status('الصورة أكبر من 12 MB. صغّرها أولًا.',true);return;}try{const image=await createImageBitmap(file,{imageOrientation:'from-image'});if(serial!==state.imageSerial){image.close();return;}if(image.width*image.height>40_000_000){image.close();status('دقة الصورة كبيرة جدًا لهذه التجربة. استخدم نسخة أصغر من 40 مليون بكسل.',true);return;}setSource(image,file.name);image.close();}catch{status('تعذر قراءة الصورة. جرّب صورة أخرى.',true);}}
function sample(){state.imageSerial++;const c=document.createElement('canvas');c.width=480;c.height=480;const x=c.getContext('2d');x.fillStyle='#fcfbf6';x.fillRect(0,0,480,480);x.lineWidth=3;x.lineCap='round';x.strokeStyle='#334e3c';
 x.beginPath();x.moveTo(235,320);x.bezierCurveTo(230,265,250,180,240,100);x.stroke();
 const leaves=[[240,145,180,95],[240,190,310,140],[238,240,164,196],[239,283,310,235],[237,120,268,67]];
 for(const[a,b,cx,cy]of leaves){x.beginPath();x.moveTo(a,b);x.quadraticCurveTo(cx-20,cy-20,cx,cy);x.quadraticCurveTo(cx+34,cy+22,a,b);x.fillStyle='#bdcdb4';x.fill();x.stroke();x.beginPath();x.moveTo(a,b);x.lineTo(cx,cy);x.stroke();}
 x.beginPath();x.moveTo(171,318);x.lineTo(308,318);x.lineTo(287,411);x.quadraticCurveTo(240,429,193,411);x.closePath();x.fillStyle='#d0af8d';x.fill();x.strokeStyle='#795e42';x.stroke();x.beginPath();x.ellipse(240,319,70,12,0,0,Math.PI*2);x.fillStyle='#e3cfac';x.fill();x.stroke();
 setSource(c,'مثال هندسي تجريبي — نبات في إناء، وليس صورة فوتوغرافية');}
async function processImage(){if(!state.hasImage||!prepApproved)return;invalidate(false);state.busy=true;controls();const job=++state.job;status('استخراج الخطوط وتبسيطها وترتيب ضربات القلم…');$('statusBadge').textContent='جارٍ التحويل';const image=source.getContext('2d').getImageData(0,0,source.width,source.height);let connected;try{connected=(approvedVectors&&approvedVectors.width===source.width&&approvedVectors.height===source.height)?approvedVectors:await api('/api/paths',{image:source.toDataURL('image/png'),level:Number($('drawingMode').value),detail:Number($('detail').value),minLength:Number($('minLength').value),lineMode:$('lineMode').value,inkThreshold:Number($('inkThresholdMain').value),lineDenoise:Number($('lineDenoise').value),tolerance:0});}catch(e){if(job===state.job){state.busy=false;status(e.message,true);controls();}return;}if(job!==state.job)return;state.worker=new Worker('trace-worker.js');timeout=setTimeout(()=>{if(job!==state.job)return;state.worker?.terminate();state.worker=null;state.busy=false;status('استغرقت المعالجة وقتًا طويلًا. قلل التفاصيل أو ارفع حد استبعاد الخطوط.',true);$('statusBadge').textContent='لم تكتمل';controls();},60000);
 state.worker.onerror=()=>{clearTimeout(timeout);state.busy=false;status('تعذر تنفيذ معالج الصورة المحلي.',true);state.worker?.terminate();state.worker=null;controls();};
 state.worker.onmessage=({data})=>{if(data.id!==state.job)return;clearTimeout(timeout);state.busy=false;state.worker?.terminate();state.worker=null;if(data.error){status('فشل استخراج المسارات: '+data.error,true);controls();return;}state.rawPaths=data.paths;state.protectedFlags=data.protectedFlags||[];state.refinement={joins:data.joinedCount||0,protected:data.protectedCount||0};state.detectedPaths=connected.paths;state.lineStats={selectedEdges:data.selectedEdges,pointsBefore:data.pointsBefore,pointsAfter:data.pointsAfter};state.extraction=connected;state.trace={width:data.width,height:data.height,rawCount:data.rawCount,truncated:data.truncated,hatchCount:data.hatchCount||0};if(!data.paths.length){$('statusBadge').textContent='لا توجد خطوط';status('لم تظهر خطوط مناسبة. جرّب تفاصيل أعلى، أو صورة أوضح، أو حدًا أصغر للخطوط القصيرة.');controls();return;}remap();$('statusBadge').textContent='المسارات جاهزة';status(`تجهيز ${state.paths.length.toLocaleString('ar-u-nu-latn')} ضربة قلم. تفاصيل ${$('drawingMode').value}/100 ${$('limitTime').checked?'ضمن ميزانية '+$('timeBudget').selectedOptions[0].textContent:'دون حذف زمني'}. مستخرج ${data.rawCount} مسار متصل؛ أسقطت ميزانية الوقت ${state.budgetOmitted} مسارًا. راجع المعاينة قبل التشغيل.${data.truncated?' استبعد مستوى التفاصيل بعض المسارات؛ يمكن زيادته للمقارنة.':''}`);};
 state.worker.postMessage({id:job,width:image.width,height:image.height,pixels:image.data,fitToStrokes:$('fitToStrokes').checked,protectFeatures:$('protectFeatures').checked,featureToleranceMm:.04,joinGapMm:Number($('joinGap').value),curveSmoothMm:Number($('curveSmooth').value),preserveInk:$('lineMode').value!=='edges'&&$('preserveInk').checked,basePaths:connected.paths,detail:Number($('detail').value),minLength:Number($('minLength').value),epsilon:Number($('smooth').value),shading:$('shading').checked,paper:paper(),penWidth:penWidth(),executionLevel:Number($('drawingMode').value),featureRegion:$('featureFocus').checked?featureRegion:null},[image.data.buffer]);}
function remap(){if(!state.rawPaths.length){paintPaper(preview);paintPaper(simulation);return;}stopAnimation();const p=paper();let minX=0,minY=0,maxX=state.trace.width-1,maxY=state.trace.height-1;if($('fitToStrokes').checked){minX=Infinity;minY=Infinity;maxX=-Infinity;maxY=-Infinity;for(const path of (state.detectedPaths?.length?state.detectedPaths:state.rawPaths))for(const [x,y]of path){minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);}}const w=Math.max(1,maxX-minX),h=Math.max(1,maxY-minY),s=Math.min((p.width-2*p.margin)/w,(p.height-2*p.margin)/h),ox=(p.width-w*s)/2,oy=(p.height-h*s)/2;
 state.paths=state.rawPaths.map(path=>path.map(([x,y])=>[(x-minX)*s+ox,(y-minY)*s+oy]));
 state.budgetOmitted=0;
 if($('limitTime').checked){
  const target=Number($('timeBudget').value)*(.2+.8*Number($('drawingMode').value)/100),speed=Math.min(100,Math.max(5,Number($('drawSpeed').value)||30));
  const candidates=state.paths,selected=[];let cursor=[p.margin,p.margin],seconds=0;
  // Rank comes from edge length, contrast and a central-image preference, not face recognition.
  for(const [pathIndex,path] of candidates.entries()){let length=0;for(let i=1;i<path.length;i++)length+=Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]);
   const a=path[0],b=path[path.length-1],reverse=Math.hypot(b[0]-cursor[0],b[1]-cursor[1])<Math.hypot(a[0]-cursor[0],a[1]-cursor[1]);if(reverse)path.reverse();
   const cost=length/speed+Math.hypot(path[0][0]-cursor[0],path[0][1]-cursor[1])/80+.4;
   // Reserve a little time for sparse shadows so they are not always dropped last.
   const isHatch=path.length===2,limit=isHatch?target:target*.85;
   if(!state.protectedFlags[pathIndex]&&seconds+cost>limit){state.budgetOmitted++;continue;}selected.push(path);seconds+=cost;cursor=path[path.length-1];
  }
  state.paths=selected;
 }
 state.paths=orderPenPaths(state.paths,p.margin);
 const ctx=paintPaper(preview),scale=preview.width/p.width;if($('compareInk').checked){ctx.save();ctx.globalAlpha=.22;ctx.drawImage(source,(ox-minX*s)*scale,(oy-minY*s)*scale,source.width*s*scale,source.height*s*scale);ctx.restore();}if($('showRejected').checked&&state.detectedPaths)for(const path of state.detectedPaths)drawPath(ctx,path.map(([x,y])=>[(x-minX)*s+ox,(y-minY)*s+oy]),scale,'#c7cec8',.18);
 for(const path of state.paths)drawPath(ctx,path,scale);preparePlan();controls();
 const stats=state.lineStats||{};$('pathDiagnostics').textContent=`المستخرج: ${state.detectedPaths?.length||0} مسار ← المختار: ${stats.selectedEdges||0} + ${state.trace.hatchCount||0} تهشير ← المحذوف بسبب الوقت: ${state.budgetOmitted} ← التنفيذ: ${state.paths.length} ضربة. نقاط الخطوط: ${stats.pointsBefore||0} قبل الاختصار / ${stats.pointsAfter||0} بعده. استمرار عند التقاطعات دون جسور: ${state.extraction?.junctionPairs||0}. حماية: ${state.refinement?.protected||0} مسار؛ وُصلت ${state.refinement?.joins||0} فجوة. ${$('lineMode').value==='ink'?'نسخ كامل للسواد بعد العتبة، مع إعادة مرور فوق الحبر لتقليل الرفع.':''} الرمادي للمقارنة فقط. قد يتجاوز الزمن الحصة لحفظ الملامح.`;}
function preparePlan(){stopAnimation();const speed=Math.min(100,Math.max(5,Number($('drawSpeed').value)||30));state.drawSpeed=speed;$('drawSpeed').value=String(speed);state.segments=[];let cursor=[paper().margin,paper().margin],t=0,inkLength=0,travelLength=0;
 const add=(kind,a,b,duration)=>{if(duration<=0)return;state.segments.push({kind,a,b,start:t,end:t+duration});t+=duration;};
 for(const path of state.paths){let d=Math.hypot(path[0][0]-cursor[0],path[0][1]-cursor[1]);travelLength+=d;add('travel',cursor,path[0],d/80);add('lift',path[0],path[0],.4);for(let i=1;i<path.length;i++){d=Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]);inkLength+=d;add('draw',path[i-1],path[i],d/speed);}cursor=path[path.length-1];}
 state.totalTime=t;state.metrics={inkMm:inkLength,travelMm:travelLength};$('strokeCount').textContent=state.paths.length.toLocaleString('ar-u-nu-latn');$('inkLength').textContent=(inkLength/1000).toFixed(2);$('travelLength').textContent=(travelLength/1000).toFixed(2);$('estimatedTime').textContent=formatTime(t);resetSimulation();}
function formatTime(seconds){const s=Math.max(0,Math.round(seconds)),m=Math.floor(s/60);return`${m}:${String(s%60).padStart(2,'0')}`;}
function resetSimulation(){stopAnimation();state.time=0;state.nextSegment=0;const p=paper();paintPaper(simulation);ink.width=simulation.width;ink.height=simulation.height;travel.width=simulation.width;travel.height=simulation.height;const x=travel.getContext('2d'),scale=travel.width/p.width;x.strokeStyle='#c6aa78';x.lineWidth=.45;x.setLineDash([3,4]);x.beginPath();for(const s of state.segments)if(s.kind==='travel'){x.moveTo(s.a[0]*scale,s.a[1]*scale);x.lineTo(s.b[0]*scale,s.b[1]*scale);}x.stroke();drawSimulation();updateProgress();}
function drawSimulation(){const ctx=simulation.getContext('2d'),p=paper(),s=simulation.width/p.width;ctx.fillStyle='white';ctx.fillRect(0,0,simulation.width,simulation.height);ctx.strokeStyle='#e4e8e0';ctx.lineWidth=.6;ctx.setLineDash([4,5]);ctx.strokeRect(p.margin*s,p.margin*s,(p.width-2*p.margin)*s,(p.height-2*p.margin)*s);ctx.setLineDash([]);if($('showTravel').checked)ctx.drawImage(travel,0,0);ctx.drawImage(ink,0,0);
 const seg=state.segments[state.nextSegment];let pen=state.segments.length?state.segments[state.segments.length-1].b:[p.margin,p.margin],down=false;
 if(seg){const u=Math.max(0,Math.min(1,(state.time-seg.start)/(seg.end-seg.start)));pen=[seg.a[0]+(seg.b[0]-seg.a[0])*u,seg.a[1]+(seg.b[1]-seg.a[1])*u];down=seg.kind==='draw';if(down)drawPath(ctx,[seg.a,pen],s);}
 if(state.paths.length){ctx.beginPath();ctx.arc(pen[0]*s,pen[1]*s,4,0,Math.PI*2);ctx.fillStyle=down?'#16857c':'#c3a266';ctx.fill();ctx.beginPath();ctx.arc(pen[0]*s,pen[1]*s,7,0,Math.PI*2);ctx.strokeStyle='#1d736744';ctx.stroke();}}
function updateProgress(){const value=state.totalTime?Math.min(1,state.time/state.totalTime):0;$('progress').value=value;$('progressText').textContent=Math.round(value*100)+'%';}
function tick(now){if(!state.running)return;const dt=Math.min(.15,Math.max(0,(now-state.lastTick)/1000));state.lastTick=now;state.time=Math.min(state.totalTime,state.time+dt*Number($('playbackSpeed').value));const x=ink.getContext('2d'),scale=ink.width/paper().width;
 while(state.nextSegment<state.segments.length&&state.segments[state.nextSegment].end<=state.time){const seg=state.segments[state.nextSegment++];if(seg.kind==='draw')drawPath(x,[seg.a,seg.b],scale);}
 drawSimulation();updateProgress();if(state.time>=state.totalTime){stopAnimation();$('statusBadge').textContent='اكتملت المحاكاة';status('اكتملت حركة القلم الافتراضية. يمكنك تصدير SVG أو مسارات JSON؛ لم تُرسل أوامر لأي جهاز.');return;}state.frame=requestAnimationFrame(tick);}
function play(){if(!state.paths.length)return;if(state.running){stopAnimation();$('statusBadge').textContent='متوقفة مؤقتًا';return;}if(state.time>=state.totalTime)resetSimulation();setView('simulation');state.running=true;state.lastTick=performance.now();$('playBtn').textContent='Ⅱ إيقاف مؤقت';$('statusBadge').textContent='القلم يتحرك';state.frame=requestAnimationFrame(tick);}
function download(content,type,name){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function exportSvg(){if(!state.paths.length)return;const p=paper();const lines=state.paths.map(path=>`<path d="${path.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(3)} ${y.toFixed(3)}`).join(' ')}"/>`).join('\n');download(`<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${p.width}mm" height="${p.height}mm" viewBox="0 0 ${p.width} ${p.height}"><title>Local drawing simulation: geometric line paths</title><g fill="none" stroke="#111" stroke-width="${penWidth().toFixed(1)}" stroke-linecap="round" stroke-linejoin="round">${lines}</g></svg>`,'image/svg+xml','drawing-paths.svg');}
function exportJson(){if(!state.paths.length)return;const p=paper();download(JSON.stringify({schema:'drawing-simulator/1',simulationOnly:true,units:'mm',coordinateSystem:'paper-top-left; x right; y down',paper:p,source:{width:source.width,height:source.height},method:state.extraction?.method||'imported approved paths',settings:{inkThreshold:Number($('inkThresholdMain').value),preserveInk:$('lineMode').value!=='edges'&&$('preserveInk').checked,protectFeatures:$('protectFeatures').checked,featureToleranceMm:.04,joinGapMm:Number($('joinGap').value),curveSmoothMm:Number($('curveSmooth').value),lineMode:$('lineMode').value,lineDenoise:Number($('lineDenoise').value),limitTime:$('limitTime').checked,featureRegion:$('featureFocus').checked?featureRegion:null,executionLevel:Number($('drawingMode').value),timeBudgetSeconds:Number($('timeBudget').value),shading:$('shading').checked,penWidthMm:penWidth(),fitToStrokes:$('fitToStrokes').checked,detail:Number($('detail').value),minLengthPixels:Number($('minLength').value),simplifyPixels:Number($('smooth').value)},timingAssumptions:{drawMmPerSecond:state.drawSpeed,travelMmPerSecond:80,penLiftLowerSecondsPerStroke:.4,accelerationIncluded:false},metrics:{...state.metrics,estimatedSeconds:state.totalTime,strokeCount:state.paths.length},notes:['No joint kinematics, force, collision checking or motor commands.','Photo-to-drawing quality has not been artistically validated.'],paths:state.paths.map((points,index)=>({id:index+1,points:points.map(p=>p.map(v=>+v.toFixed(3)))}))},null,2),'application/json','drawing-paths.json');}
async function startCamera(){if(!navigator.mediaDevices?.getUserMedia){status('الكاميرا تحتاج متصفحًا يدعمها وعنوان localhost. استخدم رفع صورة الآن.',true);return;}$('cameraBtn').disabled=true;try{stopCamera();const stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:false});state.stream=stream;$('video').srcObject=stream;$('cameraPanel').hidden=false;await $('video').play();status('الكاميرا تعمل للمعاينة فقط. اضغط التقاط لتثبيت الصورة وإيقافها.');}catch{status('لم تُفتح الكاميرا. تحقق من الإذن أو ارفع صورة محفوظة.',true);}finally{$('cameraBtn').disabled=false;}}
function stopCamera(){state.stream?.getTracks().forEach(track=>track.stop());state.stream=null;$('video').srcObject=null;$('cameraPanel').hidden=true;}
function capture(){const video=$('video');if(!video.videoWidth)return;const c=document.createElement('canvas');c.width=video.videoWidth;c.height=video.videoHeight;c.getContext('2d').drawImage(video,0,0);state.imageSerial++;setSource(c,'لقطة كاميرا ثابتة — توقفت الكاميرا بعد الالتقاط');}
async function api(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data;try{data=await response.json();}catch{throw new Error('شغّل الصفحة عبر server.py للوصول إلى LM Studio.');}if(!response.ok)throw new Error(data.error||'تعذر إكمال الطلب.');return data;}
async function connect(){const button=$('connectLm');button.disabled=true;$('lmResult').textContent='جارٍ الاتصال بخادمك المحلي…';try{const result=await api('/api/lm/models',{token:$('apiToken').value});$('lmModel').replaceChildren(new Option('اختر نموذج رؤية محمّلًا…',''));for(const model of result.models)$('lmModel').add(new Option(model.id,model.id));$('lmResult').textContent=result.models.length?`وجدت ${result.models.length} نموذجًا. تحقق أنه يقبل الصور قبل اختياره؛ إدراجه وحده لا يثبت دعم الرؤية.`:'لا توجد نماذج متاحة. حمّل نموذج رؤية داخل LM Studio ثم أعد الاتصال.';}catch(e){$('lmResult').textContent=e.message;}finally{button.disabled=false;controls();}}
async function analyze(){if(!state.hasImage||!$('lmModel').value||state.lmBusy)return;const serial=++state.analysisSerial;state.lmBusy=true;controls();$('lmResult').textContent='نموذج الرؤية يحلل الصورة محليًا…';try{const result=await api('/api/lm/analyze',{token:$('apiToken').value,model:$('lmModel').value,image:source.toDataURL('image/jpeg',.9)});if(serial!==state.analysisSerial)return;const text=typeof result.text==='string'?result.text:'لم يُرجع النموذج نصًا قابلًا للعرض.';$('lmResult').textContent=text+(result.finish_reason==='length'?'\n\nتنبيه: توقف الرد عند حد الطول؛ التحليل قد يكون غير مكتمل.':'');}catch(e){if(serial===state.analysisSerial)$('lmResult').textContent=e.message;}finally{state.lmBusy=false;controls();}}
$('imageFile').addEventListener('change',e=>loadImageFile(e.target.files[0]));$('sampleBtn').addEventListener('click',sample);$('cameraBtn').addEventListener('click',startCamera);$('stopCameraBtn').addEventListener('click',stopCamera);$('captureBtn').addEventListener('click',capture);$('processBtn').addEventListener('click',processImage);$('playBtn').addEventListener('click',play);$('resetBtn').addEventListener('click',()=>{resetSimulation();$('statusBadge').textContent='جاهزة لإعادة التشغيل';});
for(const id of ['detail','minLength','smooth'])$(id).addEventListener('input',()=>{$('detailValue').textContent=$('detail').value+' / 100';$('lengthValue').textContent=$('minLength').value+' بكسل';$('smoothValue').textContent=Number($('smooth').value).toFixed(1)+' بكسل';invalidate();});
for(const id of ['orientation','margin'])$(id).addEventListener('change',()=>{$('margin').value=String(paper().margin);remap();});$('drawSpeed').addEventListener('change',()=>{if(state.rawPaths.length)remap();});$('showTravel').addEventListener('change',drawSimulation);$('exportSvg').addEventListener('click',exportSvg);$('exportJson').addEventListener('click',exportJson);document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));$('connectLm').addEventListener('click',connect);$('lmModel').addEventListener('change',controls);$('analyzeBtn').addEventListener('click',analyze);document.addEventListener('visibilitychange',()=>{if(document.hidden){stopCamera();if(state.running)stopAnimation();}});window.addEventListener('pagehide',()=>{stopCamera();state.worker?.terminate();});
paintPaper(preview);paintPaper(simulation);controls();

$('fitToStrokes').addEventListener('change',remap);$('penWidth').addEventListener('input',()=>{$('penWidthValue').textContent=penWidth().toFixed(1)+' مم';if(state.paths.length)remap();});

$('shading').addEventListener('change',invalidate);

for(const id of ['timeBudget'])$(id).addEventListener('change',invalidate);

$('featureFocus').addEventListener('change',invalidate);
source.style.cursor='crosshair';
source.addEventListener('click',event=>{
 if(!state.hasImage)return;
 const bounds=source.getBoundingClientRect(),cx=(event.clientX-bounds.left)/bounds.width,cy=(event.clientY-bounds.top)/bounds.height;
 const width=featureRegion.width,height=featureRegion.height;featureRegion={x:Math.max(0,Math.min(1-width,cx-width/2)),y:Math.max(0,Math.min(1-height,cy-height/2)),width,height};
 $('featureFocus').checked=true;$('focusHint').textContent=`تحديد يدوي: مركز الملامح عند ${Math.round(cx*100)}٪ أفقيًا و${Math.round(cy*100)}٪ رأسيًا. تتحدث المسارات تلقائيًا.`;invalidate();
});

for(const id of ['focusWidth','focusHeight'])$(id).addEventListener('input',()=>{
 const requestedWidth=Number($('focusWidth').value),requestedHeight=Number($('focusHeight').value);if(requestedWidth<20||requestedWidth>100||requestedHeight<20||requestedHeight>100)return;
 const cx=featureRegion.x+featureRegion.width/2,cy=featureRegion.y+featureRegion.height/2,width=Math.max(.2,Math.min(1,Number($('focusWidth').value)/100||.36)),height=Math.max(.2,Math.min(1,Number($('focusHeight').value)/100||.34));
 $('focusWidth').value=Math.round(width*100);$('focusHeight').value=Math.round(height*100);
 featureRegion={x:Math.max(0,Math.min(1-width,cx-width/2)),y:Math.max(0,Math.min(1-height,cy-height/2)),width,height};updateFocusBox();invalidate();
});

let executionTimer;
$('drawingMode').addEventListener('input',()=>{
 const level=Math.max(0,Math.min(100,Number($('drawingMode').value)));
 $('drawingModeValue').textContent=level+' / 100';$('timeBudget').disabled=!$('limitTime').checked;
 invalidate();clearTimeout(executionTimer);
 if(state.hasImage&&prepApproved)executionTimer=setTimeout(processImage,400);
});

const prepDefaults={brightness:0,gamma:100,contrast:100,local:0,denoise:0,sharp:0,enhance:0,morphology:0,edgeStrength:50,cropX:0,cropY:0,cropW:100,cropH:100,rotation:0,style:'photo'};
function setStage(stage){$('prepStage').hidden=stage!=='prep';$('drawingStage').hidden=stage!=='draw';$('showPrep').className='button '+(stage==='prep'?'primary':'secondary');$('showDrawing').className='button '+(stage==='draw'?'primary':'secondary');if(stage==='prep')stopAnimation();requestAnimationFrame(updateFocusBox);}
function prepControls(){
 $('applyPrep').disabled=!prepHasImage||prepBusy;$('resetPrep').disabled=!prepHasImage||prepBusy;
 $('approvePrep').disabled=!prepHasImage||prepBusy||prepDirty;$('downloadPrep').disabled=!prepHasImage||prepBusy||prepDirty;
 $('showDrawing').disabled=!prepApproved||prepDirty||prepBusy;
}
function resetPrepFields(){for(const [key,value]of Object.entries(prepDefaults)){const input=$('prep-'+key);input.value=String(value);const output=$('prep-'+key+'-value');if(output)output.textContent=value;}}
function beginPreparation(image,name){
 clearApprovedVectors();
 prepVersion++;prepHasImage=true;prepApproved=false;prepDirty=false;
 const ratio=Math.min(1,2000/Math.max(image.width,image.height));prepOriginalCanvas.width=Math.round(image.width*ratio);prepOriginalCanvas.height=Math.round(image.height*ratio);
 const ctx=prepOriginalCanvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,prepOriginalCanvas.width,prepOriginalCanvas.height);ctx.drawImage(image,0,0,prepOriginalCanvas.width,prepOriginalCanvas.height);
 $('prepOriginal').src=prepOriginalCanvas.toDataURL('image/png');prepImageURL=$('prepOriginal').src;$('prepResult').src=prepImageURL;
 resetPrepFields();syncDependencies();$('prepStatus').textContent='الأصل محفوظ في ذاكرة المتصفح. اضبط الأدوات وطبّق التجهيز، أو اعتمد الأصل مباشرة.';prepControls();setStage('prep');
}
for(const key of Object.keys(prepDefaults))$('prep-'+key).addEventListener('input',()=>{
 const output=$('prep-'+key+'-value');if(output)output.textContent=$('prep-'+key).value;
 if(!prepHasImage)return;clearApprovedVectors();prepVersion++;prepDirty=true;prepApproved=false;clearResults();prepControls();$('prepStatus').textContent='جارٍ تحديث المعاينة تلقائيًا…';queuePreparation();
});
async function applyPreparation(){
 if(!prepHasImage)return;if(prepBusy){prepPending=true;return;}prepPending=false;prepBusy=true;prepControls();const serial=++prepVersion;
 const settings={};for(const key of Object.keys(prepDefaults))settings[key]=key==='style'?$('prep-'+key).value:Number($('prep-'+key).value);
 $('prepStatus').textContent='جارٍ التجهيز في Python محليًا…';
 try{const result=await api('/api/prepare',{image:prepOriginalCanvas.toDataURL('image/jpeg',.95),settings});if(serial!==prepVersion)return;
 prepImageURL=result.image;$('prepResult').src=result.image;prepDirty=false;prepApproved=false;clearResults();
 $('prepStatus').textContent=`اكتمل التجهيز: ${result.width} × ${result.height} خلال ${result.milliseconds} مللي ثانية · OpenCV ${result.libraries.OpenCV} · Pillow ${result.libraries.Pillow}. راجع النتيجة ثم اعتمدها.`;
 }catch(e){if(serial===prepVersion)$('prepStatus').textContent=e.message;}finally{prepBusy=false;prepControls();if(prepPending)queuePreparation();}
}
$('applyPrep').addEventListener('click',applyPreparation);
$('resetPrep').addEventListener('click',()=>{prepVersion++;resetPrepFields();prepImageURL=$('prepOriginal').src;$('prepResult').src=prepImageURL;prepDirty=false;prepApproved=false;clearResults();$('prepStatus').textContent='استُعيد الأصل. يمكنك اعتماده أو تطبيق إعدادات جديدة.';prepControls();});
$('approvePrep').addEventListener('click',async()=>{
 if(!prepHasImage||prepDirty||prepBusy)return;const serial=prepVersion;
 try{const image=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=prepImageURL;});const bitmap=await createImageBitmap(image);if(serial!==prepVersion){bitmap.close();return;}
 setSource(bitmap,'صورة معتمدة من المرحلة الأولى',true);bitmap.close();prepApproved=true;prepControls();setStage('draw');status('الصورة المجهزة معتمدة؛ جارٍ تحديث الرسم تلقائيًا.');scheduleDrawing();
 }catch{$('prepStatus').textContent='تعذر اعتماد الصورة المجهزة.';}
});
$('downloadPrep').addEventListener('click',()=>{if(!prepHasImage||prepDirty||prepBusy)return;const a=document.createElement('a');a.href=prepImageURL;a.download='prepared-image.png';a.click();});
$('showPrep').addEventListener('click',()=>setStage('prep'));
$('showDrawing').addEventListener('click',()=>{if(prepApproved&&!prepDirty)setStage('draw');});
prepControls();

$('limitTime').addEventListener('change',()=>{if(state.rawPaths.length){remap();status('تغير حد الوقت: '+state.paths.length+' ضربة، محذوفة بسبب الوقت: '+state.budgetOmitted+'؛ راجع المعاينة.');}});

function orderPenPaths(paths,margin){

  const remaining=paths.slice(),ordered=[];let at=[margin,margin];
  while(remaining.length){let best=0,flip=false,distance=Infinity;for(let i=0;i<remaining.length;i++){const path=remaining[i];for(const end of [0,path.length-1]){const d=Math.hypot(path[end][0]-at[0],path[end][1]-at[1]);if(d<distance){distance=d;best=i;flip=end!==0;}}}const path=remaining.splice(best,1)[0].slice();if(flip)path.reverse();ordered.push(path);at=path[path.length-1];}
  const travelCost=paths=>{let total=0,at=[margin,margin];for(const path of paths){total+=Math.hypot(path[0][0]-at[0],path[0][1]-at[1]);at=path[path.length-1];}return total;};
  return travelCost(ordered)<=travelCost(paths)?ordered:paths;
}

let prepTimer,prepPending=false;
function queuePreparation(){clearTimeout(prepTimer);prepTimer=setTimeout(applyPreparation,350);}
function scheduleDrawing(){clearTimeout(executionTimer);if(state.hasImage&&prepApproved&&!prepDirty)executionTimer=setTimeout(processImage,400);}
function syncDependencies(){
 $('prep-edgeStrength').disabled=$('prep-style').value!=='edges';
 $('timeBudget').disabled=!$('limitTime').checked;
 for(const id of ['focusWidth','focusHeight'])$(id).disabled=!$('featureFocus').checked;
}
for(const id of ['prep-style','limitTime','featureFocus'])$(id).addEventListener('change',syncDependencies);
syncDependencies();

// One-time, same-tab transfer of an explicitly approved local model output.
const approvedLineart=sessionStorage.getItem('lineart-approved');
const approvedVectorText=sessionStorage.getItem('lineart-paths-approved');sessionStorage.removeItem('lineart-paths-approved');
if(approvedLineart){sessionStorage.removeItem('lineart-approved');const image=new Image();image.onload=()=>{beginPreparation(image,'رسم نموذج Lineart');$('lineMode').value='centerline';$('shading').checked=false;$('drawingMode').value=100;$('drawingModeValue').textContent='100 / 100';$('lineDenoise').value=0;$('minLength').value=2;$('lineDenoiseValue').textContent='0';$('lengthValue').textContent='2 بكسل';$('smoothValue').textContent='0 بكسل';$('joinGapValue').textContent='0.00 مم';$('curveSmoothValue').textContent='0.00 مم';$('fitToStrokes').checked=false;for(const id of ['smooth','joinGap','curveSmooth'])$(id).value=0;for(const id of ['featureFocus','protectFeatures','limitTime'])$(id).checked=false;
 try{const vector=JSON.parse(approvedVectorText||'null');if(vector&&vector.width===image.width&&vector.height===image.height&&Array.isArray(vector.paths)&&vector.paths.length<=6000&&vector.paths.every(p=>Array.isArray(p)&&p.length>=2&&p.every(q=>Array.isArray(q)&&q.length===2&&q.every(Number.isFinite)&&q[0]>=0&&q[0]<vector.width&&q[1]>=0&&q[1]<vector.height))){approvedVectors=vector;document.body.dataset.approvedVectors='true';if(vector.lineMode==='ink')$('lineMode').value='ink';if(Number.isFinite(vector.penWidthMm)&&vector.penWidthMm>=.2&&vector.penWidthMm<=1.2){$('penWidth').value=vector.penWidthMm;$('penWidthValue').textContent=vector.penWidthMm+' مم';}$('drawingMode').value=100;$('drawingModeValue').textContent='100 / 100';for(const id of ['smooth','joinGap','curveSmooth'])$(id).value=0;for(const id of ['featureFocus','protectFeatures','limitTime'])$(id).checked=false;for(const id of ['lineMode','lineDenoise','detail','minLength'])$(id).disabled=true;$('prepStatus').textContent='وصلت الخطوط المختارة نفسها دون إعادة استخراج. اعتمادها يحافظ على هندستها؛ تعديل تجهيز الصورة يعيد التتبع من الصورة.';}}
 catch{};syncInkSafety();$('approvePrep').click();};image.src=approvedLineart;}

$('lineMode').addEventListener('change',()=>{syncInkSafety();invalidate();});
$('lineDenoise').addEventListener('input',()=>{$('lineDenoiseValue').textContent=$('lineDenoise').value;invalidate();});
$('showRejected').addEventListener('change',remap);

$('protectFeatures').addEventListener('change',()=>invalidate());
for(const id of ['joinGap','curveSmooth'])$(id).addEventListener('input',()=>{$(id+'Value').textContent=Number($(id).value).toFixed(2)+' مم';invalidate();});

function updateFocusBox(){
 const box=$('focusBox'),rect=source.getBoundingClientRect(),parent=source.parentElement.getBoundingClientRect();
 box.hidden=!state.hasImage||!$('featureFocus').checked||!rect.width||!rect.height;
 if(box.hidden)return;
 box.style.left=(rect.left-parent.left+featureRegion.x*rect.width)+'px';box.style.top=(rect.top-parent.top+featureRegion.y*rect.height)+'px';
 box.style.width=(featureRegion.width*rect.width)+'px';box.style.height=(featureRegion.height*rect.height)+'px';
}
new ResizeObserver(updateFocusBox).observe(source);
for(const id of ['featureFocus','focusWidth','focusHeight'])$(id).addEventListener('change',updateFocusBox);
source.addEventListener('click',updateFocusBox);

$('referenceBtn').addEventListener('click',async()=>{
 try{const response=await fetch('reference-benchmark/reference.png');if(!response.ok)throw new Error('تعذر تحميل المرجع.');
 await loadImageFile(new File([await response.blob()],'مرجع هندسي — عشرة مكونات خطية.png',{type:'image/png'}));
 $('lineMode').value='centerline';$('lineDenoise').value='0';$('lineDenoiseValue').textContent='0';
 $('drawingMode').value='100';$('drawingModeValue').textContent='100 / 100';
 for(const id of ['shading','featureFocus','protectFeatures','limitTime'])$(id).checked=false;
 $('minLength').value='2';$('lengthValue').textContent='2 بكسل';$('smooth').value='0';$('smoothValue').textContent='0.0 بكسل';
 $('joinGap').value='0';$('joinGapValue').textContent='0.00 مم';$('curveSmooth').value='0';$('curveSmoothValue').textContent='0.00 مم';
 syncDependencies();syncInkSafety();$('prepStatus').textContent='مرجع هندسي اصطناعي بعشرة مكونات منفصلة. الاختبار دون حذف أو تهشير أو وصل أو تنعيم أو اختصار؛ اعتمد الأصل ثم راجع المسارات.';
 }catch(e){$('prepStatus').textContent=e.message;}
});


function syncInkSafety(){
 const mode=$('lineMode').value,copy=mode==='ink',locked=mode!=='edges'&&$('preserveInk').checked;
 $('pathMethodHint').textContent=copy?'نسخ السواد بعد العتبة عبر مسارات تعبئة متصلة؛ قد تعيد المرور فوق الحبر لتقليل الرفع. القلم العريض قد يغلق الفراغات الدقيقة.':mode==='centerline'?'تتبّع مركز الخط مع استمرار حذر عند التقاطعات؛ هذا الوضع لا يملأ كتل السواد.':'استخراج حواف متصلة عبر OpenCV EdgeDrawing.';$('inkSafetyPanel').hidden=mode==='edges';$('inkThresholdMain').disabled=Boolean(approvedVectors);$('preserveInk').disabled=copy;
 if(copy){$('lineDenoise').value=0;$('lineDenoiseValue').textContent='0';$('preserveInk').checked=true;$('drawingMode').value=100;$('drawingModeValue').textContent='100 / 100';for(const id of ['limitTime','featureFocus','protectFeatures','shading','fitToStrokes'])$(id).checked=false;}
 for(const id of ['drawingMode','limitTime','featureFocus','protectFeatures','shading','fitToStrokes'])$(id).disabled=copy;
 for(const id of ['lineDenoise','detail','minLength'])$(id).disabled=copy||Boolean(approvedVectors);
 for(const id of ['joinGap','curveSmooth','smooth']){$(id).disabled=locked||copy;if(locked||copy)$(id).value=0;}
 if(locked||copy){$('joinGapValue').textContent='0.00 مم';$('curveSmoothValue').textContent='0.00 مم';$('smoothValue').textContent='0 بكسل';}
}
$('preserveInk').addEventListener('change',()=>{syncInkSafety();invalidate();});
$('safeInkBtn').addEventListener('click',()=>{
 clearApprovedVectors();$('lineMode').value='ink';$('penWidth').value=.3;$('penWidthValue').textContent='0.3 مم';$('preserveInk').checked=true;$('drawingMode').value=100;$('drawingModeValue').textContent='100 / 100';
 for(const id of ['limitTime','featureFocus','protectFeatures','shading','fitToStrokes'])$(id).checked=false;
 $('lineDenoise').value=0;$('lineDenoiseValue').textContent='0';$('minLength').value=2;$('lengthValue').textContent='2 بكسل';
 syncDependencies();syncInkSafety();updateFocusBox();invalidate();
});
$('compareInk').addEventListener('change',remap);
syncInkSafety();

$('inkThresholdMain').addEventListener('change',()=>invalidate());
