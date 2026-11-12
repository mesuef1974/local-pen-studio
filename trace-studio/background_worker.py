"""Use the installed local BiRefNet weights; keep real alpha, never compose on white."""
import json,sys
from pathlib import Path
DRAW=Path(__file__).resolve().parent.parent/'drawing-simulator'
sys.path.insert(0,str(DRAW))
from background_service import run

def main():
    print(json.dumps(run(json.load(sys.stdin),transparent=True,device='cuda')))

if __name__=='__main__':
    try:main()
    except ValueError as error:print(json.dumps({'error':str(error)},ensure_ascii=False));sys.exit(2)
    except Exception:print(json.dumps({'error':'تعذرت إزالة الخلفية على كرت NVIDIA. أغلق البرامج التي تستهلك ذاكرة الكرت ثم أعد المحاولة؛ لم يُستخدم المعالج بديلًا.'},ensure_ascii=False));sys.exit(1)
