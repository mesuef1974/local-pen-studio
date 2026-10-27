// Uses the exact ordering, physical paper mapping and timing implementation of the app.
import {readFileSync,writeFileSync} from 'node:fs';
import * as geometry from './geometry.js';
const [inputFile,outputPrefix]=process.argv.slice(2),input=JSON.parse(readFileSync(inputFile,'utf8'));
const mapping=geometry.layout(input.width,input.height,210,297,15);
const items=geometry.order(input.paths,new Set(),'nearest',0,mapping.scale);
const timeline=geometry.timeline(items,mapping.scale,30,80,.4);
const lengths=items.map(({p})=>geometry.length(p)*mapping.scale);
const metrics={count:timeline.count,seconds:timeline.seconds,inkMm:timeline.ink,travelMm:timeline.movement,
 points:items.reduce((sum,{p})=>sum+p.length,0),shortUnder2mm:lengths.filter(n=>n<2).length,
 meanStrokeMm:lengths.length?timeline.ink/lengths.length:0,
 liftSeconds:timeline.count*.4,drawSeconds:timeline.ink/30,travelSeconds:timeline.movement/80,
 mapping,paper:'A4 portrait',marginMm:15,penMm:.3,drawSpeed:30,travelSpeed:80,lift:.4};
writeFileSync(outputPrefix+'.svg',geometry.svg(items,mapping,.3));
writeFileSync(outputPrefix+'-metrics.json',JSON.stringify(metrics,null,2));
console.log(JSON.stringify(metrics));
