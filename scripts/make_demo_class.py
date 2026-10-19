"""
Builds a demo classroom from public face data (LFW):
  demo/enroll/*.jpg     3-4 enrollment photos per student
  demo/students.json    manifest used by the "Load demo class" button
  demo/class_photo.jpg  ONE synthetic class photo made from DIFFERENT photos of those
                        students (+ a few strangers, + some students left out = absent)
  demo/truth.json       ground truth for scripts/evaluate.py

Usage:
  python scripts/make_demo_class.py                 # downloads LFW through scikit-learn (~200 MB, once)
  python scripts/make_demo_class.py --source DIR    # DIR/<person_name>/*.jpg (any dataset, LFW layout)
"""
import argparse, json, os, random, glob
import cv2, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")

def load_lfw(min_faces):
    from sklearn.datasets import fetch_lfw_people
    print("Fetching LFW dataset (first run downloads ~200 MB)...")
    d = fetch_lfw_people(min_faces_per_person=min_faces, color=True, slice_=None, resize=1.0)
    people = {}
    for img, t in zip(d.images, d.target):
        a = np.clip(img, 0, 255).astype(np.uint8)
        people.setdefault(d.target_names[t], []).append(cv2.cvtColor(a, cv2.COLOR_RGB2BGR))
    return people

def load_dir(path, min_faces):
    people = {}
    for p in sorted(os.listdir(path)):
        imgs = [cv2.imread(f) for f in sorted(glob.glob(os.path.join(path, p, "*")))]
        imgs = [i for i in imgs if i is not None]
        if len(imgs) >= min_faces: people[p.replace("_", " ")] = imgs
    return people

def paste(canvas, face, cx, cy, size, rng, blur):
    f = cv2.resize(face, (size, size), interpolation=cv2.INTER_AREA)
    f = cv2.convertScaleAbs(f, alpha=rng.uniform(.8, 1.15), beta=rng.uniform(-15, 15))
    if blur: f = cv2.GaussianBlur(f, (0, 0), blur)
    ang = rng.uniform(-8, 8)
    M = cv2.getRotationMatrix2D((size / 2, size / 2), ang, 1)
    f = cv2.warpAffine(f, M, (size, size), borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros((size, size), np.float32)
    cv2.ellipse(mask, (size // 2, size // 2), (int(size * .47), int(size * .5)), 0, 0, 360, 1, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), size * .06)[..., None]
    x0, y0 = int(cx - size / 2), int(cy - size / 2)
    H, W = canvas.shape[:2]
    if x0 < 0 or y0 < 0 or x0 + size > W or y0 + size > H: return False
    roi = canvas[y0:y0 + size, x0:x0 + size].astype(np.float32)
    canvas[y0:y0 + size, x0:x0 + size] = (f * mask + roi * (1 - mask)).astype(np.uint8)
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source"); ap.add_argument("--students", type=int, default=14)
    ap.add_argument("--absent", type=int, default=2); ap.add_argument("--strangers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed); nrng = np.random.default_rng(a.seed)
    people = load_dir(a.source, 6) if a.source else load_lfw(12)
    names = sorted(people); rng.shuffle(names)
    n_stu = min(a.students, len(names) - a.strangers)
    studs, strangers = names[:n_stu], names[n_stu:n_stu + a.strangers]
    os.makedirs(os.path.join(DEMO, "enroll"), exist_ok=True)
    manifest = []
    for i, n in enumerate(studs):
        imgs = people[n]; files = []
        for k in range(3):
            fn = f"enroll/{i:02d}_{k}.jpg"; cv2.imwrite(os.path.join(DEMO, fn), imgs[k]); files.append(fn)
        manifest.append({"name": n, "roll": str(i + 1), "images": files})
    json.dump(manifest, open(os.path.join(DEMO, "students.json"), "w"), indent=1)

    absent = set(studs[-a.absent:]) if a.absent else set()
    crowd = [(n, people[n][3 + (i % max(1, len(people[n]) - 3))]) for i, n in enumerate(studs) if n not in absent]
    crowd += [(None, people[n][0]) for n in strangers]
    rng.shuffle(crowd)

    W, H = 2400, 1350
    canvas = np.zeros((H, W, 3), np.uint8)
    for y in range(H):  # classroom-ish gradient wall + floor
        t = y / H; canvas[y] = (int(150 - 60 * t), int(165 - 70 * t), int(170 - 90 * t))
    canvas += nrng.integers(0, 12, canvas.shape, dtype=np.uint8)
    rows = 3; per = int(np.ceil(len(crowd) / rows)); truth = []
    k = 0
    for r in range(rows):
        size = [150, 190, 235][r]; yc = [420, 700, 1030][r]
        items = crowd[k:k + per]; k += per
        step = W // (len(items) + 1)
        for j, (n, img) in enumerate(items):
            cx = step * (j + 1) + rng.randint(-25, 25); cy = yc + rng.randint(-30, 30)
            sz = size + rng.randint(-15, 15)
            if paste(canvas, img, cx, cy, sz, rng, blur=[1.4, .9, 0][r] if r < 2 else 0):
                truth.append({"name": n, "cx": cx, "cy": cy, "size": sz})
    cv2.imwrite(os.path.join(DEMO, "class_photo.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    json.dump({"faces": truth, "absent": sorted(absent)}, open(os.path.join(DEMO, "truth.json"), "w"), indent=1)
    print(f"Enrolled set: {len(studs)} students | class photo has {len(truth)} faces "
          f"({len(truth) - a.strangers} students present, {a.strangers} strangers, {len(absent)} absent)")
    print("Next: restart the app, click 'Students' > 'Load demo class', then Attendance > 'Use demo class photo'")

if __name__ == "__main__":
    main()
