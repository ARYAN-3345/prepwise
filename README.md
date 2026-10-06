# Prepwise · GATE DA Study Tracker

A Flask MVP for GATE Data Science and Artificial Intelligence aspirants. It includes accounts, a seeded topic roadmap, study timers and history, topic progress, PYQ and mock tracking, a mistake book, and a shared notes library.

## Run locally

1. Install Python 3.11 or later.
2. Create and activate a virtual environment, then install `requirements.txt`.
3. Copy `.env.example` to `.env`. Change `SECRET_KEY` before deployment. SQLite is used by default for local development.
4. Start with `python app.py` and open `http://127.0.0.1:5000`.

The database tables and initial syllabus are created at startup. Set `DATABASE_URL` to a PostgreSQL connection URL in production. Use a managed PostgreSQL database and set `SECRET_KEY` to a long random value.

## Cloud file storage

When `S3_BUCKET` is empty, uploads are stored under `instance/uploads`. For cloud storage, set `S3_BUCKET`, `AWS_REGION`, and credentials via the deployment's secret manager or workload identity. The adapter supports S3-compatible services that boto3 can address; configure a custom endpoint in `storage.py` for providers such as R2 or MinIO. Files are delivered through short-lived signed links when S3 is enabled.

The study tracker requires an account. The resource library and shared file links are public; uploading requires signing in. The library has a GATE DA book shelf (PDF only) alongside section-organized notes. Study and performance records are scoped to their owner. Max upload size is 100 MB per resource file and 100 MB total for mistake images. Configure a reverse proxy and HTTPS in deployment.

The mistake book accepts multiple PNG, JPEG, WEBP, or GIF attachments per entry. Voice dictation uses the browser's Web Speech API where supported (for example, current Chrome or Edge); microphone permission is required, and HTTPS is required outside localhost.

The PYQ / DPP tracker lets students switch between PYQ and DPP sets, logging attempted and correct totals plus question references to review. Accuracy is calculated across both types, including older PYQ entries.

## Structure

```text
app.py                 app factory and web routes
models.py              SQLAlchemy domain models
extensions.py          shared Flask extensions
seed.py                initial GATE DA topic outline
storage.py             local/S3-compatible file storage
templates/             server-rendered pages
static/                responsive styling and chart/timer behavior
```

The topic outline follows the GATE 2027 DA syllabus PDF supplied for this project. On startup, the app synchronizes the active topic list to that outline. Previously stored topic rows are retained as inactive history so session and study records are not discarded. Analytics endpoints and separately modeled activity records provide a base for later recommendations or retrieval features.
