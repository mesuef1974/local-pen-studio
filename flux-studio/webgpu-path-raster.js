import {requestJson as api} from './api-client.js';

let contextPromise;
const pipelineCache=new Map();

function chooseCoverageModel(target){
 const sourcePixels=target.sourceWidth*target.sourceHeight;
 const detail=sourcePixels>=300000&&target.edgeDensity>=0.04;
 return detail?{name:'dense-edge-4x4',radiusScale:0.975,coverageThreshold:9,reason:'edge density >= 0.04 on >= 300,000 source pixels'}:
  {name:'baseline-4x4',radiusScale:1,coverageThreshold:8,reason:'sparse/small source image'};
}

async function getContext(){
 if(contextPromise)return contextPromise;
 contextPromise=(async()=>{
  if(!navigator.gpu)throw new Error('WebGPU غير متاح في هذا المتصفح.');
  const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'});
  if(!adapter)throw new Error('لم يعثر المتصفح على محول WebGPU.');
  const device=await adapter.requestDevice(),i=adapter.info||{};
  return {device,adapter:{vendor:i.vendor||'',architecture:i.architecture||'',device:i.device||'',description:i.description||''}};
 })();
 try{return await contextPromise;}catch(error){contextPromise=null;throw error;}
}

function compile(device,width,height,scale,pad,radius,coverageThreshold){
 const renderCode=`
  struct Segment { a: vec2<f32>, b: vec2<f32> };
  @group(0) @binding(0) var<storage,read> segments:array<Segment>;
  @group(0) @binding(1) var<storage,read_write> coverageBits:array<atomic<u32>>;
  const W:f32=${width}.0; const H:f32=${height}.0; const SCALE:f32=${scale}.0;
  const PAD:f32=${pad}.0; const RADIUS:f32=${radius.toPrecision(10)};
  struct VertexOut { @builtin(position) position:vec4<f32>, @location(0) @interpolate(flat) a:vec2<f32>, @location(1) @interpolate(flat) b:vec2<f32> };
  @vertex fn vs(@builtin(vertex_index) vertex:u32,@builtin(instance_index) instance:u32)->VertexOut {
   let s=segments[instance];let a=s.a*SCALE+vec2<f32>(PAD+0.5*SCALE);let b=s.b*SCALE+vec2<f32>(PAD+0.5*SCALE);
   let corners=array<vec2<f32>,6>(vec2<f32>(0,0),vec2<f32>(1,0),vec2<f32>(0,1),vec2<f32>(0,1),vec2<f32>(1,0),vec2<f32>(1,1));
   let lo=min(a,b)-vec2<f32>(RADIUS);let hi=max(a,b)+vec2<f32>(RADIUS);let p=mix(lo,hi,corners[vertex]);
   var out:VertexOut;out.position=vec4<f32>(p.x/W*2.0-1.0,1.0-p.y/H*2.0,0.0,1.0);out.a=a;out.b=b;return out;
  }
  @fragment fn fs(in:VertexOut)->@location(0) f32 {
   let ab=in.b-in.a;
   let offsets=array<vec2<f32>,16>(
    vec2<f32>(-0.375,-0.375),vec2<f32>(-0.125,-0.375),vec2<f32>(0.125,-0.375),vec2<f32>(0.375,-0.375),
    vec2<f32>(-0.375,-0.125),vec2<f32>(-0.125,-0.125),vec2<f32>(0.125,-0.125),vec2<f32>(0.375,-0.125),
    vec2<f32>(-0.375,0.125),vec2<f32>(-0.125,0.125),vec2<f32>(0.125,0.125),vec2<f32>(0.375,0.125),
    vec2<f32>(-0.375,0.375),vec2<f32>(-0.125,0.375),vec2<f32>(0.125,0.375),vec2<f32>(0.375,0.375));
   var hits=0u;
   for(var sample=0u;sample<16u;sample++){
    let point=in.position.xy+offsets[sample];let t=clamp(dot(point-in.a,ab)/max(dot(ab,ab),0.000001),0.0,1.0);
    if(distance(point,in.a+t*ab)<=RADIUS){hits|=1u<<sample;}
   }
   if(hits!=0u){let p=vec2<u32>(in.position.xy);let index=p.y*u32(W)+p.x;atomicOr(&coverageBits[index/2u],hits<<((index%2u)*16u));}
   return 0.0;
  }`;
 const coverageWords=Math.ceil(width*height/2),resetGroupsX=Math.min(65535,Math.ceil(coverageWords/256));
 const resetCode=`
  @group(0) @binding(0) var<storage,read_write> coverageBits:array<atomic<u32>>;
  @compute @workgroup_size(256) fn main(@builtin(global_invocation_id) id:vec3<u32>){let index=id.x+id.y*${resetGroupsX*256}u;if(index<${coverageWords}u){atomicStore(&coverageBits[index],0u);}}`;
 const scoreCode=`
  @group(0) @binding(0) var drawnMask:texture_2d<f32>;
  @group(0) @binding(1) var<storage,read> targetBits:array<u32>;
  @group(0) @binding(2) var<storage,read_write> coverageBits:array<atomic<u32>>;
  @group(0) @binding(3) var<storage,read_write> counts:array<atomic<u32>>;
  @compute @workgroup_size(16,16) fn main(@builtin(global_invocation_id) id:vec3<u32>){
   let dims=textureDimensions(drawnMask);if(id.x>=dims.x||id.y>=dims.y){return;}
   let index=id.y*dims.x+id.x;let expected=(targetBits[index/32u]&(1u<<(index%32u)))!=0u;
   let coverage=(atomicLoad(&coverageBits[index/2u])>>((index%2u)*16u))&65535u;
   let actual=countOneBits(coverage)>=${coverageThreshold}u;
   if(expected){atomicAdd(&counts[1],1u);}if(actual){atomicAdd(&counts[2],1u);}
   if(expected&&actual){atomicAdd(&counts[0],1u);}
  }`;
 const renderModule=device.createShaderModule({code:renderCode}),resetModule=device.createShaderModule({code:resetCode}),scoreModule=device.createShaderModule({code:scoreCode});
 return {
  render:device.createRenderPipeline({layout:'auto',vertex:{module:renderModule,entryPoint:'vs'},fragment:{module:renderModule,entryPoint:'fs',targets:[{format:'r8unorm'}]},primitive:{topology:'triangle-list'}}),
  reset:device.createComputePipeline({layout:'auto',compute:{module:resetModule,entryPoint:'main'}}),
  score:device.createComputePipeline({layout:'auto',compute:{module:scoreModule,entryPoint:'main'}})
 };
}

export async function auditPathsDirectWebGPU({image,paths,mmPerPixel,penMm,inkThreshold=0,radiusScale=1,coverageThreshold=8,coverageModel='fixed'}){
 const totalStart=performance.now(),target=await api('/api/path-audit-target',{image,mmPerPixel,penMm,inkThreshold}),prepMs=performance.now()-totalStart;
 const selected=coverageModel==='adaptive'?chooseCoverageModel(target):{name:'fixed',radiusScale,coverageThreshold,reason:'fixed benchmark parameters'};
 radiusScale=selected.radiusScale;coverageThreshold=selected.coverageThreshold;
 const {device,adapter}=await getContext();
 const gpuErrors=[];device.addEventListener('uncapturederror',event=>gpuErrors.push(String(event.error?.message||event.error)));
 let deviceLost=null;device.lost.then(info=>{deviceLost={reason:info.reason,message:info.message};});
 const width=target.width,height=target.height,scale=target.auditUpscale,pad=target.pad,radius=penMm/mmPerPixel*scale/2*radiusScale;
 const coverageWords=Math.ceil(width*height/2),resetGroupsX=Math.min(65535,Math.ceil(coverageWords/256));
 const pipelineKey=[width,height,scale,pad,radius.toPrecision(9),coverageThreshold].join(':');
 let pipeline=pipelineCache.get(pipelineKey);
 if(!pipeline){pipeline=compile(device,width,height,scale,pad,radius,coverageThreshold);pipelineCache.set(pipelineKey,pipeline);}
 const segments=[];
 for(const path of paths)for(let n=1;n<path.length;n++)segments.push(...path[n-1],...path[n]);
 const vertexData=segments.length?new Float32Array(segments):new Float32Array(4);
 const segmentCount=vertexData.length/4;
 const packed=Uint8Array.from(atob(target.bitsBase64),c=>c.charCodeAt(0));
 const segmentBuffer=device.createBuffer({size:vertexData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
 const targetBuffer=device.createBuffer({size:packed.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
 device.queue.writeBuffer(segmentBuffer,0,vertexData);device.queue.writeBuffer(targetBuffer,0,packed);
 const coverageBuffer=device.createBuffer({size:Math.ceil(width*height/2)*4,usage:GPUBufferUsage.STORAGE});
 const texture=device.createTexture({size:[width,height],format:'r8unorm',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.TEXTURE_BINDING});
 const counters=device.createBuffer({size:16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST});
 const result=device.createBuffer({size:16,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
 const renderGroup=device.createBindGroup({layout:pipeline.render.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:segmentBuffer}},{binding:1,resource:{buffer:coverageBuffer}}]});
 const resetGroup=device.createBindGroup({layout:pipeline.reset.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:coverageBuffer}}]});
 const scoreGroup=device.createBindGroup({layout:pipeline.score.getBindGroupLayout(0),entries:[{binding:0,resource:texture.createView()},{binding:1,resource:{buffer:targetBuffer}},{binding:2,resource:{buffer:coverageBuffer}},{binding:3,resource:{buffer:counters}}]});
 const gpuStart=performance.now(),encoder=device.createCommandEncoder(),reset=encoder.beginComputePass();reset.setPipeline(pipeline.reset);reset.setBindGroup(0,resetGroup);reset.dispatchWorkgroups(resetGroupsX,Math.ceil(Math.ceil(coverageWords/256)/resetGroupsX));reset.end();
 const render=encoder.beginRenderPass({colorAttachments:[{view:texture.createView(),clearValue:{r:1,g:1,b:1,a:1},loadOp:'clear',storeOp:'store'}]});
 if(segmentCount){render.setPipeline(pipeline.render);render.setBindGroup(0,renderGroup);render.draw(6,segmentCount);}render.end();
 device.queue.writeBuffer(counters,0,new Uint32Array(4));const compute=encoder.beginComputePass();compute.setPipeline(pipeline.score);compute.setBindGroup(0,scoreGroup);compute.dispatchWorkgroups(Math.ceil(width/16),Math.ceil(height/16));compute.end();
 encoder.copyBufferToBuffer(counters,0,result,0,16);device.queue.submit([encoder.finish()]);await result.mapAsync(GPUMapMode.READ);
 const [both,expected,drawn]=Array.from(new Uint32Array(result.getMappedRange().slice(0)));result.unmap();const gpuMs=performance.now()-gpuStart;
 texture.destroy();segmentBuffer.destroy();targetBuffer.destroy();coverageBuffer.destroy();counters.destroy();result.destroy();
 const union=both+expected+drawn-2*both;
 return {width,height,pixels:width*height,segmentCount,penMm,mmPerPixel,auditUpscale:scale,
  counts:{both,expected,drawn},inkIoU:union?100*both/union:100,inkRecall:expected?100*both/expected:100,
  inkPrecision:drawn?100*both/drawn:(expected?0:100),missingInkPercent:expected?100*(expected-both)/expected:0,
  extraInkPercent:drawn?100*(drawn-both)/drawn:0,targetBitsBytes:packed.byteLength,
  segmentBufferBytes:vertexData.byteLength,coverageBufferBytes:Math.ceil(width*height/2)*4,
  readbackBytes:16,maskTextureBytes:width*height,
  expectedPixels:target.expected,approxGpuWorkingSetBytes:packed.byteLength+vertexData.byteLength+Math.ceil(width*height/2)*4+width*height+32,
  gpuErrors,deviceLost,limits:{maxTextureDimension2D:device.limits.maxTextureDimension2D,maxStorageBufferBindingSize:device.limits.maxStorageBufferBindingSize,maxComputeWorkgroupsPerDimension:device.limits.maxComputeWorkgroupsPerDimension},
  targetPreparationMs:prepMs,gpuStageMs:gpuMs,totalMs:performance.now()-totalStart,
  adapter,coverageModel:selected,renderer:'Direct WebGPU segment raster + atomic ink-mask score; no SVG and no raster readback'};
}
