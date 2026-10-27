import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import * as geo from './geometry.js';
const root=path.join(path.dirname(fileURLToPath(import.meta.url)),'fidelity-review');
const rows=JSON.parse(fs.readFileSync(path.join(root,'audit.json'),'utf8'));
for(const row of rows){
 const output=JSON.parse(fs.readFileSync(path.join(root,row.key+'-paths.json'),'utf8'));
 const mapping=geo.inkLayout(row.width,row.height,210,297,15,row.penMm);
 if(Math.abs(mapping.scale-row.mmPerPixel)>1e-12)throw Error('mapping changed');
 const items=geo.order(output.paths),timeline=geo.timeline(items,mapping.scale,30,80,.4);
 const svg=geo.svg(items,mapping,row.penMm);
 fs.writeFileSync(path.join(root,row.key+'.svg'),svg);
 const old=JSON.parse(fs.readFileSync(path.join(root,'../comparison-review',row.key+'-via-precise-paths.json'),'utf8')); const oldMotion=geo.timeline(geo.order(old.paths),mapping.scale,30,80,.4); row.oldMotion={count:oldMotion.count,seconds:oldMotion.seconds,inkMm:oldMotion.ink,travelMm:oldMotion.movement};
 row.motion={count:timeline.count,seconds:timeline.seconds,inkMm:timeline.ink,travelMm:timeline.movement,mapping,drawSpeed:30,travelSpeed:80,lift:.4};
 for(const {p} of items)for(const [x,y]of p){const px=x*mapping.scale+mapping.x,py=y*mapping.scale+mapping.y,r=row.penMm/2;if(px-r<15-1e-8||px+r>195+1e-8||py-r<15-1e-8||py+r>282+1e-8)throw Error('pen outside margins');}
 if(svg.includes('<image')||svg.includes('fill="black"'))throw Error('raster or fake shape in export');
}
fs.writeFileSync(path.join(root,'audit.json'),JSON.stringify(rows,null,2));
console.log(`${rows.length} physical SVG exports verified: all selected paths, fixed pen, real margins, motion timing.`);
