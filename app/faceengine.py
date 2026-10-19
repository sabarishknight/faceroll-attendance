"""
Face engine v4.

Detector : SCRFD-10G (InsightFace).  Runs once over the whole photo AND over overlapping zoomed-in tiles,
           so small, blurry back-row faces are found (a single pass loses everything under ~20px).
Recognise: ArcFace R50 (WebFace600K, fast)  +  ArcFace R100 (Glint360K, strongest).
           R50 runs on every face (with a mirrored copy); R100 is added for the faces R50 is unsure about.
All models are ONNX run through onnxruntime (no insightface package, no compiler).
"""
import os
import cv2
import numpy as np
import onnxruntime as ort
from scipy.optimize import linear_sum_assignment

ARC_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)

STRIDES = (8, 16, 32)
MIN_FACE = 10          # px (in the ORIGINAL photo) - below this there is nothing to recognise


def _nms(boxes, scores, thr):
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest]); yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest]); yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1 + 1) * np.maximum(0, yy2 - yy1 + 1)
        # IoU, plus "mostly inside a bigger box" (kills duplicate small boxes sitting on one face)
        ovr = inter / (areas[i] + areas[rest] - inter)
        inside = inter / np.minimum(areas[i], areas[rest])
        order = rest[(ovr <= thr) & (inside < 0.8)]
    return keep


def _prep(a):
    return cv2.dnn.blobFromImage(a, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)


class FaceEngine:
    def __init__(self, model_dir):
        det_path = os.path.join(model_dir, "det_10g.onnx")
        r50 = os.path.join(model_dir, "w600k_r50.onnx")
        r100 = os.path.join(model_dir, "glintr100.onnx")
        for p in (det_path, r50):
            if not os.path.exists(p):
                raise FileNotFoundError(f"{p} missing - run: python scripts/download_models.py")
        so = ort.SessionOptions()
        so.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(det_path, so, providers=prov)
        self.rec = ort.InferenceSession(r50, so, providers=prov)
        self.rec2 = ort.InferenceSession(r100, so, providers=prov) if os.path.exists(r100) else None
        self.det_in = self.det.get_inputs()[0].name
        self.rec_in = self.rec.get_inputs()[0].name
        self.rec2_in = self.rec2.get_inputs()[0].name if self.rec2 else None
        self._anchor_cache = {}

    # ---------------------------------------------------------------- detect
    def _centers(self, h, w, stride):
        key = (h, w, stride)
        if key not in self._anchor_cache:
            g = np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32)
            c = (g * stride).reshape(-1, 2)
            c = np.stack([c] * 2, axis=1).reshape(-1, 2)  # 2 anchors / cell
            self._anchor_cache[key] = c
        return self._anchor_cache[key]

    def _detect_at(self, img, det_size, thr):
        h, w = img.shape[:2]
        scale = det_size / max(h, w)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        canvas = np.zeros((det_size, det_size, 3), np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        blob = cv2.dnn.blobFromImage(canvas, 1 / 128.0, (det_size, det_size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.det.run(None, {self.det_in: blob})
        B, S, K = [], [], []
        for i, stride in enumerate(STRIDES):
            scores = outs[i][:, 0]
            bbox = outs[i + 3] * stride
            kps = outs[i + 6] * stride
            c = self._centers(det_size // stride, det_size // stride, stride)
            idx = np.where(scores >= thr)[0]
            if idx.size == 0:
                continue
            c, bbox, kps = c[idx], bbox[idx], kps[idx]
            boxes = np.stack([c[:, 0] - bbox[:, 0], c[:, 1] - bbox[:, 1],
                              c[:, 0] + bbox[:, 2], c[:, 1] + bbox[:, 3]], 1)
            kp = kps.reshape(-1, 5, 2) + c[:, None, :]
            B.append(boxes); S.append(scores[idx]); K.append(kp)
        if not B:
            return np.zeros((0, 4)), np.zeros(0), np.zeros((0, 5, 2))
        return (np.concatenate(B) / scale, np.concatenate(S), np.concatenate(K) / scale)

    def _finish(self, b, sc, k, shape, scale=1.0, nms_thr=0.4, min_face=MIN_FACE):
        if len(b) == 0:
            return []
        keep = _nms(b, sc, nms_thr)
        H, W = shape[:2]
        faces = []
        for i in keep:
            box = (b[i] / scale).copy()
            kp = k[i] / scale
            box[[0, 2]] = box[[0, 2]].clip(0, W - 1)
            box[[1, 3]] = box[[1, 3]].clip(0, H - 1)
            if (box[2] - box[0]) < min_face or (box[3] - box[1]) < min_face:
                continue
            faces.append({"bbox": box, "score": float(sc[i]), "kps": kp})
        faces.sort(key=lambda f: -(f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
        return faces

    def detect(self, img, sizes=(640,), thr=0.5, nms_thr=0.4):
        """Plain multi-scale detection (used for the live scan frames)."""
        allb, alls, allk = [], [], []
        for s in sizes:
            b, sc, k = self._detect_at(img, s, thr)
            allb.append(b); alls.append(sc); allk.append(k)
        return self._finish(np.concatenate(allb), np.concatenate(alls), np.concatenate(allk), img.shape, 1.0, nms_thr)

    def detect_group(self, img, thr=0.38, work_long=3600, max_long=5200, tile=640, stride=432, progress=None, info=None):
        """Best-effort detection for a class photo.
        1. work image: small photos are enlarged (cubic) so tiny faces reach the detector's sweet spot,
           huge photos are capped (speed).
        2. full-image pass at two scales   +   3. overlapping 640px tiles over the work image.
        Everything is merged with NMS and mapped back to original coordinates."""
        H, W = img.shape[:2]
        long_ = max(H, W)
        s = 1.0
        if long_ < work_long:
            s = min(work_long / long_, 2.5)
        elif long_ > max_long:
            s = max_long / long_
        work = img if abs(s - 1) < 1e-3 else cv2.resize(
            img, (int(round(W * s)), int(round(H * s))), interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
        wh, ww = work.shape[:2]
        allb, alls, allk = [], [], []

        def add(b, sc, k, ox=0, oy=0):
            if len(b):
                b = b.copy(); k = k.copy()
                b[:, [0, 2]] += ox; b[:, [1, 3]] += oy
                k[:, :, 0] += ox; k[:, :, 1] += oy
                allb.append(b); alls.append(sc); allk.append(k)

        n_full = 0
        for ds in (1280, 2560):
            add(*self._detect_at(work, ds, thr))
        n_full = sum(len(x) for x in alls)
        xs = list(range(0, max(1, ww - tile) + 1, stride)) or [0]
        ys = list(range(0, max(1, wh - tile) + 1, stride)) or [0]
        if xs[-1] + tile < ww: xs.append(ww - tile)
        if ys[-1] + tile < wh: ys.append(wh - tile)
        total = len(xs) * len(ys); done = 0
        for y in ys:
            for x in xs:
                t = work[y:y + tile, x:x + tile]
                if t.size and t.shape[0] >= 64 and t.shape[1] >= 64:
                    add(*self._detect_at(t, tile, thr), ox=x, oy=y)
                done += 1
                if progress: progress(done, total)
        if info is not None:
            info.update(work=(ww, wh), scale=round(s, 2), tiles=total, full_pass=n_full)
        if not allb:
            return []
        faces = self._finish(np.concatenate(allb), np.concatenate(alls), np.concatenate(allk), (wh, ww), 1.0, 0.4,
                             min_face=MIN_FACE * s)
        return self._to_orig(faces, s, (H, W))

    @staticmethod
    def _to_orig(faces, s, shape):
        H, W = shape
        out = []
        for f in faces:
            b = f["bbox"] / s
            b[[0, 2]] = b[[0, 2]].clip(0, W - 1); b[[1, 3]] = b[[1, 3]].clip(0, H - 1)
            out.append({"bbox": b, "score": f["score"], "kps": f["kps"] / s})
        return out

    # ------------------------------------------------------------- recognize
    @staticmethod
    def align(img, kps, size=112):
        kps = kps.astype(np.float32)
        M, _ = cv2.estimateAffinePartial2D(kps, ARC_TEMPLATE, method=cv2.LMEDS)
        if M is None:
            return None
        sc = float(np.hypot(M[0, 0], M[1, 0]))
        if sc < 0.5:   # big face: shrink with area averaging first (a plain warp would alias)
            pad = 1.2 * (kps[:, 0].max() - kps[:, 0].min())
            x1 = int(max(0, kps[:, 0].min() - pad)); x2 = int(min(img.shape[1], kps[:, 0].max() + pad))
            y1 = int(max(0, kps[:, 1].min() - pad)); y2 = int(min(img.shape[0], kps[:, 1].max() + pad))
            roi = img[y1:y2, x1:x2]
            f = min(1.0, sc * 2)
            roi = cv2.resize(roi, (max(1, int(roi.shape[1] * f)), max(1, int(roi.shape[0] * f))), interpolation=cv2.INTER_AREA)
            k2 = (kps - np.array([x1, y1], np.float32)) * f
            M, _ = cv2.estimateAffinePartial2D(k2, ARC_TEMPLATE, method=cv2.LMEDS)
            if M is None:
                return None
            return cv2.warpAffine(roi, M, (size, size), flags=cv2.INTER_AREA, borderValue=0.0)
        return cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_CUBIC if sc > 1.3 else cv2.INTER_LINEAR, borderValue=0.0)

    @staticmethod
    def blur_score(a):
        return float(cv2.Laplacian(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    @staticmethod
    def degrade(a, rng=None):
        """Simulate a far-away, soft class-photo face from a sharp close-up crop."""
        r = (rng or np.random).uniform(0.22, 0.38)
        n = max(16, int(112 * r))
        d = cv2.resize(a, (n, n), interpolation=cv2.INTER_AREA)
        d = cv2.GaussianBlur(d, (0, 0), 0.6)
        return cv2.resize(d, (112, 112), interpolation=cv2.INTER_CUBIC)

    def _run(self, sess, name, crops, bs=32):
        out = []
        for i in range(0, len(crops), bs):
            blob = np.concatenate([_prep(c) for c in crops[i:i + bs]], 0)
            e = sess.run(None, {name: blob})[0]
            out.append(e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9))
        return np.concatenate(out).astype(np.float32) if out else np.zeros((0, 512), np.float32)

    def embed_crops(self, crops, flip=True):
        """R50 embeddings of already-aligned 112px crops. flip -> average with the mirrored crop."""
        if not crops:
            return np.zeros((0, 512), np.float32)
        e = self._run(self.rec, self.rec_in, crops)
        if flip:
            e2 = self._run(self.rec, self.rec_in, [c[:, ::-1] for c in crops])
            e = e + e2
            e /= (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9)
        return e.astype(np.float32)

    def embed_crops_r100(self, crops):
        if not crops or self.rec2 is None:
            return np.zeros((0, 512), np.float32)
        return self._run(self.rec2, self.rec2_in, crops)

    def embed(self, img, kps):
        """Single face, R50 only (kept for simple callers). -> (emb, blur)"""
        a = self.align(img, kps)
        if a is None:
            return None, 0.0
        return self.embed_crops([a], flip=False)[0], self.blur_score(a)

    @staticmethod
    def yaw_ratio(kps):
        """~0 = frontal, magnitude grows as the head turns (sign = direction in image)."""
        eye_l, eye_r, nose = kps[0], kps[1], kps[2]
        eye_dist = np.linalg.norm(eye_r - eye_l) + 1e-6
        return float((nose[0] - (eye_l[0] + eye_r[0]) / 2) / eye_dist)

    @staticmethod
    def pitch_ratio(kps):
        """nose position between eye-line and mouth-line (~0.5-0.6 frontal; moves when the chin goes up/down)."""
        eye_y = (kps[0][1] + kps[1][1]) / 2
        mouth_y = (kps[3][1] + kps[4][1]) / 2
        return float((kps[2][1] - eye_y) / (mouth_y - eye_y + 1e-6))


# ------------------------------------------------------------------ matching
def _topk_mean(P, G, k):
    s = P @ G.T
    k = min(k, s.shape[1])
    return np.sort(s, axis=1)[:, -k:].mean(axis=1)


def similarity_matrix(face_embs, gallery, topk=3, face_embs2=None):
    """face_embs (F,512) R50 probes; gallery: list of (id, A(K,512), B(K2,512)|None).
    face_embs2 (F,512) R100 probes, rows of NaN/zero = not computed.
    Per student: score = mean of top-k cosines.  When both the probe and the student have R100 data the final
    score is the average of the R50 score and the R100 score."""
    F, S = len(face_embs), len(gallery)
    sim = np.zeros((F, S), np.float32)
    has2 = None
    if face_embs2 is not None:
        has2 = np.abs(face_embs2).sum(1) > 0
    for j, item in enumerate(gallery):
        A = item[1]; B = item[2] if len(item) > 2 else None
        s = _topk_mean(face_embs, A, topk)
        if B is not None and len(B) and has2 is not None:
            s2 = _topk_mean(face_embs2, B, topk)
            s = np.where(has2, (s + s2) / 2, s)
        sim[:, j] = s
    return sim


def assign(sim, thr):
    """One face <-> at most one student (Hungarian). Returns {face_idx: student_idx}."""
    if sim.size == 0:
        return {}
    r, c = linear_sum_assignment(-sim)
    return {int(i): int(j) for i, j in zip(r, c) if sim[i, j] >= thr}
