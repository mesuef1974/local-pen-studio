import {requestJson as api} from './api-client.js';

let gpuContext;

async function context(){
 if(!navigator.gpu)throw new Error('هذا المتصفح لا يوفّر WebGPU. ألغِ الخيار التجريبي لاستخدام التدقيق المعتاد.');
 if(gpuContext)return gpuContext;
 const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'});
 if(!adapter)throw new Error('لم يعثر المتصفح على محول WebGPU صالح.');
 const device=await adapter.requestDevice();
 const shader=device.createShaderModule({code:`
  @group(0) @binding(0) var actualTex:texture_2d<f32>;
  @group(0) @binding(1) var<storage,read> targetBits:array<u32>;
  @group(0) @binding(2) var<storage,read_write> counts:array<atomic<u32>>;
  @compute @workgroup_size(16,16) fn main(@builtin(global_invocation_id) id:vec3<u32>){
   let dims=textureDimensions(actualTex);if(id.x>=dims.x||id.y>=dims.y){return;}
   let index=id.y*dims.x+id.x;let expected=(targetBits[index/32u]&(1u<<(index%32u)))!=0u;
   let pixel=textureLoad(actualTex,vec2<i32>(id.xy),0);let actual=pixel.r<0.5;
   if(expected){atomicAdd(&counts[1],1u);}if(actual){atomicAdd(&counts[2],1u);}
   if(expected&&actual){atomicAdd(&counts[0],1u);}
  }`});
 const pipeline=await device.createComputePipelineAsync({layout:'auto',compute:{module:shader,entryPoint:'main'}});
 const info=adapter.info||{};gpuContext={device,pipeline,adapter:{vendor:info.vendor||'',architecture:info.architecture||'',device:info.device||'',description:info.description||''}};
 return gpuContext;
}

function svgFor(paths,width,height,penPixels,pad,upscale){
 const pathData=paths.map(path=>'<path d="'+path.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(6)},${y.toFixed(6)}`).join(' ')+'"/>').join('');
 return `<svg xmlns="http://www.w3.org/2000/svg" width="${(width+2*pad)*upscale}" height="${(height+2*pad)*upscale}" viewBox="${-pad-.5} ${-pad-.5} ${width+2*pad} ${height+2*pad}"><rect x="${-pad-.5}" y="${-pad-.5}" width="${width+2*pad}" height="${height+2*pad}" fill="white"/><g fill="none" stroke="black" stroke-width="${penPixels.toFixed(9)}" stroke-linecap="round" stroke-linejoin="round">${pathData}</g></svg>`;
}

export async function auditWebGPU({image,paths,mmPerPixel,penMm,inkThreshold,canvas}){
 const source={image,paths,mmPerPixel,penMm,inkThreshold};
 const target=await api('/api/path-audit-target',source);
 const {device,pipeline,adapter}=await context();
 const packed=Uint8Array.from(atob(target.bitsBase64),char=>char.charCodeAt(0));
 const mask=device.createBuffer({size:packed.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
 device.queue.writeBuffer(mask,0,packed);
 const width=target.width,height=target.height;
 const penPixels=penMm/mmPerPixel;
 const svg=svgFor(paths,target.sourceWidth,target.sourceHeight,penPixels,Math.max(3,Math.ceil(penPixels)+2),target.auditUpscale);
 const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'})),imageElement=new Image();
 try{imageElement.src=url;await imageElement.decode();}finally{URL.revokeObjectURL(url);}
 const raster=new OffscreenCanvas(width,height),ctx=raster.getContext('2d');
 ctx.fillStyle='white';ctx.fillRect(0,0,width,height);ctx.drawImage(imageElement,0,0,width,height);
 canvas.width=width;canvas.height=height;canvas.getContext('2d').drawImage(raster,0,0);
 const texture=device.createTexture({size:[width,height],format:'rgba8unorm',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.RENDER_ATTACHMENT});
 const rendered=await createImageBitmap(raster);
 device.queue.copyExternalImageToTexture({source:rendered},{texture},{width,height});rendered.close();
 const counts=device.createBuffer({size:16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
 const result=device.createBuffer({size:16,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
 const group=device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:[{binding:0,resource:texture.createView()},{binding:1,resource:{buffer:mask}},{binding:2,resource:{buffer:counts}}]});
 device.queue.writeBuffer(counts,0,new Uint32Array(4));const encoder=device.createCommandEncoder(),pass=encoder.beginComputePass();
 pass.setPipeline(pipeline);pass.setBindGroup(0,group);pass.dispatchWorkgroups(Math.ceil(width/16),Math.ceil(height/16));pass.end();
 encoder.copyBufferToBuffer(counts,0,result,0,16);device.queue.submit([encoder.finish()]);await result.mapAsync(GPUMapMode.READ);
 const [both,expected,drawn]=Array.from(new Uint32Array(result.getMappedRange().slice(0)));result.unmap();
 texture.destroy();mask.destroy();counts.destroy();result.destroy();
 const union=both+(expected-both)+(drawn-both);
 const metrics={inkIoU:union?100*both/union:100,inkRecall:expected?100*both/expected:100,
  inkPrecision:drawn?100*both/drawn:(expected?0:100),missingInkPercent:expected?100*(expected-both)/expected:0,
  extraInkPercent:drawn?100*(drawn-both)/drawn:0,coloredPixelsPercent:target.coloredPixelsPercent,
  penMm:target.penMm,mmPerPixel:target.mmPerPixel,auditUpscale:target.auditUpscale,
  auditIncludesOutsideImage:true,scope:'WebGPU ink-mask score; source threshold and reference mask prepared locally on CPU.',
  renderer:'Browser SVG raster + WebGPU mask comparison',webgpuAdapter:adapter,
  targetBitsBytes:packed.byteLength,readbackBytes:16,grayErrorInkRegion:null,
  missingInkPercentRounded:(expected?100*(expected-both)/expected:0).toFixed(2),extraInkPercentRounded:(drawn?100*(drawn-both)/drawn:0).toFixed(2)};
 return metrics;
}
