# Attendance - face-recognition class attendance

**Admin (teacher)** opens the site, signs in, and is on the attendance screen straight away.
**Students** only ever see two things: a temporary face-scan link and the public dashboard.

## Pages
- `/` - admin: Attendance (home), Records, Students. Class switcher and Share button at the top.
- `/join/<token>` - student face scan (temporary link, 1 hour to 5 days).
- `/dashboard` - public attendance dashboard (never expires, no login).

## Taking attendance
1. Pick the date and the hour(s) of the class (current hour is pre-selected; tap several for 2- or 3-hour classes).
2. Add photos: **Take photo** (phone camera) or **Upload photos**. Add as many as you like - one row at a time gives the sharpest faces. Everyone found is combined.
3. Review the list. Each student shows 0..N (hours attended). Tap a lower number for a late student.
4. **Save attendance**. It is only stored when you press Save.

Each saved class is one row under Records > Classes taken. Open it to see the photos, add students back or change hours.

## Excel
Records > Export to Excel (optionally for a date range). One column per class hour, `1` = attended, `0` = missed; dates are merged across their hours.
A student marked 2 of 3 hours counts as late: 0 for the first hour, 1 for the last two.

## Students and classes
Students tab: paste two columns from Excel (Name, Roll no.), upload .xlsx/.csv, or add one at a time. Edit any name/roll in place.
New class: optionally copy students (and their face scans) from another class - the copy is independent.

## Run on your own computer
```
bash run.sh
```
then open http://localhost:8000 (no password locally unless you set `ADMIN_PASSWORD`).

## Put it online
See `DEPLOY.md` (Google Cloud Run + Firestore).

## Tech
- Detection: InsightFace SCRFD-10G. Class photos are scanned whole AND in overlapping zoomed-in tiles (small photos are enlarged first), so tiny blurry back-row faces are found.
- Recognition: ArcFace R50 (every face, plus a mirrored copy) and ArcFace R100 (second opinion on unsure faces). Matching is one-to-one per photo (Hungarian assignment).
- Face scan: 5 guided poses (front, left, right, tilt, tilt back) with live quality checks (distance, light, blur, one person). Each scan also stores simulated soft/far-away versions of the face, so close-up scans still match faces in a class photo.
- Settings: rename/delete class, matching strictness (strict / balanced / lenient), reset scans, change password, import old scans.
