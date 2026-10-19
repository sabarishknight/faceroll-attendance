"""Scores the engine on the demo class photo using demo/truth.json."""
import json, os, sys
import cv2, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
from faceengine import FaceEngine, similarity_matrix, assign

DEMO = os.path.join(ROOT, "demo")
eng = FaceEngine(os.path.join(ROOT, "models"))
man = json.load(open(os.path.join(DEMO, "students.json")))
gal = []
for s in man:
    es = []
    for fn in s["images"]:
        im = cv2.imread(os.path.join(DEMO, fn)); fs = eng.detect(im, (640,), thr=.5)
        if fs: es.append(eng.embed(im, fs[0]["kps"])[0])
    gal.append((s["name"], np.stack(es)))
truth = json.load(open(os.path.join(DEMO, "truth.json")))["faces"]
img = cv2.imread(os.path.join(DEMO, "class_photo.jpg"))
faces = eng.detect(img, (1024, 1920), thr=.45)
embs = np.stack([eng.embed(img, f["kps"])[0] for f in faces])
sim = similarity_matrix(embs, gal)
thr = float(sys.argv[1]) if len(sys.argv) > 1 else 0.38
m = assign(sim, thr)
found = ok_id = wrong = stranger_acc = n_known = n_str = 0
for t in truth:
    d = [np.hypot((f["bbox"][0] + f["bbox"][2]) / 2 - t["cx"], (f["bbox"][1] + f["bbox"][3]) / 2 - t["cy"]) for f in faces]
    i = int(np.argmin(d)) if d else -1
    if i < 0 or d[i] > t["size"] * .5: 
        print("MISSED detection:", t["name"]); 
        if t["name"]: n_known += 1
        else: n_str += 1
        continue
    pred = gal[m[i]][0] if i in m else None
    if t["name"]:
        n_known += 1; found += 1
        if pred == t["name"]: ok_id += 1
        elif pred: wrong += 1; print("WRONG:", t["name"], "->", pred)
        else: print("not recognised:", t["name"], round(float(sim[i].max()), 2))
    else:
        n_str += 1; found += 1
        if pred: stranger_acc += 1; print("STRANGER accepted as", pred)
print(f"\nThreshold {thr}\nFaces detected      : {found}/{n_known + n_str}\n"
      f"Students identified : {ok_id}/{n_known}\nWrong identity      : {wrong}\nStrangers accepted  : {stranger_acc}/{n_str}")
