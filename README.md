<div align="center">

# 📸 Classroom Face Attendance

### Scan every student once. Snap the class. Attendance marks itself.

*A face-recognition attendance system that finds 50+ faces in a single classroom photo, matches each one to an enrolled student, and hands the teacher a clean review screen and an Excel sheet.*

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-backend-000000?logo=flask)
![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-CPU-005CED?logo=onnx&logoColor=white)
![Google Cloud Run](https://img.shields.io/badge/Cloud_Run-deploy-4285F4?logo=googlecloud&logoColor=white)
![Firestore](https://img.shields.io/badge/Firestore-database-FFCA28?logo=firebase&logoColor=black)
![Frontend](https://img.shields.io/badge/Frontend-vanilla_JS-F7DF1E?logo=javascript&logoColor=black)
![Models](https://img.shields.io/badge/Models-non--commercial-red)

[Features](#-features) · [The big picture](#-the-big-picture) · [Journey](#-the-teachers-day-in-one-picture) · [Under the hood](#-under-the-hood) · [Using the app](#-using-the-app) · [Deploy](#-deploy-to-google-cloud-run) · [Limits](#-honest-limitations) · [Licensing](#-model-licensing-read-this)

</div>

<!-- Add screenshots to docs/screenshots/ and uncomment:
<p align="center">
  <img src="docs/screenshots/attendance.png" width="24%">
  <img src="docs/screenshots/review.png" width="24%">
  <img src="docs/screenshots/scan.png" width="24%">
  <img src="docs/screenshots/records.png" width="24%">
</p>
-->

---

## ✨ Why this exists

Calling out names in a class of 60 eats 5–10 minutes of every lecture. Paper registers get lost. Tap-to-mark apps still need a human to look at every face.

This project turns attendance into **one photo**:

| Old way | This way |
|---|---|
| 🗣 Roll call, 5–10 min | 📷 One or a few photos, ~seconds of teacher time |
| 📝 Paper register | 📊 Auto-built records sheet + Excel export |
| 🤷 Proxy attendance | 👀 Every face reviewed, uncertain ones flagged |
| 🧍 Teacher scans each student | 📱 Students scan themselves from a link |

---

## 🚀 Features

<table>
<tr>
<td width="50%" valign="top">

### 🎓 For teachers
- 📷 **Multi-photo sessions**: upload or capture several photos; each student is counted once
- ⏰ **Multi-hour classes**: present for the last 2 of 3 hours? Recorded exactly
- 🔍 **Review screen** with *confirmed*, *check* and *unknown* faces; reassign any face in a tap
- 🗂 **Records sheet** (students × dates), with editable past sessions
- 📥 **Excel export** with merged date headers, 1/0 cells, date-range filter and a "Classes held" sheet
- 🏫 **Multiple classes**, each with its own sensitivity (strict / balanced / lenient)
- ⚙️ **Class settings**: rename, download roster, reset scans, change password, delete class
- 📋 **Roster import** from Excel/CSV, or copy from another class

</td>
<td width="50%" valign="top">

### 🙋 For students
- 🔗 **Shareable scan link** that expires in 1 h, 5 h, 2 days or 5 days
- 🧭 **Guided 5-pose scan**: front, left, right, tilt up, tilt down
- ✅ **Live quality coaching**: face too small, too dark, blurry or turned the wrong way? It tells you
- 📱 Works from a normal phone browser, no app install
- 👯 **Duplicate warning** if a scan looks like another student

### 🧠 For the engine
- 🔬 **Tiled multi-scale detection** for tiny back-row faces
- 🤝 **Two-model ensemble** (ArcFace R50 + R100) for uncertain faces
- ♟ **One-to-one assignment**: two faces can't claim the same student
- 🌐 **Public read-only dashboard** to share results

</td>
</tr>
</table>

---

## 🗺 The big picture

Everything in the project, in one diagram:

```mermaid
flowchart TB
    subgraph USERS["👥 People"]
        TCH["👩‍🏫 Teacher"]
        STU["🙋 Student"]
        VIEW["👀 Viewer"]
    end

    subgraph BROWSER["🌐 Browser, no build step"]
        SPA["index.html + app.js<br/>Teacher SPA"]
        JOIN["join.html<br/>Guided face scan"]
        DASH["dashboard.html + matrix.js<br/>Public dashboard"]
    end

    subgraph SERVER["🖥 Flask + gunicorn"]
        AUTH["🔐 Auth<br/>password + signed cookie"]
        LINKS["🔗 Scan links<br/>signed, expiring tokens"]
        GATES["🚦 Quality gates<br/>pose, light, blur, size"]
        ANALYZE["📸 Analyze pipeline"]
        EXPORT["📊 Excel export<br/>openpyxl"]
        REPO["🗃 Repo layer<br/>20 s list cache"]
    end

    subgraph ENGINE["🧠 Face engine, ONNX Runtime CPU"]
        DET["SCRFD-10G<br/>detector"]
        R50["ArcFace R50<br/>recogniser"]
        R100["ArcFace R100<br/>second opinion"]
        HUN["Hungarian<br/>assignment"]
    end

    subgraph STORE["💾 Storage"]
        FS[("Firestore")]
        LOC[("Local JSON<br/>dev mode")]
    end

    TCH --> SPA
    STU --> JOIN
    VIEW --> DASH

    SPA --> AUTH
    SPA --> ANALYZE
    SPA --> EXPORT
    JOIN --> LINKS
    LINKS --> GATES
    DASH --> REPO

    GATES --> DET
    GATES --> R50
    ANALYZE --> DET
    ANALYZE --> R50
    ANALYZE --> R100
    ANALYZE --> HUN

    AUTH --> REPO
    ANALYZE --> REPO
    EXPORT --> REPO
    REPO --> FS
    REPO -.-> LOC
```

---

## 📅 The teacher's day in one picture

```mermaid
journey
    title From first login to Excel sheet
    section Set up once
      Create a class: 5: Teacher
      Add names and roll numbers: 4: Teacher
      Send the scan link: 5: Teacher
    section Students enroll
      Open link on phone: 5: Student
      Follow 5 guided poses: 4: Student
      Scan saved: 5: Student
    section Every class
      Take one or more class photos: 5: Teacher
      Wait for analysis: 3: Teacher
      Fix the few uncertain faces: 4: Teacher
      Save the session: 5: Teacher
    section Anytime
      View records sheet: 5: Teacher
      Download Excel: 5: Teacher
      Share the dashboard: 4: Viewer
```

---

## 🔬 Under the hood

### 1️⃣ Enrollment: building a student's face profile

The server is stateless during a scan. The browser holds the progress, the server judges every frame.

```mermaid
sequenceDiagram
    autonumber
    actor S as Student phone
    participant J as join.html
    participant API as Flask API
    participant E as Face engine
    participant DB as Firestore

    S->>J: Open scan link
    J->>API: GET /api/join/token/info
    API-->>J: Class name and required steps
    loop 15 good frames across 5 poses
        J->>API: POST /frame with step, sign, base
        API->>E: Detect face at 640 px
        E-->>API: Box, 5 landmarks
        API->>API: Quality gates
        alt Frame passes
            API-->>J: Aligned 112x112 crop
        else Frame rejected
            API-->>J: Coaching message
        end
    end
    J->>API: POST /finish with 15 crops
    API->>E: R50 on crops and mirrors
    API->>E: R50 on degraded copies
    API->>E: R100 on originals
    API->>API: Consistency check
    API->>DB: Save embeddings and thumbnail
    API-->>J: Done
```

**The five poses and what each must satisfy**

| Step | Crops | Pose rule |
|---|---|---|
| 🙂 Front | 5 | \|yaw\| < 0.12, pitch becomes the student's baseline |
| ↩️ Side A | 3 | 0.20 < \|yaw\| ≤ 0.65 |
| ↪️ Side B | 3 | same range, opposite direction to Side A |
| ⬆️ Tilt A | 2 | \|Δpitch\| ≥ 0.08 vs baseline, \|yaw\| < 0.22 |
| ⬇️ Tilt B | 2 | opposite tilt to Tilt A |

**Quality gates applied to every frame**

```mermaid
flowchart LR
    F["📷 Frame"] --> ONE{"Exactly<br/>one face?"}
    ONE -- no --> X1["❌ Show only your face"]
    ONE -- yes --> SZ{"Face width<br/>18 to 80%?"}
    SZ -- no --> X2["❌ Move closer or back"]
    SZ -- yes --> POSE{"Pose matches<br/>this step?"}
    POSE -- no --> X3["❌ Turn or tilt as shown"]
    POSE -- yes --> LIGHT{"Brightness 45 to 225<br/>contrast at least 18?"}
    LIGHT -- no --> X4["❌ Fix the lighting"]
    LIGHT -- yes --> BLUR{"Blur score<br/>at least 22?"}
    BLUR -- no --> X5["❌ Hold still"]
    BLUR -- yes --> OK["✅ Keep 112x112 aligned crop"]
```

> **Pose maths.** Yaw = (nose_x − eye-midpoint_x) / eye distance. Pitch = (nose_y − eye_y) / (mouth_y − eye_y), compared with the person's own front-facing baseline so differently shaped faces are treated fairly.

**What gets stored per student** (so recognition survives real classroom conditions):

```mermaid
flowchart LR
    C["15 aligned crops"] --> A["R50 on crop + mirror<br/>15 rows"]
    C --> B["Degraded copies<br/>blur, noise, downscale<br/>15 rows"]
    C --> D["R100 on originals<br/>15 rows"]
    A --> EMB["emb: 30 rows"]
    B --> EMB
    D --> EMB2["emb2: 15 rows"]
    EMB --> CHK{"Cosine to centroid<br/>at least 0.40?"}
    EMB2 --> CHK
    CHK -- "keep at least max 2 or 60%" --> SAVE[("Saved")]
    CHK -- too inconsistent --> REJ["❌ Looks like different people, rescan"]
```

---

### 2️⃣ Finding every face in a crowded photo

Back-row faces can be only 10–30 pixels wide. A normal detector misses them, so `detect_group` looks at the photo several ways and merges the results.

```mermaid
flowchart TB
    IMG["🖼 Class photo"] --> UP["Upscale to about 3600 px<br/>max 2.5x, cap 5200 px"]
    UP --> P1["Full image pass at 1280"]
    UP --> P2["Full image pass at 2560"]
    UP --> P3["Tiles of 640 px<br/>stride 432"]
    P1 --> M["Collect candidates<br/>threshold 0.38"]
    P2 --> M
    P3 --> M
    M --> NMS["NMS IoU 0.4<br/>plus containment rule 0.8"]
    NMS --> MIN["Drop faces under 10 px"]
    MIN --> MAP["Map boxes back to<br/>original coordinates"]
    MAP --> OUT["✅ 56 faces found on the sample photo"]
```

---

### 3️⃣ Matching faces to students

```mermaid
flowchart TB
    FACES["Detected faces"] --> AL["5-point alignment<br/>to 112x112"]
    AL --> E50["R50 embedding<br/>original + mirror averaged"]
    E50 --> SIM["Cosine similarity vs gallery<br/>score = mean of top 3"]
    SIM --> UNS{"Best score in<br/>0.26 to 0.62?"}
    UNS -- yes --> E100["R100 second opinion<br/>cap 70 faces<br/>average both scores"]
    UNS -- no --> HUN
    E100 --> HUN["Hungarian assignment<br/>one face to one student"]
    HUN --> TH{"Threshold<br/>sensitivity preset"}
    TH -- "at or above high" --> CONF["🟢 Confirmed"]
    TH -- "between low and high" --> CHECK["🟡 Check"]
    TH -- "below low" --> UNK["🔴 Unknown"]
```

| Sensitivity | 🔴 Unknown below | 🟢 Confirmed at or above | Best for |
|---|---|---|---|
| Strict | 0.42 | 0.54 | Fewer false matches, more manual review |
| **Balanced** (default) | 0.36 | 0.48 | Most classrooms |
| Lenient | 0.30 | 0.42 | Hard lighting, accept more review of matches |

Anything between the two numbers lands in the 🟡 **check** pile for the teacher.

---

### 4️⃣ The attendance session lifecycle

```mermaid
stateDiagram-v2
    [*] --> PhotosAdded: Teacher uploads or captures photos
    PhotosAdded --> Analyzing: Analyze
    Analyzing --> Review: Faces matched
    Review --> Review: Reassign face or toggle student
    Review --> Conflict: Same date and hour already exists
    Conflict --> Review: Change date or hour
    Review --> Saved: Save session
    Saved --> Editing: Edit from records sheet
    Editing --> Saved
    Saved --> Exported: Download Excel
    Exported --> [*]
```

**Hours work like this:** `marks[student] = k` means the student attended the **last k** of the session's N sorted hour slots. A date + hour overlap returns HTTP 409.

---

### 5️⃣ How a face becomes a mark: end-to-end

```mermaid
sequenceDiagram
    autonumber
    actor T as Teacher
    participant UI as Teacher SPA
    participant API as Flask API
    participant E as Face engine
    participant DB as Storage

    T->>UI: Add one or more class photos
    UI->>API: POST /classes/cid/analyze
    API->>DB: Load gallery of student embeddings
    API->>E: detect_group on each photo
    API->>E: R50 embeddings, mirror averaged
    API->>E: R100 for unsure faces
    API->>API: Hungarian one-to-one assignment
    API-->>UI: faces, matches, status, timing
    T->>UI: Fix check and unknown faces
    UI->>API: POST /classes/cid/sessions
    API->>DB: Save session and photos
    T->>UI: Download Excel
    UI->>API: GET /classes/cid/export.xlsx
    API-->>T: Attendance workbook
```

---

## 🧰 Tech stack

| Layer | Choice | Why |
|---|---|---|
| 🐍 Backend | Python 3.11, Flask, gunicorn (1 worker, 4 threads) | Simple, one process keeps the models in memory once |
| 👁 Detection | SCRFD-10G (`det_10g.onnx`, 17 MB) | Strong on small faces |
| 🧬 Recognition | ArcFace R50 (`w600k_r50.onnx`, 174 MB) and R100 Glint360K (`glintr100.onnx`, 260 MB) | Fast first pass, heavy second opinion |
| ⚡ Inference | ONNX Runtime, CPU | No GPU needed |
| 🖼 Imaging | OpenCV (headless), Pillow, NumPy | Alignment, resizing, quality checks |
| 🔢 Matching | SciPy (Hungarian), scikit-learn | One-to-one assignment |
| 💾 Storage | Firestore or local JSON | Same `Repo` interface for both |
| 🖥 Frontend | Vanilla JS SPA with hash routing | No bundler, no framework |
| 📊 Export | openpyxl | Merged headers, 1/0 grid |
| 🔐 Security | Admin password, signed cookie, `itsdangerous` timed tokens | Scan links expire on their own |
| ☁️ Hosting | Google Cloud Run (Cloud Build from `Dockerfile`), optional Firebase Hosting rewrite | Scales to zero |

---

## 📖 Using the app

The app is hosted on **Google Cloud Run**, so teachers and students just open its web address. Nothing to install.

> 🌐 **Live app:** `https://YOUR-SERVICE-URL.run.app` *(replace with your Cloud Run URL)*

### Who sees what

| Role | How they get in | What they can do |
|---|---|---|
| 👩‍🏫 **Admin (teacher)** | Opens the site and signs in with the admin password | Everything: attendance, records, students, class settings |
| 🙋 **Student** | A temporary scan link from the teacher | Only the face scan |
| 👀 **Anyone** | The public dashboard link | Read-only attendance view, no login |

### Pages

| Path | Purpose |
|---|---|
| `/` | Admin app: **Attendance** (home), **Records**, **Students**. Class switcher and Share button at the top. |
| `/join/<token>` | Student face scan. Temporary link, valid from 1 hour to 5 days. |
| `/dashboard` | Public attendance dashboard. Never expires, no login. |

### Taking attendance

1. **Pick the date and hour(s).** The current hour is pre-selected; tap several for 2- or 3-hour classes.
2. **Add photos** with *Take photo* (phone camera) or *Upload photos*. Add as many as you like; faces from all photos are combined, and one photo at a time gives the sharpest faces.
3. **Review the list.** Each student shows 0..N hours attended. Tap a lower number for a late student, and fix any 🟡 *check* or 🔴 *unknown* faces.
4. **Save attendance.** Nothing is stored until you press Save.

Each saved class becomes one row under **Records → Classes taken**. Open it to see the photos, add students back or change hours.

### Excel export

**Records → Export to Excel** (optionally for a date range). There is one column per class hour: `1` = attended, `0` = missed, with dates merged across their hours. A student marked 2 of 3 hours counts as late: `0` for the first hour, `1` for the last two.

### Students and classes

- **Add students** by pasting two columns from Excel (Name, Roll no.), uploading `.xlsx` / `.csv`, or adding one at a time. Edit any name or roll number in place.
- **New class:** optionally copy students (and their face scans) from another class. The copy is independent.
- **Get scans:** use *Share* to create a scan link and send it to students, or add photos for a student from the Students tab.
- **Class settings (⚙):** rename or delete the class, set matching strictness (strict / balanced / lenient), reset scans, change the admin password, import old scans.

---

## ☁️ Deploy to Google Cloud Run

```mermaid
flowchart LR
    DEV["💻 Your machine<br/>gcloud run deploy"] --> CB["🏗 Cloud Build<br/>builds Dockerfile<br/>downloads models"]
    CB --> AR["📦 Artifact Registry"]
    AR --> CR["🚀 Cloud Run<br/>service: faceroll<br/>4 GiB, 2 vCPU"]
    CR <--> FS[("🔥 Firestore<br/>asia-south1")]
    USER["🌍 Teachers and students"] --> FH["Optional: Firebase Hosting<br/>rewrite"]
    FH --> CR
    USER --> CR
```

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com firestore.googleapis.com
gcloud firestore databases create --location=asia-south1   # once

gcloud run deploy faceroll --source . --region asia-south1 \
  --memory 4Gi --cpu 2 --timeout 300 --cpu-boost \
  --max-instances 2 --concurrency 4 --allow-unauthenticated \
  --set-env-vars ADMIN_PASSWORD=your-password,SECRET_KEY=$(openssl rand -hex 32)
```

**Checklist**

- 🧠 **Memory:** at least **4 GiB**; both recognisers plus the detector live in RAM
- 🔑 **IAM:** the Cloud Run service account needs `roles/datastore.user` to use Firestore
- 🔄 **Update:** re-run `gcloud run deploy faceroll --source . --region asia-south1 --memory 4Gi --cpu 2 --timeout 300`; env vars are kept
- 🍪 **Cookie name:** `__session`, the only cookie Firebase Hosting forwards
- 📘 More detail in [`DEPLOY.md`](DEPLOY.md), including recovering scans saved by an older version

Free-tier and trial terms change; check Google's current pricing before assuming anything is free.

---

## ⚙️ Configuration

| Variable | What it does | Default |
|---|---|---|
| `ADMIN_PASSWORD` | Admin login. A password changed inside the app (stored hashed in `settings/admin`) overrides it. Neither set means no login. | unset |
| `SECRET_KEY` | Signs cookies and scan links. Rotating it kills every existing scan link. | random per run, so set it in production |
| `STORE` | `local` or `firestore` | `local` (`firestore` in Docker) |
| `ATT_DATA` | Folder for local JSON data | `data/` |
| `PORT`, `HOST` | Bind address | `8000`, `0.0.0.0` |
| `K_SERVICE` | Set by Cloud Run; makes the cookie `Secure` | n/a |

---

## 💻 Run locally (optional, for development)

You do not need this to use the app. It is only for developing or testing changes on your own machine.

```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
bash run.sh          # sets up a venv, downloads models, starts the server
```

Then open `http://localhost:8000`. Data is stored in `data/` as local JSON, and there is no login unless you set `ADMIN_PASSWORD`. The phone camera only works over HTTPS, so test the student scan page on the deployed Cloud Run URL.

---

## 🗃 Data model

```mermaid
erDiagram
    CLASS ||--o{ STUDENT : has
    CLASS ||--o{ SESSION : records
    CLASS ||--o{ PHOTO : stores
    SESSION }o--o{ PHOTO : uses
    SESSION ||--o{ MARK : contains
    STUDENT ||--o{ MARK : earns

    CLASS {
        string id
        string name
        string sens
        timestamp created
    }
    STUDENT {
        string id
        string name
        string roll
        int order
        array emb "R50 rows"
        array emb2 "R100 rows"
        blob thumb "front crop JPEG"
        timestamp scanned_at
    }
    SESSION {
        string id
        string date
        array slots "hours"
        timestamp created
        timestamp updated
    }
    MARK {
        string student_id
        int hours_attended "last k of N slots"
    }
    PHOTO {
        string id
        blob data "JPEG up to about 850 KB"
        int w
        int h
        array faces "bbox, sid, sim, status"
    }
```

Plus one global document, `settings/admin`, holding the password hash.

---

## 🔌 API at a glance

~40 routes. Everything under `/api` needs the admin session, except login, health, public and join endpoints.

| Area | Endpoints |
|---|---|
| 🔐 Auth | `POST /api/login` · `POST /api/logout` · `GET /api/me` · `POST /api/password` |
| 🏫 Classes | `GET/POST /api/classes` · `PATCH/DELETE /api/classes/<cid>` · `POST …/clear-faces` · `POST …/clear-students` · `POST …/copy-from` |
| 🎓 Students | `GET/POST …/students` · `PATCH/DELETE …/students/<sid>` · `POST …/students/parse-file` · `GET /api/students-template.xlsx` · `GET …/students.xlsx` · `POST …/students/<sid>/face-photos` · `POST …/students/<sid>/clear-face` |
| 📸 Attendance | `POST …/analyze` · `GET/POST …/sessions` · `GET/DELETE …/sessions/<id>` · `GET …/photos/<pid>.jpg` · `GET …/matrix` · `GET …/export.xlsx` |
| 🔗 Scan links | `POST /api/invite` · `GET /join/<token>` · `GET /api/join/<token>/info` · `POST …/frame` · `POST …/finish` |
| 🌐 Public | `GET /api/public/classes` · `GET /api/public/classes/<cid>/matrix` |
| 🛟 Migration | `GET /api/legacy` · `POST /api/classes/<cid>/legacy-import` |
| ❤️ Ops | `GET /healthz` |

---

## 📁 Project structure

```mermaid
flowchart LR
    ROOT["📦 repo"] --> APP["app/"]
    ROOT --> SCR["scripts/"]
    ROOT --> PUB["public/"]
    ROOT --> MOD["models/<br/>git-ignored"]
    ROOT --> FILES["Dockerfile · firebase.json<br/>run.sh · requirements.txt<br/>DEPLOY.md · README.md"]

    APP --> SRV["server.py<br/>routes, auth, gates, pipeline"]
    APP --> FE["faceengine.py<br/>detect, align, embed, match"]
    APP --> ST["storage.py<br/>Repo, Firestore, local, legacy import"]
    APP --> STA["static/"]
    STA --> H1["index.html + app.js<br/>teacher SPA"]
    STA --> H2["join.html<br/>student scan"]
    STA --> H3["dashboard.html + matrix.js<br/>public view"]
    STA --> H4["common.css"]

    SCR --> S1["download_models.py"]
    SCR --> S2["evaluate.py *"]
    SCR --> S3["make_demo_class.py *"]
```

<sub>\* Optional developer helpers that expect a local `demo/` folder. The server does not use them.</sub>

---

## 🎯 Getting the best accuracy

1. 📸 **Photo quality beats settings.** Aim for faces at least ~30 px wide, front-lit, no motion blur. The app warns when an upload's long side is under 2400 px.
2. 🔁 **Take 2–3 photos** from different angles; a face missed in one is usually caught in another.
3. 🎚 **Pick the right sensitivity** per class (Settings → Sensitivity).
4. 🧑‍🏫 **Re-scan** students who keep showing up as *check* or *unknown*, ideally in similar lighting to the classroom.
5. 🔧 Constants for scales, tile stride, thresholds and the R100 band sit near the top of `faceengine.py` and `server.py`.

---

## ⏱ Performance

Measured on a 2-CPU sandbox, CPU only:

| Task | Time |
|---|---|
| Class photo with ~56 faces (full tiled detection + ensemble) | **about 40 s** |
| Model loading on startup | about 15 s |

Cloud Run timings have not been benchmarked and will vary with CPU allocation. Use a minimum instance count if cold starts matter. The project deliberately trades speed for accuracy.

---

## ⚠️ Honest limitations

- **Not benchmarked at scale.** Tested on sample photos, not a large labelled classroom dataset. Always keep the review step.
- **No liveness check.** A printed photo or a screen can pass during enrollment.
- **Scan links can't be revoked one by one.** They expire; rotate `SECRET_KEY` to kill all.
- **Public dashboard lists all classes.** It is for convenience, not confidentiality.
- **One analysis at a time.** A long class analysis blocks other face work on the same worker.
- **Real Firestore not end-to-end tested here.** Verified against a fake/local backend; test on your own project.
- **Scan thresholds are untested on real phones.** Side-turn and tilt limits in `frame_impl` may need adjusting.
- Tiny, blurred, masked or heavily occluded faces will be missed or mismatched.

---

## 🔒 Privacy and consent

Face images and embeddings are **biometric, sensitive personal data**.

- ✍️ Get informed consent from students (and guardians for minors) before enrolling
- ⚖️ Check applicable law (GDPR, India's DPDP Act, local education and child-protection rules)
- 🗄 Stored data: face embeddings, one small thumbnail per student, and the class photos you upload
- 🧹 Delete via *reset all scans*, *delete student*, *delete session*, *delete class*
- 🔑 Set a strong `ADMIN_PASSWORD` and `SECRET_KEY` on any public deployment

---

## 📜 Model licensing: read this

The **code** in this repo is MIT. The **model weights are not.**

- SCRFD and ArcFace models come from the [InsightFace](https://github.com/deepinsight/insightface) packs `buffalo_l` and `antelopev2`. InsightFace states its pretrained models are **for non-commercial research use only**; commercial use needs a licence from the InsightFace team (contact@insightface.ai).
- Planning to sell or commercially deploy this? Get commercial rights or swap in models whose licence fits.
- Models are never committed; `scripts/download_models.py` fetches them.

---

## 🛣 Roadmap

```mermaid
timeline
    title Where this could go
    Now : Web app on Cloud Run : Guided 5-pose scan : Tiled detection + R50/R100 ensemble : Excel export
    Next : Liveness detection : Revocable scan links : Multiple teacher accounts : Background job queue
    Later : Licensed or self-trained models : Offline phone app, on-device models : Cloud backup and Pro sharing : Labelled accuracy benchmark
```

---

## 🤝 Contributing

1. Fork and branch
2. Run locally with `bash run.sh` and try your change on a few real photos
3. Keep PRs focused; say what changed and how you tested it
4. **Never commit** model files, student photos or personal data

---

## 📄 License

Code: [MIT](LICENSE) (add a `LICENSE` file with your name and year). Model weights: their own licences, see [above](#-model-licensing-read-this).

## 🙏 Acknowledgements

[InsightFace](https://github.com/deepinsight/insightface) · [ONNX Runtime](https://onnxruntime.ai/) · [OpenCV](https://opencv.org/) · [NumPy](https://numpy.org/) · [SciPy](https://scipy.org/) · [Flask](https://flask.palletsprojects.com/) · [openpyxl](https://openpyxl.readthedocs.io/) · Google Cloud Run and Firestore

<div align="center">

**If this saved you a roll call, drop a ⭐**

</div>
