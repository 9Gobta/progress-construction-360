# Progress Construction 360

เว็บแอปต้นแบบสำหรับตรวจความก้าวหน้างานก่อสร้างจากวิดีโอ 360 องศา เปรียบเทียบ Planned Progress กับผลตรวจจริงที่ผู้ใช้ยืนยัน พร้อมหลักฐานที่ตรวจสอบย้อนหลังได้ ระบบยังใช้ AI/CV ช่วยระบุตำแหน่งภาพบนแปลน แต่ไม่ใช้ AI ตัดสิน Progress

## สถานะ

- Scope v2: ตรวจ Progress โดยผู้ใช้เท่านั้น
- Development: Week 2 Vertical Slice + Localization Baseline v2
- Progress: งานโครงสร้าง พร้อมหลักฐานภาพ 360 และประวัติผู้ตรวจ

อ่านขอบเขตและลำดับเอกสารที่ [docs/planning/00-planning-index.md](docs/planning/00-planning-index.md)

## Collaboration

- ภาพรวมและข้อเท็จจริงกลางของโครงการ: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)
- วิธีแบ่งงานพัฒนาเว็บ/ทำเล่มคนละเครื่อง: [THESIS_HANDOFF.md](THESIS_HANDOFF.md)
- Prompt เริ่มงานสำหรับ Codex ของผู้ทำเล่ม: [docs/thesis/CODEX_START_PROMPT_TH.md](docs/thesis/CODEX_START_PROMPT_TH.md)
- กติกาที่ Codex ทุก task ต้องปฏิบัติตาม: [AGENTS.md](AGENTS.md)

## Repository

```text
apps/web/                 Next.js web application
apps/api/                 FastAPI modular API and database migrations
workers/                  Background task entry points by processing domain
packages/                 Shared contracts and reusable packages
ml/                       Dataset manifests, experiments and model artifacts metadata
infra/                    Local infrastructure configuration
scripts/                  Developer commands
tests/                    Cross-service and acceptance tests
Data/                     Original project data; excluded from Git
```

## Quick start without Docker

The API defaults to a local SQLite database when `DATABASE_URL` is not set. This mode is for development and tests only.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\apps\api[dev]"
python -m alembic -c apps/api/alembic.ini upgrade head
python -m uvicorn progress_api.main:app --app-dir apps/api/src --reload --reload-dir apps/api/src
```

In another terminal:

```powershell
npm install
npm run dev:web
```

Open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/health/live`

Rebuild the source-data inventory without modifying `Data`:

```powershell
.\.venv\Scripts\python.exe scripts\build_dataset_manifest.py
```

After Redis is available, start the background worker:

```powershell
.\.venv\Scripts\python.exe -m celery -A progress_api.worker:celery_app worker -Q video_cpu --pool=solo --concurrency=1 --loglevel=INFO
```

## Full local infrastructure

On Windows, start MinIO, the API and the web app together (and open the browser) with:

```powershell
npm run dev:local
```

Docker is required for PostgreSQL, Redis and MinIO:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env -f infra/compose.yaml up -d
```

Do not commit `.env`, video data, model weights or generated media.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/src apps/api/tests scripts
.\.venv\Scripts\python.exe -m pytest apps/api/tests
.\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini check
npm run lint:web
npm run typecheck:web
npm run build:web
```

รายละเอียด Localization และ Warp Point ที่พัฒนาแล้วอยู่ใน
`docs/development/05-localization-warp-points.md`

สถานะ Dense Capture Path, Warp Point quality gate และ Calibration correction อยู่ใน
`docs/development/06-localization-v2-status.md`
