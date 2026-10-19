import base64, csv, io, json, os, re, threading, time, uuid
from datetime import date as _date, datetime, timezone

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_from_directory, Response, abort, session
from itsdangerous import URLSafeTimedSerializer
from PIL import Image, ImageOps

from werkzeug.security import check_password_hash, generate_password_hash

from faceengine import FaceEngine, similarity_matrix, assign
from storage import Repo, make_backend, find_legacy, import_legacy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("ATT_DATA", os.path.join(ROOT, "data"))
MODELS = os.path.join(ROOT, "models")
STATIC = os.path.join(os.path.dirname(__file__), "static")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")   # empty = no login (laptop demo)

# match thresholds per class "sensitivity":  (below low = unknown, above high = confirmed, in between = "check")
SENS = {"strict": (0.42, 0.54), "balanced": (0.36, 0.48), "lenient": (0.30, 0.42)}
T_LOW, T_HIGH = SENS["balanced"]

# guided 3D-ish face scan: step -> (frames to keep, instruction)
SCAN = [("front", 5), ("side_a", 3), ("side_b", 3), ("tilt_a", 2), ("tilt_b", 2)]
NEED = dict(SCAN)

app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_NAME"] = "__session"   # the only cookie Firebase Hosting forwards
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("K_SERVICE") or ADMIN_PASSWORD)
app.permanent_session_lifetime = 60 * 60 * 24 * 7

engine = FaceEngine(MODELS)
lock = threading.Lock()
repo = Repo(make_backend(DATA))
_ser = URLSafeTimedSerializer(app.secret_key, salt="scan-invite")


# ------------------------------------------------------------------ helpers
def decode(b, max_side=6000):
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(b))).convert("RGB")
    a = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    h, w = a.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        a = cv2.resize(a, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return a


def jpeg_under(img, max_side=1800, limit=850_000):
    """Re-encode an image so it fits comfortably inside a Firestore document."""
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    out = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    for q in (82, 74, 66, 58, 50):
        b = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()
        if len(b) <= limit:
            break
    return b, out.shape[1], out.shape[0], s


def crop_b64(img, box, size=88, margin=0.25):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    x1 = int(max(0, x1 - w * margin)); x2 = int(min(img.shape[1], x2 + w * margin))
    y1 = int(max(0, y1 - h * margin)); y2 = int(min(img.shape[0], y2 + h * margin))
    c = cv2.resize(img[y1:y2, x1:x2], (size, size), interpolation=cv2.INTER_AREA)
    return "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 80])[1]).decode()


def thumb_from(b64url, size=112):
    try:
        raw = base64.b64decode((b64url or "").split(",", 1)[1])
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        im = cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA)
        return cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 78])[1].tobytes()
    except Exception:
        return None


def dataurl_bytes(u):
    return base64.b64decode(u.split(",", 1)[1])


def slot_label(h):
    e = h + 1
    return f"{h % 12 or 12}-{e % 12 or 12} {'AM' if e < 12 else 'PM'}"


def need_class(cid):
    c = repo.get_class(cid)
    if not c: abort(404, "Class not found")
    return c


def check_date(d):
    if not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d): abort(400, "Bad date")
    return d


# -------------------------------------------------------------------- pages
def page(name):
    r = send_from_directory(STATIC, name)
    r.headers["Cache-Control"] = "no-cache"
    return r

@app.after_request
def nocache(resp):
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.get("/")
def index(): return page("index.html")

@app.get("/dashboard")
def dashboard_page(): return page("dashboard.html")

@app.get("/healthz")
def healthz(): return "ok"


# --------------------------------------------------------------------- auth
OPEN_PREFIXES = ("/static/", "/join/", "/api/join/", "/api/public/")
OPEN_PATHS = ("/", "/dashboard", "/healthz", "/api/login", "/api/me")

_pw = [0.0, None]
def stored_pw(force=False):
    if force or time.time() - _pw[0] > 30:
        try:
            _pw[1] = repo.settings().get("pw_hash")
        except Exception:
            pass
        _pw[0] = time.time()
    return _pw[1]

def auth_required():
    return bool(ADMIN_PASSWORD or stored_pw())

def pw_ok(p):
    h = stored_pw()
    if h:
        return check_password_hash(h, p or "")
    return bool(ADMIN_PASSWORD) and p == ADMIN_PASSWORD

@app.before_request
def guard():
    if not auth_required(): return
    p = request.path
    if p in OPEN_PATHS or p.startswith(OPEN_PREFIXES): return
    if not session.get("ok"):
        return jsonify(error="Login required", login=True), 401

@app.get("/api/me")
def me():
    return jsonify(login_required=auth_required(), authed=(not auth_required()) or bool(session.get("ok")))

@app.post("/api/login")
def login():
    j = request.get_json(force=True)
    if auth_required() and pw_ok(j.get("password")):
        session.permanent = True; session["ok"] = True
        return jsonify(ok=True)
    return jsonify(error="Wrong password"), 403

@app.post("/api/password")
def change_password():
    j = request.get_json(force=True)
    new = (j.get("new") or "").strip()
    if auth_required() and not pw_ok(j.get("old")): return jsonify(error="Current password is wrong"), 403
    if len(new) < 4: return jsonify(error="New password must be at least 4 characters"), 400
    d = repo.settings(); d["pw_hash"] = generate_password_hash(new); repo.save_settings(d); stored_pw(True)
    session.permanent = True; session["ok"] = True
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)


# ------------------------------------------------------------------ classes
@app.get("/api/classes")
def classes():
    out = repo.classes()
    if not out:                       # first launch: create a default class
        out = [repo.add_class("My Class")]
    return jsonify(out)

@app.post("/api/classes")
def add_class():
    j = request.get_json(force=True)
    name = (j.get("name") or "").strip()[:80]
    if not name: return jsonify(error="Class name required"), 400
    c = repo.add_class(name)
    src = j.get("copy_from")
    copied = 0
    if src and repo.get_class(src):
        copied = repo.copy_students(src, c["id"], with_faces=bool(j.get("with_faces", True)))
    return jsonify({**c, "copied": copied})

@app.patch("/api/classes/<cid>")
def edit_class(cid):
    need_class(cid)
    j = request.get_json(force=True)
    name = j.get("name")
    if name is not None:
        name = name.strip()[:80]
        if not name: return jsonify(error="Name required"), 400
    sens = j.get("sens")
    if sens is not None and sens not in SENS: return jsonify(error="Bad sensitivity"), 400
    repo.set_class_fields(cid, name=name, sens=sens)
    return jsonify(ok=True)

@app.delete("/api/classes/<cid>")
def delete_class(cid):
    need_class(cid)
    if len(repo.classes()) <= 1: return jsonify(error="You need at least one class - add another before deleting this one"), 400
    repo.delete_class(cid); return jsonify(ok=True)

@app.post("/api/classes/<cid>/clear-faces")
def clear_faces(cid):
    need_class(cid); return jsonify(cleared=repo.clear_all_faces(cid))

@app.post("/api/classes/<cid>/clear-students")
def clear_students(cid):
    need_class(cid); repo.delete_all_students(cid); return jsonify(ok=True)

@app.get("/api/classes/<cid>/students.xlsx")
def roster_xlsx(cid):
    c = need_class(cid)
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Students"
    ws.append(["Name", "Roll No", "Face scanned"])
    for st in repo.students(cid):
        ws.append([st["name"], st["roll"], "Yes" if st["scanned"] else "No"])
    ws.column_dimensions["A"].width = 32; ws.column_dimensions["B"].width = 14; ws.column_dimensions["C"].width = 14
    buf = io.BytesIO(); wb.save(buf)
    nm = re.sub(r"[^A-Za-z0-9]+", "_", c["name"]).strip("_") or "class"
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=students_{nm}.xlsx"})

@app.get("/api/legacy")
def legacy_scan():
    try:
        return jsonify(groups=find_legacy(repo))
    except Exception as e:
        return jsonify(error=f"Could not read the database: {type(e).__name__}: {e}"), 500

@app.post("/api/classes/<cid>/legacy-import")
def legacy_import(cid):
    need_class(cid)
    path = (request.get_json(force=True).get("path") or "").strip("/")
    try:
        made, updated = import_legacy(repo, path, cid)
    except ValueError:
        return jsonify(error="Bad path"), 400
    return jsonify(created=made, updated=updated)


# ----------------------------------------------------------------- students
@app.get("/api/classes/<cid>/students")
def students(cid):
    need_class(cid)
    return jsonify(repo.students(cid, thumbs=True))

@app.post("/api/classes/<cid>/students")
def add_students(cid):
    need_class(cid)
    rows = (request.get_json(force=True) or {}).get("rows") or []
    if not rows: return jsonify(error="Nothing to add"), 400
    a, u = repo.add_students(cid, rows[:500])
    return jsonify(added=a, updated=u)

@app.patch("/api/classes/<cid>/students/<sid>")
def edit_student(cid, sid):
    need_class(cid)
    j = request.get_json(force=True)
    if not repo.update_student(cid, sid, j.get("name"), j.get("roll")): abort(404)
    return jsonify(ok=True)

@app.delete("/api/classes/<cid>/students/<sid>")
def del_student(cid, sid):
    need_class(cid); repo.delete_student(cid, sid); return jsonify(ok=True)

@app.post("/api/classes/<cid>/copy-from")
def copy_into(cid):
    need_class(cid)
    j = request.get_json(force=True)
    if not repo.get_class(j.get("source")) or j["source"] == cid: abort(400, "Choose another class")
    return jsonify(copied=repo.copy_students(j["source"], cid, with_faces=bool(j.get("with_faces", True)), skip_rolls=True))

@app.post("/api/classes/<cid>/students/<sid>/clear-face")
def clear_face(cid, sid):
    need_class(cid); repo.clear_face(cid, sid); return jsonify(ok=True)

def _looks_roll(x):
    return bool(re.search(r"\d", x or "")) and len(x or "") <= 20

def parse_rows(rows):
    """rows = list of lists of cell strings -> [{name, roll}] (header + column-order detection)."""
    rows = [[str(c).strip() if c is not None else "" for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows: return []
    name_i, roll_i, start = 0, 1, 0
    head = [c.lower() for c in rows[0]]
    if any(re.search(r"name|roll|reg|\bid\b|no\.?$", c) for c in head) and not any(re.fullmatch(r"\d+", c) for c in head):
        for i, c in enumerate(head):
            if "name" in c: name_i = i
            elif re.search(r"roll|reg|\bid\b|\bno\b", c): roll_i = i
        start = 1
    else:
        sample = rows[:10]
        c0 = sum(1 for r in sample if r and re.fullmatch(r"[\w\-/.]*\d[\w\-/.]*", r[0]) and not re.search(r"[A-Za-z]{3,}", r[0]))
        c1 = sum(1 for r in sample if len(r) > 1 and re.search(r"[A-Za-z]{3,}", r[1]))
        if c0 >= len(sample) * 0.6 and c1 >= len(sample) * 0.6:
            name_i, roll_i = 1, 0
    out = []
    for r in rows[start:]:
        name = r[name_i] if len(r) > name_i else ""
        roll = r[roll_i] if len(r) > roll_i else ""
        if name: out.append({"name": name[:80], "roll": roll[:30]})
    return out

@app.post("/api/classes/<cid>/students/parse-file")
def parse_file(cid):
    need_class(cid)
    f = request.files.get("file")
    if not f: return jsonify(error="No file"), 400
    fn = (f.filename or "").lower(); data = f.read()
    try:
        if fn.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
            rows = [[("" if c is None else (str(int(c)) if isinstance(c, float) and c.is_integer() else c)) for c in r] for r in ws.iter_rows(values_only=True)]
        else:
            txt = data.decode("utf-8-sig", errors="replace")
            dialect = csv.Sniffer().sniff(txt[:2000], delimiters=",;\t") if txt.strip() else csv.excel
            rows = list(csv.reader(io.StringIO(txt), dialect))
    except Exception as e:
        return jsonify(error=f"Could not read that file ({type(e).__name__}). Use .xlsx or .csv"), 400
    return jsonify(rows=parse_rows(rows)[:500])

@app.get("/api/students-template.xlsx")
def template():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Students"
    ws.append(["Name", "Roll No"]); ws.append(["Aisha Khan", "1"]); ws.append(["Rahul Verma", "2"])
    ws.column_dimensions["A"].width = 32; ws.column_dimensions["B"].width = 14
    buf = io.BytesIO(); wb.save(buf)
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=students_template.xlsx"})


# ------------------------------------------------------------ face analysis
def thr_for(c):
    return SENS.get((c or {}).get("sens") or "balanced", SENS["balanced"])


@app.post("/api/classes/<cid>/analyze")
def analyze(cid):
    c = need_class(cid)
    t_low, t_high = thr_for(c)
    t0 = time.time()
    img = decode(request.files["image"].read())
    H, W = img.shape[:2]
    info = {}
    with lock:
        faces = engine.detect_group(img, info=info)
        crops, keep = [], []
        for f in faces:
            a = engine.align(img, f["kps"])
            if a is not None:
                crops.append(a); keep.append(f)
        faces = keep
        E1 = engine.embed_crops(crops, flip=True) if crops else np.zeros((0, 512), np.float32)
        g = repo.gallery(cid)
        E2, sims = None, None
        if len(E1) and g:
            sims = similarity_matrix(E1, g)
            # second opinion (ArcFace R100) for faces the fast model is unsure about
            if engine.rec2 is not None and any(x[2] is not None for x in g):
                best = sims.max(axis=1)
                unsure = [i for i in range(len(E1)) if 0.26 <= best[i] < 0.62][:70]
                if unsure:
                    E2 = np.zeros_like(E1)
                    E2[unsure] = engine.embed_crops_r100([crops[i] for i in unsure])
                    sims = similarity_matrix(E1, g, face_embs2=E2)
    matches = assign(sims, t_low) if sims is not None else {}
    shown, sw, sh, sc = jpeg_under(img)
    out, byid = [], {}
    for i, f in enumerate(faces):
        item = {"bbox": [round(float(x) * sc, 1) for x in f["bbox"]], "sid": None, "sim": None, "status": "unknown",
                "px": int(f["bbox"][2] - f["bbox"][0])}
        if sims is not None:
            item["best"] = round(float(sims[i].max()), 3)
        if i in matches:
            sid = g[matches[i]][0]; s_ = float(sims[i, matches[i]])
            item.update(sid=sid, sim=round(s_, 3), status="confirmed" if s_ >= t_high else "check")
            byid[sid] = {"sim": item["sim"], "status": item["status"]}
        out.append(item)
    return jsonify(image="data:image/jpeg;base64," + base64.b64encode(shown).decode(), w=sw, h=sh, faces=out,
                   matches=byid, seconds=round(time.time() - t0, 1), gallery=len(g),
                   src=[W, H], low_res=max(W, H) < 2400, scan=info)


# ----------------------------------------------------------------- sessions
def _clean_faces(fs):
    out = []
    for f in (fs or [])[:300]:
        try:
            out.append({"bbox": [round(float(x), 1) for x in f["bbox"][:4]], "sid": f.get("sid") or None,
                        "sim": None if f.get("sim") is None else round(float(f["sim"]), 3), "status": str(f.get("status", "unknown"))[:12]})
        except Exception:
            pass
    return out

def build_session(cid, body, sid, old=None):
    date = check_date(body.get("date"))
    try:
        slots = sorted({int(x) for x in body.get("slots") or []})
    except Exception:
        abort(400, "Bad hours")
    if not slots or any(h < 0 or h > 23 for h in slots) or len(slots) > 12: abort(400, "Pick at least one hour")
    N = len(slots)
    ids = {s["id"] for s in repo.students(cid)}
    marks = {}
    for k, v in (body.get("marks") or {}).items():
        try: v = max(0, min(N, int(v)))
        except Exception: continue
        if k in ids and v > 0: marks[k] = v
    for o in repo.sessions(cid):
        if o["id"] != sid and o["date"] == date and set(o["slots"]) & set(slots):
            return None, (jsonify(error=f"There is already a record on {date} for {', '.join(slot_label(h) for h in sorted(set(o['slots']) & set(slots)))}. Open it from Records to edit.", session_id=o["id"]), 409)
    keep_old = set((old or {}).get("photos", []))
    pids = []
    for p in (body.get("photos") or [])[:10]:
        if p.get("pid") and p["pid"] in keep_old:
            pids.append(p["pid"]); continue
        if not p.get("image"): continue
        raw = dataurl_bytes(p["image"])
        if len(raw) > 900_000:
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            raw, w, h, _ = jpeg_under(im, 1600)
        else:
            w, h = int(p.get("w") or 0), int(p.get("h") or 0)
        pid = uuid.uuid4().hex[:10]
        repo.save_photo(cid, pid, raw, w, h, _clean_faces(p.get("faces")))
        pids.append(pid)
    for pid in keep_old - set(pids):
        repo.delete_photo(cid, pid)
    now = datetime.now().isoformat(timespec="seconds")
    return {"date": date, "slots": slots, "marks": marks, "photos": pids,
            "created": (old or {}).get("created", now), "updated": now}, None

@app.get("/api/classes/<cid>/sessions")
def sessions(cid):
    need_class(cid)
    total = len(repo.students(cid))
    out = []
    for s in repo.sessions(cid):
        out.append({"id": s["id"], "date": s["date"], "slots": s["slots"], "present": len(s.get("marks", {})), "total": total,
                    "photos": len(s.get("photos", []))})
    return jsonify(out)

@app.post("/api/classes/<cid>/sessions")
def create_session(cid):
    need_class(cid)
    sid = uuid.uuid4().hex[:10]
    data, err = build_session(cid, request.get_json(force=True), sid)
    if err: return err
    repo.save_session(cid, sid, data)
    return jsonify(id=sid, **{k: data[k] for k in ("date", "slots")}, present=len(data["marks"]))

@app.get("/api/classes/<cid>/sessions/<sid>")
def get_session(cid, sid):
    need_class(cid)
    s = repo.get_session(cid, sid)
    if not s: abort(404, "Record not found")
    photos = []
    for pid in s.get("photos", []):
        p = repo.get_photo(cid, pid)
        if p: photos.append({"pid": pid, "w": p["w"], "h": p["h"], "faces": p["faces"], "url": f"/api/classes/{cid}/photos/{pid}.jpg"})
    return jsonify(id=s["id"], date=s["date"], slots=s["slots"], marks=s.get("marks", {}), photos=photos)

@app.put("/api/classes/<cid>/sessions/<sid>")
def update_session(cid, sid):
    need_class(cid)
    old = repo.get_session(cid, sid)
    if not old: abort(404, "Record not found")
    data, err = build_session(cid, request.get_json(force=True), sid, old)
    if err: return err
    repo.save_session(cid, sid, data)
    return jsonify(ok=True, present=len(data["marks"]))

@app.delete("/api/classes/<cid>/sessions/<sid>")
def del_session(cid, sid):
    need_class(cid); repo.delete_session(cid, sid); return jsonify(ok=True)

@app.get("/api/classes/<cid>/photos/<pid>.jpg")
def photo(cid, pid):
    if not re.fullmatch(r"[0-9a-f]{10}", pid): abort(400)
    p = repo.get_photo(cid, pid)
    if not p: abort(404)
    return Response(p["data"], mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------ matrix/export
def build_matrix(cid, d_from=None, d_to=None):
    studs = repo.students(cid)
    sess = [s for s in repo.sessions(cid) if (not d_from or s["date"] >= d_from) and (not d_to or s["date"] <= d_to)]
    cols = []
    for s in sess:
        slots = sorted(s["slots"]); N = len(slots)
        for i, h in enumerate(slots):
            cols.append({"date": s["date"], "hour": h, "label": slot_label(h), "session": s["id"], "i": i, "n": N})
    cols.sort(key=lambda c: (c["date"], c["hour"]))
    marks = {s["id"]: s.get("marks", {}) for s in sess}
    rows = []
    for st in studs:
        cells = [1 if c["i"] >= c["n"] - marks[c["session"]].get(st["id"], 0) else 0 for c in cols]
        att = sum(cells)
        rows.append({"id": st["id"], "name": st["name"], "roll": st["roll"], "cells": cells, "attended": att,
                     "total": len(cols), "pct": round(100 * att / len(cols)) if cols else None})
    groups = []
    for c in cols:
        if groups and groups[-1]["date"] == c["date"]: groups[-1]["span"] += 1
        else: groups.append({"date": c["date"], "span": 1})
    pcts = [r["pct"] for r in rows if r["pct"] is not None]
    summary = {"students": len(studs), "sessions": len(sess), "hours": len(cols),
               "avg": round(sum(pcts) / len(pcts)) if pcts else None, "below75": sum(1 for p in pcts if p < 75)}
    return {"columns": cols, "groups": groups, "rows": rows, "summary": summary}

def _range():
    f, t = request.args.get("from") or None, request.args.get("to") or None
    return (check_date(f) if f else None), (check_date(t) if t else None)

@app.get("/api/classes/<cid>/matrix")
def matrix(cid):
    c = need_class(cid); f, t = _range()
    return jsonify(cls={"id": cid, "name": c["name"]}, **build_matrix(cid, f, t))

@app.get("/api/classes/<cid>/export.xlsx")
def export_xlsx(cid):
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter as L
    c = need_class(cid); f, t = _range()
    m = build_matrix(cid, f, t)
    wb = Workbook(); ws = wb.active; ws.title = "Attendance"
    head = PatternFill("solid", fgColor="1E293B"); white = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="CBD5E1"); box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws["A1"] = "Roll No"; ws["B1"] = "Name"
    ws.merge_cells("A1:A2"); ws.merge_cells("B1:B2")
    col = 3
    for g in m["groups"]:
        d = datetime.strptime(g["date"], "%Y-%m-%d")
        ws.cell(1, col, d.strftime("%d %b %Y (%a)"))
        if g["span"] > 1: ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + g["span"] - 1)
        col += g["span"]
    for i, cc in enumerate(m["columns"]): ws.cell(2, 3 + i, cc["label"])
    n = len(m["columns"]); sc = 3 + n
    for j, h in enumerate(("Hours attended", "Total hours", "Attendance %")):
        ws.cell(1, sc + j, h); ws.merge_cells(start_row=1, start_column=sc + j, end_row=2, end_column=sc + j)
    for r in range(1, 3):
        for cx in range(1, sc + 3):
            x = ws.cell(r, cx); x.fill = head; x.font = white; x.alignment = center; x.border = box
    for ri, row in enumerate(m["rows"]):
        r = 3 + ri
        ws.cell(r, 1, int(row["roll"]) if re.fullmatch(r"\d{1,9}", row["roll"] or "") else row["roll"])
        ws.cell(r, 2, row["name"])
        for i, v in enumerate(row["cells"]): ws.cell(r, 3 + i, v)
        ws.cell(r, sc, row["attended"]); ws.cell(r, sc + 1, row["total"])
        ws.cell(r, sc + 2, (row["pct"] / 100) if row["pct"] is not None else None).number_format = "0%"
        for cx in range(1, sc + 3):
            x = ws.cell(r, cx); x.border = box
            if cx != 2: x.alignment = Alignment(horizontal="center")
    if n and m["rows"]:
        rng = f"C3:{L(2 + n)}{2 + len(m['rows'])}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["1"], fill=PatternFill("solid", bgColor="DCFCE7", fgColor="DCFCE7"), font=Font(color="166534")))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["0"], fill=PatternFill("solid", bgColor="FEE2E2", fgColor="FEE2E2"), font=Font(color="991B1B")))
    ws.column_dimensions["A"].width = 10; ws.column_dimensions["B"].width = 30
    for i in range(n): ws.column_dimensions[L(3 + i)].width = 9
    for j in range(3): ws.column_dimensions[L(sc + j)].width = 15
    ws.row_dimensions[2].height = 30
    ws.freeze_panes = "C3"
    s2 = wb.create_sheet("Classes held")
    s2.append(["Date", "Hours", "Number of hours", "Students present", "Total students"])
    total = len(m["rows"])
    for s in repo.sessions(cid):
        if (f and s["date"] < f) or (t and s["date"] > t): continue
        s2.append([s["date"], ", ".join(slot_label(h) for h in sorted(s["slots"])), len(s["slots"]), len(s.get("marks", {})), total])
    for cx, w in zip("ABCDE", (14, 34, 16, 18, 14)): s2.column_dimensions[cx].width = w
    for x in s2[1]: x.font = Font(bold=True)
    buf = io.BytesIO(); wb.save(buf)
    nm = re.sub(r"[^A-Za-z0-9]+", "_", c["name"]).strip("_") or "class"
    rng_txt = f"_{f or 'start'}_to_{t or 'today'}" if (f or t) else ""
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=attendance_{nm}{rng_txt}.xlsx"})


# ------------------------------------------------- face-scan links (students)
def token_info(t):
    try:
        data, ts = _ser.loads(t, return_timestamp=True)
        left = data["h"] * 3600 - (datetime.now(timezone.utc) - ts).total_seconds()
        return (data, left) if left > 0 and repo.get_class(data["c"]) else (None, 0)
    except Exception:
        return None, 0

@app.post("/api/invite")
def make_invite():
    j = request.get_json(force=True)
    need_class(j.get("cid"))
    hours = max(1, min(120, int(j.get("hours") or 5)))
    return jsonify(token=_ser.dumps({"c": j["cid"], "h": hours}), hours=hours)

@app.get("/join/<token>")
def join_page(token):
    data, _ = token_info(token)
    if not data:
        return Response("<body style='font:18px sans-serif;background:#f6f7fb;color:#0f172a;text-align:center;padding:60px'>"
                        "<h2>This link has expired</h2><p>Ask your teacher for a new one.</p>", status=410, mimetype="text/html")
    return page("join.html")

@app.get("/api/join/<token>/info")
def join_info(token):
    data, left = token_info(token)
    if not data: return jsonify(error="Link expired"), 410
    c = repo.get_class(data["c"])
    studs = [{"id": s["id"], "name": s["name"], "roll": s["roll"], "scanned": s["scanned"]} for s in repo.students(data["c"])]
    return jsonify(cls=c["name"], students=studs, minutes_left=int(left // 60))

@app.post("/api/join/<token>/frame")
def join_frame(token):
    if not token_info(token)[0]: return jsonify(error="Link expired"), 410
    return frame_impl()

def _png_crop(u):
    try:
        raw = base64.b64decode((u or "").split(",", 1)[1])
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if im is None or im.shape[0] < 64: return None
        return cv2.resize(im, (112, 112), interpolation=cv2.INTER_AREA) if im.shape[:2] != (112, 112) else im
    except Exception:
        return None


def store_face(cid, sid, crops):
    """crops: list of aligned 112x112 BGR faces (best first). Embeds them with both recognisers, adds simulated
    far-away/soft variants (so a close-up scan also matches a blurry back-row face) and saves.
    Returns (warning|None). Raises ValueError with a user-facing message when the scan is unusable."""
    with lock:
        A = engine.embed_crops(crops, flip=True)
        # drop crops that don't look like the same person as the rest (someone walked into frame)
        cen = A.mean(0); cen /= (np.linalg.norm(cen) + 1e-9)
        sim = A @ cen
        good = [i for i in range(len(crops)) if sim[i] >= 0.40]
        if len(good) < max(2, int(len(crops) * 0.6)):
            raise ValueError("The scan frames did not look like one person. Please scan again, alone in the frame.")
        crops = [crops[i] for i in good]; A = A[good]
        rng = np.random.RandomState(7)
        deg = [engine.degrade(c, rng) for c in crops]
        Ad = engine.embed_crops(deg, flip=False)
        B = engine.embed_crops_r100(crops) if engine.rec2 is not None else None
    warn = None
    others = [(i, a, b) for i, a, b in repo.gallery(cid) if i != sid]
    if others:
        front = A[: min(5, len(A))].mean(0, keepdims=True)
        front /= (np.linalg.norm(front) + 1e-9)
        if similarity_matrix(front, others).max() > 0.62:
            warn = "This face is very similar to another student's scan. If you picked the wrong name, scan again with the right one."
    thumb = cv2.imencode(".jpg", crops[0], [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()
    repo.set_face(cid, sid, np.concatenate([A, Ad]), thumb, B)
    return warn


@app.post("/api/join/<token>/finish")
def join_finish(token):
    data, _ = token_info(token)
    if not data: return jsonify(error="Link expired"), 410
    cid = data["c"]; j = request.get_json(force=True)
    sid = j.get("student_id")
    st = next((s for s in repo.students(cid) if s["id"] == sid), None)
    if not st: return jsonify(error="Please choose your name from the list"), 400
    crops = []
    for k, need in SCAN:
        arr = (j.get("crops") or {}).get(k) or []
        got = [c for c in (_png_crop(u) for u in arr[:6]) if c is not None]
        if len(got) < need: return jsonify(error="Scan not complete"), 400
        crops += got
    try:
        warn = store_face(cid, sid, crops)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, name=st["name"], warning=warn)


@app.post("/api/classes/<cid>/students/<sid>/face-photos")
def face_from_photos(cid, sid):
    """Teacher fallback: set a student's face from 1-8 ordinary photos (ID card, selfies...)."""
    need_class(cid)
    if not any(s["id"] == sid for s in repo.students(cid)): abort(404)
    crops = []
    for f in request.files.getlist("image")[:8]:
        img = decode(f.read())
        with lock:
            faces = engine.detect(img, (960,), thr=0.5)
        if faces:
            a = engine.align(img, faces[0]["kps"])
            if a is not None: crops.append(a)
    if not crops: return jsonify(error="No clear face found in those photos"), 400
    if len(crops) < 4:                      # few photos: mirrored / re-lit copies keep the matching stable
        crops = crops + [c[:, ::-1].copy() for c in crops] + [cv2.convertScaleAbs(c, alpha=1.12, beta=8) for c in crops]
    try:
        warn = store_face(cid, sid, crops)
    except ValueError as e:
        return jsonify(error="Those photos do not look like the same person"), 400
    return jsonify(ok=True, used=len(crops), warning=warn)


def frame_impl():
    step = request.form.get("step", "front")
    sign = int(request.form.get("sign") or 0)           # sign of the first side turn / first tilt
    base = float(request.form.get("base") or 0.55)      # this person's neutral pitch ratio (from the front frames)
    img = decode(request.files["image"].read())
    H, W = img.shape[:2]
    with lock:
        faces = engine.detect(img, (640,), thr=0.6)
    res = {"w": W, "h": H, "faces": len(faces), "ok": False, "box": None, "kps": None}
    if not faces:
        res["msg"] = "No face found - look at the camera"; return jsonify(res)
    f = faces[0]; box, kps = f["bbox"], f["kps"]
    res["box"] = box.tolist(); res["kps"] = kps.tolist(); res["score"] = float(f["score"])
    fw = box[2] - box[0]
    yaw = engine.yaw_ratio(kps); res["yaw"] = yaw
    pitch = engine.pitch_ratio(kps); res["pitch"] = pitch
    if len(faces) > 1 and (faces[1]["bbox"][2] - faces[1]["bbox"][0]) > 0.5 * fw:
        res["msg"] = "Only one person in frame, please"; return jsonify(res)
    if fw < 0.18 * min(W, H) * 1.0:
        res["msg"] = "Move a little closer"; return jsonify(res)
    if fw > 0.80 * min(W, H):
        res["msg"] = "Move back a little"; return jsonify(res)
    ay = abs(yaw)
    if step == "front":
        ok = ay < 0.12 and abs(pitch - base) < 0.10 if request.form.get("base") else ay < 0.12
        res["msg"] = "Hold still..." if ok else "Look straight at the camera"
    elif step == "side_a":
        ok = 0.20 < ay <= 0.65
        res["msg"] = "Hold still..." if ok else ("A bit less - not a full profile" if ay > 0.65 else "Turn your head slowly to one side")
    elif step == "side_b":
        ok = sign != 0 and 0.20 < ay <= 0.65 and yaw * sign < 0
        res["msg"] = "Hold still..." if ok else "Now turn to the OTHER side"
    elif step == "tilt_a":
        d = pitch - base
        ok = abs(d) >= 0.08 and ay < 0.22
        res["msg"] = "Hold still..." if ok else "Face the camera, then tilt your head a little up or down"
    else:
        d = pitch - base
        ok = sign != 0 and abs(d) >= 0.08 and d * sign < 0 and ay < 0.22
        res["msg"] = "Hold still..." if ok else "Now tilt the opposite way"
    if ok:
        a = engine.align(img, kps)
        if a is None:
            res["ok"] = False; res["msg"] = "Hold steady"; return jsonify(res)
        gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        blur = engine.blur_score(a); mean = float(gray.mean()); contrast = float(gray.std())
        if mean < 45 or contrast < 18:
            res["ok"] = False; res["msg"] = "Too dark - face a light"; return jsonify(res)
        if mean > 225:
            res["ok"] = False; res["msg"] = "Too bright - avoid glare"; return jsonify(res)
        if blur < 22:
            res["ok"] = False; res["msg"] = "Blurry - hold the phone steady"; return jsonify(res)
        res["ok"] = True
        res["crop"] = "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", a)[1].tobytes()).decode()
        res["side_sign"] = 1 if yaw > 0 else -1
        res["tilt_sign"] = 1 if pitch > base else -1
        res["blur"] = round(blur)
    return jsonify(res)


# ---------------------------------------------------------- public dashboard
@app.get("/api/public/classes")
def pub_classes():
    return jsonify([{"id": c["id"], "name": c["name"]} for c in repo.classes()])

@app.get("/api/public/classes/<cid>/matrix")
def pub_matrix(cid):
    c = need_class(cid); f, t = _range()
    return jsonify(cls={"id": cid, "name": c["name"]}, **build_matrix(cid, f, t))


# -------------------------------------------------------------------- errors
@app.errorhandler(Exception)
def on_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException) and e.code < 500:
        return jsonify(error=e.description), e.code
    app.logger.exception("request failed")
    return jsonify(error=f"{type(e).__name__}: {e}"), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  Attendance running -> http://localhost:{port}\n")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, threaded=True)
