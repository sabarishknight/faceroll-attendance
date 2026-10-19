"""
Storage. Two interchangeable backends (local JSON files for the laptop demo, Firestore for the cloud)
behind one small document API, plus `Repo` with the app's data model:

classes/{cid}                         {name, created}
classes/{cid}/students/{sid}          {name, roll, order, emb(bytes), thumb(bytes), scanned_at}
classes/{cid}/sessions/{id}           {date, slots[hour ints], marks{sid: hours_attended}, photos[pid], created, updated}
classes/{cid}/photos/{pid}            {data(bytes), w, h, faces[{bbox,sid,sim,status}]}
"""
import base64, json, os, re, shutil, threading, time, uuid
from datetime import datetime
import numpy as np


# ----------------------------------------------------------------- backends
def _enc(o):
    if isinstance(o, (bytes, bytearray)):
        return {"__b": base64.b64encode(bytes(o)).decode()}
    raise TypeError(type(o))


def _dec(d):
    if isinstance(d, dict):
        if set(d) == {"__b"}:
            return base64.b64decode(d["__b"])
        return {k: _dec(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_dec(x) for x in d]
    return d


class LocalBackend:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.lock = threading.RLock()

    def _dir(self, coll):
        return os.path.join(self.root, *coll.split("/"))

    def get(self, coll, id):
        p = os.path.join(self._dir(coll), id + ".json")
        if not os.path.exists(p):
            return None
        with self.lock:
            return _dec(json.load(open(p)))

    def set(self, coll, id, data):
        d = self._dir(coll)
        os.makedirs(d, exist_ok=True)
        with self.lock:
            json.dump(data, open(os.path.join(d, id + ".json"), "w"), default=_enc)

    def delete(self, coll, id):
        try:
            os.remove(os.path.join(self._dir(coll), id + ".json"))
        except FileNotFoundError:
            pass

    def list(self, coll, fields=None):
        d = self._dir(coll)
        if not os.path.isdir(d):
            return []
        out = []
        with self.lock:
            for f in os.listdir(d):
                if f.endswith(".json"):
                    x = _dec(json.load(open(os.path.join(d, f))))
                    if fields is not None:
                        x = {k: v for k, v in x.items() if k in fields}
                    out.append((f[:-5], x))
        return out

    def delete_collection(self, coll):
        shutil.rmtree(self._dir(coll), ignore_errors=True)


class FirestoreBackend:
    TTL = 20  # seconds; keeps free-tier read counts low

    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client()
        self.cache = {}
        self.lock = threading.Lock()

    def _inval(self, coll):
        with self.lock:
            for k in [k for k in self.cache if k[0] == coll]:
                self.cache.pop(k, None)

    def get(self, coll, id):
        d = self.db.collection(coll).document(id).get()
        return d.to_dict() if d.exists else None

    def set(self, coll, id, data):
        self.db.collection(coll).document(id).set(data)
        self._inval(coll)

    def delete(self, coll, id):
        self.db.collection(coll).document(id).delete()
        self._inval(coll)

    def list(self, coll, fields=None):
        key = (coll, tuple(sorted(fields)) if fields is not None else None)
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < self.TTL:
            return hit[1]
        q = self.db.collection(coll)
        if fields is not None:
            q = q.select(list(fields))
        rows = [(d.id, d.to_dict()) for d in q.stream()]
        with self.lock:
            self.cache[key] = (time.time(), rows)
        return rows

    def delete_collection(self, coll):
        for d in self.db.collection(coll).stream():
            d.reference.delete()
        self._inval(coll)


def make_backend(data_dir):
    if os.environ.get("STORE", "local") == "firestore":
        return FirestoreBackend()
    return LocalBackend(data_dir)


# ------------------------------------------------------- legacy (older version) data
def _vecs(v):
    """Pull 512-d float vectors out of whatever an older version stored (bytes / list / list-of-lists / dict)."""
    try:
        if isinstance(v, (bytes, bytearray)):
            a = np.frombuffer(bytes(v), dtype=np.float32)
            return a.reshape(-1, 512) if a.size and a.size % 512 == 0 else None
        if isinstance(v, dict):
            parts = [x for x in (_vecs(y) for y in v.values()) if x is not None]
            return np.concatenate(parts) if parts else None
        if isinstance(v, (list, tuple)) and v:
            if isinstance(v[0], (list, tuple, dict, bytes)):
                parts = [x for x in (_vecs(y) for y in v) if x is not None]
                return np.concatenate(parts) if parts else None
            a = np.asarray(v, dtype=np.float32)
            return a.reshape(-1, 512) if a.size and a.size % 512 == 0 else None
    except Exception:
        return None
    return None


def _first(d, names):
    for n in names:
        if d.get(n) not in (None, ""):
            return d[n]
    return None


def _jpeg_bytes(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if isinstance(v, str) and "," in v[:80]:
        try:
            return base64.b64decode(v.split(",", 1)[1])
        except Exception:
            return None
    return None


_SKIP_SUB = {"students", "sessions", "photos"}


def find_legacy(repo):
    """Walk Firestore for documents that carry face embeddings but are NOT in the current layout.
    Returns [{path, docs, with_faces, names:[...]}]."""
    db = getattr(repo.be, "db", None)
    if db is None:
        return []
    found = {}

    def check(doc, path):
        d = doc.to_dict() or {}
        if any(_vecs(v) is not None for v in d.values()):
            g = found.setdefault(path, {"path": path, "docs": 0, "with_faces": 0, "names": []})
            g["docs"] += 1; g["with_faces"] += 1
            nm = _first(d, ("name", "student_name", "full_name", "label", "student"))
            if nm and len(g["names"]) < 6:
                g["names"].append(str(nm))

    for coll in db.collections():
        if coll.id in ("settings",):
            continue
        for doc in coll.stream():
            if coll.id == "classes":
                for sub in doc.reference.collections():
                    if sub.id in _SKIP_SUB:
                        continue
                    for sd in sub.stream():
                        check(sd, f"classes/{doc.id}/{sub.id}")
                continue
            check(doc, coll.id)
            for sub in doc.reference.collections():
                for sd in sub.stream():
                    check(sd, f"{coll.id}/{doc.id}/{sub.id}")
    return list(found.values())


def import_legacy(repo, path, cid):
    db = getattr(repo.be, "db", None)
    if db is None:
        return 0, 0
    parts = path.split("/")
    if len(parts) % 2 == 0 or parts[0] in ("settings",) or (parts[0] == "classes" and len(parts) > 1 and parts[2:3] and parts[2] in _SKIP_SUB):
        raise ValueError("bad path")
    existing = {(s["roll"], s["name"].lower()): s["id"] for s in repo.students(cid)}
    made = updated = 0
    base = int(time.time() * 1000)
    for i, doc in enumerate(db.collection(path).stream()):
        d = doc.to_dict() or {}
        vec = None
        for v in d.values():
            vec = _vecs(v)
            if vec is not None:
                break
        if vec is None:
            continue
        name = str(_first(d, ("name", "student_name", "full_name", "label", "student")) or doc.id)[:80]
        roll = str(_first(d, ("roll", "roll_no", "rollno", "roll_number", "reg_no", "regno", "id_no")) or "")[:30]
        norm = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
        thumb = None
        for k in ("thumb", "thumbnail", "photo", "image", "face", "avatar"):
            thumb = _jpeg_bytes(d.get(k))
            if thumb:
                break
        sid = existing.get((roll, name.lower())) or (next((x for (r, n), x in existing.items() if n == name.lower()), None))
        if sid:
            updated += 1
        else:
            sid = uuid.uuid4().hex[:10]
            repo.be.set(f"classes/{cid}/students", sid, {"name": name, "roll": roll, "order": base + i})
            existing[(roll, name.lower())] = sid
            made += 1
        repo.set_face(cid, sid, norm[:40], thumb)
    return made, updated


# --------------------------------------------------------------------- repo
def _nat(roll):
    m = re.match(r"^\s*(\d+)", roll or "")
    return (0, int(m.group(1)), roll) if m else (1, 0, (roll or "").lower())


FACE_KEYS = ("emb", "emb2", "thumb", "scanned_at", "n_emb", "n_emb2")


def _now():
    return datetime.now().isoformat(timespec="seconds")


class Repo:
    def __init__(self, be):
        self.be = be

    # ---- classes
    def classes(self):
        rows = [{"id": i, **d} for i, d in self.be.list("classes")]
        return sorted(rows, key=lambda c: c.get("created", ""))

    def get_class(self, cid):
        d = self.be.get("classes", cid)
        return {"id": cid, **d} if d else None

    def add_class(self, name):
        cid = uuid.uuid4().hex[:10]
        self.be.set("classes", cid, {"name": name, "created": _now()})
        return {"id": cid, "name": name}

    def rename_class(self, cid, name):
        d = self.be.get("classes", cid)
        d["name"] = name
        self.be.set("classes", cid, d)

    def delete_class(self, cid):
        for sub in ("students", "sessions", "photos"):
            self.be.delete_collection(f"classes/{cid}/{sub}")
        self.be.delete("classes", cid)

    # ---- students
    def students(self, cid, thumbs=False):
        fields = ["name", "roll", "order", "scanned_at"] + (["thumb"] if thumbs else [])
        rows = []
        for sid, d in self.be.list(f"classes/{cid}/students", fields):
            r = {"id": sid, "name": d.get("name", ""), "roll": d.get("roll", ""), "order": d.get("order", 0),
                 "scanned": bool(d.get("scanned_at"))}
            if thumbs and d.get("thumb"):
                r["thumb"] = "data:image/jpeg;base64," + base64.b64encode(d["thumb"]).decode()
            rows.append(r)
        rows.sort(key=lambda r: (_nat(r["roll"]), r["order"], r["name"].lower()))
        return rows

    def add_students(self, cid, rows):
        """Upsert by roll number (when given). Returns (added, updated)."""
        existing = {s["roll"]: s for s in self.students(cid) if s["roll"]}
        added = updated = 0
        base = int(time.time() * 1000)
        for i, r in enumerate(rows):
            name, roll = (r.get("name") or "").strip()[:80], (r.get("roll") or "").strip()[:30]
            if not name:
                continue
            if roll and roll in existing:
                sid = existing[roll]["id"]
                d = self.be.get(f"classes/{cid}/students", sid) or {}
                d["name"] = name
                self.be.set(f"classes/{cid}/students", sid, d)
                updated += 1
            else:
                sid = uuid.uuid4().hex[:10]
                self.be.set(f"classes/{cid}/students", sid, {"name": name, "roll": roll, "order": base + i})
                if roll:
                    existing[roll] = {"id": sid}
                added += 1
        return added, updated

    def update_student(self, cid, sid, name=None, roll=None):
        d = self.be.get(f"classes/{cid}/students", sid)
        if d is None:
            return False
        if name is not None:
            d["name"] = name.strip()[:80]
        if roll is not None:
            d["roll"] = roll.strip()[:30]
        self.be.set(f"classes/{cid}/students", sid, d)
        return True

    def delete_student(self, cid, sid):
        self.be.delete(f"classes/{cid}/students", sid)

    def copy_students(self, src, dst, with_faces=True, skip_rolls=False):
        n = 0
        base = int(time.time() * 1000)
        have = {s["roll"] for s in self.students(dst) if s["roll"]} if skip_rolls else set()
        for sid, d in self.be.list(f"classes/{src}/students"):
            if d.get("roll") and d["roll"] in have:
                continue
            nd = dict(d)
            if not with_faces:
                for k in FACE_KEYS:
                    nd.pop(k, None)
            nd["order"] = base + n
            self.be.set(f"classes/{dst}/students", uuid.uuid4().hex[:10], nd)
            n += 1
        return n

    def set_face(self, cid, sid, embs, thumb_jpg, embs2=None):
        """embs: (K,512) ArcFace-R50 rows (real + simulated far-away variants); embs2: (K2,512) ArcFace-R100 rows."""
        d = self.be.get(f"classes/{cid}/students", sid)
        if d is None:
            return False
        d["emb"] = np.asarray(embs, dtype=np.float32).reshape(-1, 512).tobytes()
        d["n_emb"] = len(embs)
        if embs2 is not None and len(embs2):
            d["emb2"] = np.asarray(embs2, dtype=np.float32).reshape(-1, 512).tobytes()
            d["n_emb2"] = len(embs2)
        else:
            d.pop("emb2", None); d.pop("n_emb2", None)
        d["scanned_at"] = _now()
        if thumb_jpg:
            d["thumb"] = thumb_jpg
        self.be.set(f"classes/{cid}/students", sid, d)
        return True

    def clear_face(self, cid, sid):
        d = self.be.get(f"classes/{cid}/students", sid)
        if d:
            for k in FACE_KEYS:
                d.pop(k, None)
            self.be.set(f"classes/{cid}/students", sid, d)

    def clear_all_faces(self, cid):
        n = 0
        for sid, d in self.be.list(f"classes/{cid}/students"):
            if d.get("emb"):
                for k in FACE_KEYS:
                    d.pop(k, None)
                self.be.set(f"classes/{cid}/students", sid, d); n += 1
        return n

    def delete_all_students(self, cid):
        self.be.delete_collection(f"classes/{cid}/students")

    def gallery(self, cid):
        out = []
        for sid, d in self.be.list(f"classes/{cid}/students", ["emb", "emb2"]):
            if d.get("emb"):
                A = np.frombuffer(d["emb"], dtype=np.float32).reshape(-1, 512)
                B = np.frombuffer(d["emb2"], dtype=np.float32).reshape(-1, 512) if d.get("emb2") else None
                out.append((sid, A, B))
        return out

    def set_class_fields(self, cid, **kw):
        d = self.be.get("classes", cid)
        d.update({k: v for k, v in kw.items() if v is not None})
        self.be.set("classes", cid, d)

    def settings(self):
        return self.be.get("settings", "admin") or {}

    def save_settings(self, d):
        self.be.set("settings", "admin", d)

    # ---- sessions
    def sessions(self, cid):
        rows = [{"id": i, **d} for i, d in self.be.list(f"classes/{cid}/sessions")]
        return sorted(rows, key=lambda s: (s["date"], min(s["slots"]) if s.get("slots") else 0))

    def get_session(self, cid, sid):
        d = self.be.get(f"classes/{cid}/sessions", sid)
        return {"id": sid, **d} if d else None

    def save_session(self, cid, sid, data):
        self.be.set(f"classes/{cid}/sessions", sid, data)

    def delete_session(self, cid, sid):
        s = self.get_session(cid, sid)
        if s:
            for pid in s.get("photos", []):
                self.be.delete(f"classes/{cid}/photos", pid)
        self.be.delete(f"classes/{cid}/sessions", sid)

    # ---- photos
    def save_photo(self, cid, pid, data, w, h, faces):
        self.be.set(f"classes/{cid}/photos", pid, {"data": data, "w": w, "h": h, "faces": faces})

    def get_photo(self, cid, pid):
        return self.be.get(f"classes/{cid}/photos", pid)

    def delete_photo(self, cid, pid):
        self.be.delete(f"classes/{cid}/photos", pid)
