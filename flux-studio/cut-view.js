// What the cut page says about a built piece. Pure, so it is testable without a browser.
export function describe(piece){
 const warnings=[];
 if(piece.pieces!==1)warnings.push(`القطعة ليست واحدة (${piece.pieces} أجزاء)؛ لا تقصّها.`);
 if(piece.weakParts>0)warnings.push(`أجزاء ضعيفة التثبيت: ${piece.weakParts}. كبّر المقاس أو غيّر الخط.`);
 if(Math.max(piece.widthMm,piece.heightMm)<100)warnings.push('المقاس صغير؛ قد تنكسر الأجزاء الدقيقة.');
 return {facts:`المقاس ${piece.widthMm}×${piece.heightMm} مم · الفتحات ${piece.holes}`,warnings};
}

// A file name that keeps the Arabic name and drops what Windows refuses.
export function fileName(name,mirrored){
 const safe=name.trim().replace(/[\\/:*?"<>|.]+/g,'').replace(/\s+/g,'-')||'cut';
 return `${safe}${mirrored?'-mirrored':''}.svg`;
}
