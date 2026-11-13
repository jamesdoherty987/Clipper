# GTAClipper

Standalone local app for GTA short-form content:

- **Streamer clips** — upload long VODs → AI highlights → vertical shorts
- **Explainers** — topic/script → facecam → gameplay match → 9:16 render
- **Gameplay library** — AI tagging + semantic search
- **Review desk** — approve / reject / download / regenerate

Designed to run on your laptop (not on BookedForYou’s Render starter box).

## Requirements

- Python 3.12+
- Node 18+
- FFmpeg + ffprobe on PATH
- OpenAI API key

## Setup

```bash
cd GTAClipper
cp .env.example .env
# edit .env and set OPENAI_API_KEY

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

## Run locally

Terminal 1 — API:

```bash
cd GTAClipper
source .venv/bin/activate
export PYTHONPATH=backend
uvicorn app.main:app --app-dir backend --reload --port 8787
```

Terminal 2 — UI:

```bash
cd GTAClipper/frontend
npm run dev
```

Open http://localhost:5177

## Notes

- Media is stored under `data/media/` and served at `/media/...`
- Job state is in `data/store.json`
- URL scraping is intentionally disabled — upload files you have rights to
- Keep BookedForYou on Render; run heavy FFmpeg jobs here
