"""Package a blinded round for manual offline opening; exclude the private key."""
import argparse
from pathlib import Path


def export(round_directory,destination):
    html=(round_directory/'review.html').read_text(encoding='utf8')
    data=(round_directory/'round-data.js').read_text(encoding='utf8')
    ui=(round_directory/'round-ui.js').read_text(encoding='utf8')
    references='<script src="round-data.js"></script><script src="round-ui.js"></script>'
    if html.count(references)!=1:raise ValueError('صيغة الجولة غير متوقعة؛ لم تُكتب نسخة جديدة.')
    # The payload is base64 JSON. Escape closing script tokens defensively in code.
    bundled=html.replace(references,'<script>'+data.replace('</script','<\\/script')+'</script><script>'+ui.replace('</script','<\\/script')+'</script>')
    with destination.open('x',encoding='utf8',newline='\n') as target:target.write(bundled)
    return {'path':str(destination.resolve()),'bytes':destination.stat().st_size,'privateAllocationKeyIncluded':False}


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser();parser.add_argument('--round',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(export(args.round,args.output),ensure_ascii=False))
