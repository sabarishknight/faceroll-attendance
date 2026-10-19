# Put FaceRoll online (Google Cloud Run + Firestore + optional Firebase Hosting)

Free for a class-sized demo: Cloud Run and Firestore both have monthly free quotas. Google requires a card on file
to enable them; stay inside the quota and you pay nothing. **Set a budget alert (step 3).**

## 1. One-time setup on your Mac
```
brew install --cask google-cloud-sdk
gcloud auth login
```

## 2. Create a project (pick your own unique id)
```
gcloud projects create faceroll-sabarish-01 --set-as-default
```
Then open https://console.cloud.google.com/billing , link a billing account to this project.

## 3. Budget alert (so you can never be surprised)
Console > Billing > Budgets & alerts > Create budget > amount 100 INR (or $1) > alert at 50% and 100%.

## 4. Turn on the services and create the database
```
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com
gcloud firestore databases create --location=asia-south1
```

## 5. Deploy (from the project folder)
```
cd ~/Desktop/attendance-demo
gcloud run deploy faceroll --source . --region asia-south1 --allow-unauthenticated \
  --memory 4Gi --cpu 2 --cpu-boost --max-instances 2 --concurrency 4 --timeout 300 \
  --set-env-vars "ADMIN_PASSWORD=CHOOSE-A-PASSWORD,SECRET_KEY=$(openssl rand -hex 24)"
```
Say yes if it asks to create an Artifact Registry repo. It builds for ~8-12 minutes (downloads the face models, ~450 MB, into
the image) and prints a link like `https://faceroll-xxxxx-el.a.run.app` - that is your live app. Teachers sign in with the password you chose.
The first visit after idle takes ~15 s (the model loads); after that it is fast.

## 6. (Optional) a nicer address on Firebase Hosting: https://YOUR-PROJECT.web.app
```
npm install -g firebase-tools
firebase login
firebase use --add        # choose the same project
firebase deploy --only hosting
```
`firebase.json` already forwards everything to the Cloud Run service named `faceroll` in asia-south1.

## Update later
Re-run the `gcloud run deploy ...` command from step 5 (you can omit --set-env-vars, settings are kept).

## Notes
- Face data = biometric data. Get consent, keep the password private, delete students who leave (Students tab > Remove).
- To change the password: `gcloud run services update faceroll --region asia-south1 --update-env-vars ADMIN_PASSWORD=NEW`
- Stop everything / delete all data: `gcloud projects delete YOUR-PROJECT-ID`

## If the build fails with a permission error (new Google projects)
```
PROJECT=your-project-id
SA=$(gcloud projects describe $PROJECT --format="value(projectNumber)")-compute@developer.gserviceaccount.com
for ROLE in roles/datastore.user roles/storage.admin roles/artifactregistry.writer roles/logging.logWriter roles/cloudbuild.builds.builder; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="$ROLE" --condition=None --quiet >/dev/null
done
```
`roles/datastore.user` is what lets the app read and write Firestore.

## Updating to a newer version (keeps your password, students, scans and records)
```
cd ~/Desktop/attendance-demo
gcloud run deploy faceroll --source . --region asia-south1 --memory 4Gi --cpu 2 --timeout 300
```
Your settings (ADMIN_PASSWORD, SECRET_KEY) and all database data stay as they are. Redeploying never deletes scans.

## Getting scans saved by an older version back
Open the app > Settings (top right) > "Find & import old scans" > Import. It searches the database for face scans
saved by earlier versions and brings them into the current class, where you can edit names and roll numbers.
