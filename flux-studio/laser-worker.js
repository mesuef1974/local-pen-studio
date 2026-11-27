import {laserSvg} from './laser-export.js';
onmessage=({data:{items,mapping,options}})=>{try{postMessage(laserSvg(items,mapping,options));}catch(e){postMessage({error:e.message});}};
