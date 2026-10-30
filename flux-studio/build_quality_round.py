"""Build a local, visually blinded pilot; keep the allocation key outside the review page."""
import argparse
import base64
import hashlib
import json
import random
import secrets
import io
from pathlib import Path
from PIL import Image,ImageOps

ROOT = Path(__file__).resolve().parent


def split_groups(groups,rng,strata=None):
    if strata is None:
        rng.shuffle(groups)
        cutoff=max(1,min(len(groups)-1,round(len(groups)*.6)))
        return [(source,candidates,'calibration' if i<cutoff else 'heldout') for i,(source,candidates) in enumerate(groups)]
    buckets={}
    for source,candidates in groups:
        category=strata.get(source.stem.removesuffix('-source'))
        if not isinstance(category,str) or not category.strip():raise ValueError('كل مصدر يحتاج فئة صريحة في تقسيم المعايرة.')
        buckets.setdefault(category,[]).append((source,candidates))
    result=[]
    for category,items in sorted(buckets.items()):
        if len(items)<2:raise ValueError('يلزم مصدران مستقلان على الأقل للفئة: '+category)
        rng.shuffle(items);cutoff=max(1,min(len(items)-1,round(len(items)*.6)))
        result.extend((source,candidates,'calibration' if i<cutoff else 'heldout') for i,(source,candidates) in enumerate(items))
    return result


def build(samples, output, seed=None, include_controls=False,strata=None):
    if (output/'review.html').exists() or (output/'private-allocation-key.json').exists():
        raise ValueError('الجولة موجودة؛ اختر مجلدًا جديدًا لحفظ المفتاح والإجابات القديمة.')
    sources = sorted(samples.glob('*-source.png'))
    groups = []
    for source in sources:
        stem = source.name.removesuffix('-source.png')
        candidates = sorted(samples.glob(stem + '-*-flux.png'))
        if candidates:
            groups.append((source, candidates))
    if len(groups) < 2:
        raise ValueError('يلزم مصدران مستقلان على الأقل لتقسيم الجولة.')
    hashes=[hashlib.sha256(clean_png(source)).hexdigest() for source,_ in groups]
    if len(set(hashes))!=len(hashes):
        raise ValueError('مصدر مكرر ببصمة واحدة؛ وحّد مشتقاته في مجموعة مصدر واحدة.')
    rng = random.Random(seed if seed is not None else secrets.randbits(128))
    allocations=split_groups(groups,rng,strata)
    public, key, source_images = [], [], {}
    for source,candidates,split in allocations:
        source_id=secrets.token_hex(10);source_images[source_id]=data_uri(source)
        records=[(clean_png(candidate),str(candidate.resolve()),'saved-flux') for candidate in candidates]
        if include_controls:
            original=ImageOps.exif_transpose(Image.open(source)).convert('RGB');w,h=original.size
            controls={'identity':original,'crop':original.crop((round(w*.12),round(h*.08),round(w*.92),round(h*.95))).resize((w,h)),
                      'rotation':original.rotate(12,resample=Image.Resampling.BICUBIC,fillcolor='white')}
            for name,image in controls.items():
                stream=io.BytesIO();image.save(stream,format='PNG');records.append((stream.getvalue(),None,'control-'+name))
        for raw,candidate_path,kind in records:
            case_id = secrets.token_hex(10)
            public.append({'id': case_id, 'sourceId':source_id,'candidate':'data:image/png;base64,'+base64.b64encode(raw).decode()})
            key.append({'caseId': case_id, 'sourceGroup': source.stem,
                        'split':split,
                        'sourcePath': str(source.resolve()), 'candidatePath':candidate_path,'candidateKind':kind,
                        'sourceSHA256': hashlib.sha256(clean_png(source)).hexdigest(),
                        'originalSourceFileSHA256':hashlib.sha256(source.read_bytes()).hexdigest(),
                        'candidateSHA256': hashlib.sha256(raw).hexdigest()})
    rng.shuffle(public)
    round_id = secrets.token_hex(12)
    bundle = {'version': 'flux-human-review/1.0', 'roundId': round_id, 'sources':source_images,'cases': public}
    # Output is private local data, never an application static directory.
    output.mkdir(parents=True, exist_ok=True)
    html = (ROOT/'quality-review.html').read_text(encoding='utf-8')
    encoded = base64.b64encode(json.dumps(bundle).encode()).decode()
    html = html.replace('<script>/*ROUND_DATA*/</script><script>/*ROUND_JS*/</script>',
        '<script src="round-data.js"></script><script src="round-ui.js"></script>')
    (output/'round-data.js').write_text(f'window.REVIEW_DATA=JSON.parse(atob("{encoded}"));',encoding='utf-8')
    (output/'round-ui.js').write_text((ROOT/'quality-review.js').read_text(encoding='utf-8'),encoding='utf-8')
    (output/'review.html').write_text(html, encoding='utf-8')
    (output/'private-allocation-key.json').write_text(json.dumps({
        'roundId': round_id, 'pilotOnly': True, 'humanRatings': 'pending',
        'splitUnit': 'source image; derivatives never cross splits','stratified':strata is not None, 'cases': key,
        'limitations': ['Small convenience sample, not a representative validation dataset.',
                        'Reviewers must not inspect the allocation key before submitting ratings.']},
        ensure_ascii=False, indent=2), encoding='utf-8')
    return {'roundId': round_id, 'sources': len(groups), 'cases': len(public),
            'review': str((output/'review.html').resolve()), 'humanRatings': 'pending'}


def data_uri(path):
    return 'data:image/png;base64,' + base64.b64encode(clean_png(path)).decode()


def clean_png(path):
    with Image.open(path) as opened:
        image=ImageOps.exif_transpose(opened).convert('RGBA')
        clean=Image.frombytes('RGBA',image.size,image.tobytes())
        buffer=io.BytesIO();clean.save(buffer,format='PNG')
        return buffer.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--controls',action='store_true')
    parser.add_argument('--strata',type=Path,help='JSON mapping source stems to predeclared applicability strata')
    args = parser.parse_args()
    strata=json.loads(args.strata.read_text(encoding='utf8')) if args.strata else None
    print(json.dumps(build(args.samples, args.output,include_controls=args.controls,strata=strata), ensure_ascii=False))
