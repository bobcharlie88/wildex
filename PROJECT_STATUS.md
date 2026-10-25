# WildEx — Project Status (honest audit, Oct 2026)

**Overall: ~55–65% of MVP.** Backend is mostly built; there is **no proven
end-to-end run with live API keys** yet.

## Stack
- FastAPI (Python) backend — `main.py`, `app/`
- PostgreSQL (SQLAlchemy)
- PWA front end as static HTML in `app/static/`
- Gemini (card blurbs / ID fallback), iNaturalist, GBIF, Open-Meteo
- Cloudflare R2 for media storage

## Deploy
Render via `render.yaml`. Needs an external Postgres (Neon free tier or Render
Postgres), an R2 bucket + 5 `R2_*` vars, and `GEMINI_API_KEY`.
See `DEPLOY.md` and `DEPLOY_CHECKLIST.md`.

## Tests
Local Postgres 16: **52 passed, 5 skipped** (skips are live-API tests gated by
`WILDEX_LIVE_TESTS=1`).

## MVP path (the only thing in scope)
capture (phone video/photo) → species ID → card → WildDex (+ milestones)

## Next gate
**One real phone capture → card appears in WildDex**, on the deployed app with
live keys. After that: the 20-Australian-species run.

## Parked until after MVP
Code may exist (API-only, no screens) but is not promoted in UI or docs:
- Battles, coin-flip arenas, loser's-tax / high-stakes card transfers
- Quests
- Explore / spatial map
- Gemma offline Dr Agent (optional, `requirements-gemma.txt`; Render uses `rule_based`)
- Flutter app
- Reverse-image search / AI-generation anti-cheat
- Grok Imagine card art (template cards are fine for MVP)

## Legacy
PythonAnywhere deployment files — see `LEGACY.md`.

## Not this project
WildChef / Survival Chefs is a **separate, independent project** and has been
removed from this repo. Planned repo: `bobcharlie88/survival-chefs` (pending creation).
