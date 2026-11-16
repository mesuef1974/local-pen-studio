import {inkLayout} from './geometry.js';

export const PAPER_SIZES=Object.freeze({A6:[105,148],A5:[148,210],A4:[210,297],A3:[297,420],A2:[420,594],A1:[594,841],A0:[841,1189],B5:[176,250],Letter:[215.9,279.4],Legal:[215.9,355.6],Square:[200,200]});

export function paperLayout(image,settings){
 const named=PAPER_SIZES[settings.paper];
 if(!named&&settings.paper!=='custom')throw Error('اختر مقاس ورق معروفًا أو مقاسًا مخصصًا.');
 let [width,height]=named||[settings.paperWidth,settings.paperHeight];
 const {margin,pen}=settings,percent=settings.drawScale??100;
 for(const value of [width,height,margin,pen,percent,image.width,image.height])if(typeof value!=='number'||!Number.isFinite(value))throw Error('أدخل أبعادًا وأرقامًا صحيحة للورقة والرسم.');
 if(width<20||height<20||width>1200||height>1200)throw Error('أبعاد الورق المخصص من 20 إلى 1200 مم.');
 if(margin<0||margin>100||pen<.1||pen>1.2||percent<10||percent>100||image.width<1||image.height<1)throw Error('راجع الهامش وقطر القلم وحجم الرسم.');
 [width,height]=settings.landscape?[Math.max(width,height),Math.min(width,height)]:[Math.min(width,height),Math.max(width,height)];
 if(Math.min(width,height)<=2*margin+pen)throw Error('الهامش وقطر القلم لا يتركان مساحة رسم؛ قلّل الهامش أو كبّر الورقة.');
 const fitted=inkLayout(image.width,image.height,width,height,margin,pen),scale=fitted.scale*percent/100;
 // This bounded planning range is shared with the server's physical-pen validator.
 if(scale<.005||scale>5)throw Error('حجم الصورة على الورقة خارج مجال التخطيط؛ غيّر حجم الرسم أو دقة الصورة أو مقاس الورقة.');
 return {...fitted,scale,x:(width-(image.width-1)*scale)/2,y:(height-(image.height-1)*scale)/2,
  margin,pen,drawScale:percent,imageWidthMm:image.width*scale,imageHeightMm:image.height*scale,
  usableWidthMm:width-2*margin,usableHeightMm:height-2*margin,sourcePPI:25.4/scale};
}

export function inkBounds(items,mapping,pen){
 if(!items.length)return null;
 let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
 for(const {p} of items)for(const [x,y]of p){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
 return {left:left*mapping.scale+mapping.x-pen/2,right:right*mapping.scale+mapping.x+pen/2,
  top:top*mapping.scale+mapping.y-pen/2,bottom:bottom*mapping.scale+mapping.y+pen/2,
  width:(right-left)*mapping.scale+pen,height:(bottom-top)*mapping.scale+pen};
}
