'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const MAX_PIXELS = 4000000;
  const MAX_BYTES = 5000000;
  let version = 0;

  const asDataUrl = blob => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('تعذر قراءة الملف.'));
    reader.readAsDataURL(blob);
  });

  // Large photos are scaled down here so the server limits are never the user's problem.
  async function readImage(file) {
    const bitmap = await createImageBitmap(file).catch(() => { throw new Error('تعذر قراءة الصورة.'); });
    const scale = Math.min(1, Math.sqrt(MAX_PIXELS / (bitmap.width * bitmap.height)));
    if (scale === 1 && file.size <= MAX_BYTES) { bitmap.close(); return asDataUrl(file); }
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(bitmap.width * scale);
    canvas.height = Math.floor(bitmap.height * scale);
    const context = canvas.getContext('2d');
    context.fillStyle = 'white';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return canvas.toDataURL('image/jpeg', 0.92);
  }

  function reset() {
    version += 1;
    $('stage').hidden = true;
    $('done').hidden = true;
    $('warnings').hidden = true;
    $('download').removeAttribute('href');
    $('status').textContent = 'اضغط «جهّز المعاينة».';
    $('engraveOptions').hidden = $('operation').value !== 'engrave';
    $('acrylicOptions').hidden = $('material').value !== 'acrylic';
  }

  // A changed setting hides the old file, so a stale one cannot be downloaded.
  $('form').addEventListener('input', reset);

  $('form').addEventListener('submit', async event => {
    event.preventDefault();
    reset();
    const current = version;
    const material = $('material').value;
    const operation = $('operation').value;
    const acrylic = material === 'acrylic';
    $('run').disabled = true;
    $('status').textContent = 'جارٍ التجهيز…';
    try {
      const body = {
        image: await readImage($('file').files[0]),
        material,
        operation,
        widthMm: Number($('width').value),
        style: $('style').value,
        brightness: Number($('brightness').value),
        mirror: acrylic && $('mirror').checked,
        invert: acrylic && $('invert').checked,
      };
      const response = await fetch('/api/laser', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'تعذر التجهيز.');
      if (current !== version) return;
      $('preview').src = result.preview;
      $('stage').className = material;
      $('stage').hidden = false;
      $('warnings').replaceChildren(...result.warnings.map(text => Object.assign(document.createElement('li'), {textContent: text})));
      $('warnings').hidden = !result.warnings.length;
      $('download').href = result.file;
      $('download').download = result.name;
      $('size').textContent = `${result.widthMm}×${result.heightMm} مم`;
      $('processHint').textContent = operation === 'engrave'
        ? 'اختر النقش (Engrave)، ولا تضف تنقيطًا أو عكسًا فوق ما في الملف.'
        : 'اختر التعليم على الخط (Score)، لا القطع.';
      $('done').hidden = false;
      $('status').textContent = `جاهز: ${result.widthMm}×${result.heightMm} مم` + (result.paths ? `، ${result.paths} مسارًا` : '');
    } catch (error) {
      if (current === version) $('status').textContent = error.message;
    } finally {
      $('run').disabled = false;
    }
  });
  reset();
  $('status').textContent = 'ارفع صورة ثم اضغط «جهّز المعاينة».';
})();
