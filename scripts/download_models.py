"""Downloads the InsightFace models -> models/
   buffalo_l   : SCRFD-10G face detector + ArcFace R50 (fast recogniser)
   antelopev2 : ArcFace R100 / Glint360K (strongest recogniser, used as a second opinion)
"""
import os, sys, urllib.request, zipfile, tempfile

BASE = "https://github.com/deepinsight/insightface/releases/download/v0.7/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models")
PACKS = {"buffalo_l.zip": ["det_10g.onnx", "w600k_r50.onnx"],
         "antelopev2.zip": ["glintr100.onnx"]}

def fetch(pack, names):
    tmp = os.path.join(tempfile.gettempdir(), pack)
    print(f"Downloading {pack} ...")
    def hook(b, bs, total):
        if total > 0:
            sys.stdout.write(f"\r  {min(100, b*bs*100//total)}%"); sys.stdout.flush()
    urllib.request.urlretrieve(BASE + pack, tmp, hook)
    print()
    with zipfile.ZipFile(tmp) as z:
        for n in names:
            member = next(m for m in z.namelist() if m.endswith("/" + n) or m == n)
            with z.open(member) as src, open(os.path.join(OUT, n), "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk: break
                    dst.write(chunk)
    os.remove(tmp)

def main():
    os.makedirs(OUT, exist_ok=True)
    for pack, names in PACKS.items():
        if all(os.path.exists(os.path.join(OUT, n)) for n in names):
            continue
        fetch(pack, names)
    print("Models ready in", OUT)

if __name__ == "__main__":
    main()
