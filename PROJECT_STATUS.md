# WildEx — Project Status (live check, 5 Nov 2026 ~07:40 AWST)

**Overall: MVP capture→card path is live.** Backend healthy; Gemini paid Tier 1 active.

## Stack
- FastAPI (Python) backend — `main.py`, `app/`
- PostgreSQL (Neon) via `DATABASE_URL` on Render
- PWA front end as static HTML in `app/static/`
- Gemini (card blurbs / ID), iNaturalist, GBIF, Open-Meteo
- Cloudflare R2 for media storage (live)

## Deploy (live)
- Service: `wildex` / [wildex-fsou.onrender.com](https://wildex-fsou.onrender.com) in Render My Workspace (`tea-d7ic1afaqgkc739qfcp0`)
- `/health` → `{"status":"healthy","database":true}` (verified 3 Nov 2026)
- R2 public base in use: `https://pub-808328b52e104ad8b1fe80751b5c4936.r2.dev` (captures fetch OK)
- Last deploy: 1 Nov 2026 ~17:40 AWST (same commit as Oct 25; env-only redeploys)

## Tests
Local Postgres 16: **52 passed, 5 skipped** (skips are live-API tests gated by
`WILDEX_LIVE_TESTS=1`).

## MVP path (the only thing in scope)
capture (phone video/photo) → species ID → card → WildDex (+ milestones)

## Next gate (live, not cached notes)
**Valid `GEMINI_API_KEY` on Render.** Last real capture job (1 Nov ~17:43 AWST) uploaded to R2 fine, then ID hard-failed: Gemini returned `API_KEY_INVALID` (key present but rejected). Google Vision/Web also 403; iNaturalist CV 500 that day. No capture jobs since, only health checks.
After a working Gemini key: one real phone capture → card in WildDex, then the 20-Australian-species run.

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
removed from this repo. Repo: https://github.com/bobcharlie88/survival-chefs

## 2026-11-04 — Capture→card fixed (prod)
- New GEMINI_API_KEY set on Render (deploy dep-dblbqmrncjis73ddfgm0, live). /health: healthy, database true.
- Prod retest: capture job 63 (red fox photo) → R2 upload OK → Gemini ID "Red fox" (Vulpes vulpes, conf 0.84) → status complete, card_id 64. No API_KEY_INVALID.
- Note: iNaturalist CV returned 500 during test (secondary provider); Gemini alone carried it.

## 2026-11-04 evening — Gemini free-tier quota (live logs)
- After successful job 63→card 64, further captures hit Gemini Free Tier daily limit (20 generate_content requests/day on gemini-3.8-flash). Job 64 ID failed with 429 RESOURCE_EXHAUSTED; biome card blurbs fell back to deterministic mode.
- iNaturalist CV still returning 500 (secondary). Google Vision/Web still hard-failed in provider lists.
- No new capture jobs after biome deploy dep-dblebg2vcj2c738krjd0 (~16:01 AWST). /health still healthy + database true.
- Gate for more phone testing tonight: paid Gemini billing on the Google AI project behind GEMINI_API_KEY, or wait for the free-tier daily reset (likely tomorrow morning AWST).

## 2026-11-05 morning — live recheck (Bull)
- `/health` → healthy, database true (verified 5 Nov ~07:40 AWST).
- Google AI Studio email (4 Nov ~19:16 AWST): billing account auto-upgraded to **paid Tier 1** (higher rate limits; already active).
- After the evening free-tier 429 note: capture **job 65** (Laughing Kookaburra) → Gemini 200 OK → **card_id 67** (~18:54–18:55 AWST 4 Nov). No further RESOURCE_EXHAUSTED in Render logs after that window.
- FOUND IN range maps shipped on main: commit `e402080` (4 Nov 19:46 AWST) — parchment silhouettes in biome colour; preview assets under `_preview/` and `_refs/mitch-card-designs/`.
- Local dirty (not pushed): `PROJECT_STATUS.md`, `_preview/`, `_refs/`, `app/static/_prev/`.

## 2026-11-27 — Back up after outage (Bull)
- Outage cause 1: old Neon project `Wildex` (nameless-snow-20727007) hit the free-plan monthly compute quota (~17 Nov). The capture worker polled the DB every 3 s, 24/7, so Neon never scaled to zero. Data is intact; quota resets 1 Dec 2026 08:00 AWST.
- Fix: worker now backs off to a 30-min idle poll after 10 min with no activity, and wakes instantly on capture/retry/list (commit a9afca8).
- Temporary DB: new Neon project `Wildex-2` (mute-cake-44522219, Sydney). Render DATABASE_URL now points there. Old cards/accounts are NOT visible until migrated back after 1 Dec.
- Outage cause 2: Gemini returns 402 "prepayment credits are depleted" — AI ID is down until credits are topped up in AI Studio.
- Workaround shipped: "I know what it is" manual ID on needs-review captures (commit 1c9e946); card mints with deterministic text.
- Renderer: FOUND IN map supports `range_polygons` for precise AU sub-ranges (commit c00c81a).
- Bot accounts on Wildex-2: user 1 atlas-freedom+wildex@mail.grokbot.com (holding account for Mitch's pygmy python), user 2 atlas-freedom+wildextest@mail.grokbot.com (test; kookaburra card 1).
