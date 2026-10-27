"""Convert the installed BiRefNet ONNX to mixed FP16 locally; no model downloads."""
import hashlib,json,time,warnings
from pathlib import Path
import onnx
from onnxconverter_common import float16

ROOT=Path(__file__).resolve().parent
DIRECTORY=ROOT/'models/background/models/birefnet-general'
SOURCE=DIRECTORY/'birefnet-general.onnx'
TARGET=DIRECTORY/'birefnet-general-fp16.onnx'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

if __name__=='__main__':
    if TARGET.exists():raise SystemExit('FP16 file already exists; source not modified.')
    started=time.perf_counter()
    model=onnx.load(str(SOURCE))
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        model=float16.convert_float_to_float16(model,keep_io_types=True)
    onnx.checker.check_model(model)
    onnx.save(model,str(TARGET))
    metadata={'sourceSha256':digest(SOURCE),'fp16Sha256':digest(TARGET),'sourceBytes':SOURCE.stat().st_size,'fp16Bytes':TARGET.stat().st_size,'conversionSeconds':round(time.perf_counter()-started,2)}
    metadata['conversionWarningCount']=len(recorded)
    (DIRECTORY/'fp16-conversion-warnings.txt').write_text('\n'.join(str(item.message) for item in recorded),encoding='utf-8')
    (DIRECTORY/'fp16-conversion.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps(metadata))
