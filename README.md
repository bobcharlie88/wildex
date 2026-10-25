# WildEx

A real-world wildlife discovery game: film or photograph a real animal, get it
identified, and collect it as a card in your personal **WildDex**.

**MVP loop:** capture → species ID → card → WildDex. Everything else
(battles, quests, explore map, Gemma, Flutter, advanced anti-cheat, AI art) is
parked — see [PROJECT_STATUS.md](PROJECT_STATUS.md).

## Stack
FastAPI · PostgreSQL · static-HTML PWA · Gemini · iNaturalist / GBIF · Cloudflare R2

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # slim, no torch
cp .env.example .env  # if present; otherwise set DATABASE_URL, SESSION_SECRET, GEMINI_API_KEY
uvicorn main:app --reload
```
Open http://localhost:8000 and check http://localhost:8000/health.

Without R2 vars, uploads fall back to local `uploads/`.

### Tests
```bash
DATABASE_URL=postgresql://postgres:x@localhost:5432/wildex pytest -q
# live API tests: WILDEX_LIVE_TESTS=1 (needs real keys)
```

### Optional: offline Gemma Dr Agent
`pip install -r requirements-gemma.txt` and set `DR_AGENT_ENGINE=gemma`
(see `OFFLINE_GEMMA.md`). Not used on Render; default is `rule_based`.

## Deploy
Render Blueprint (`render.yaml`). See [DEPLOY.md](DEPLOY.md) and
[DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md). Keep keys in Render env vars, never in Git.
