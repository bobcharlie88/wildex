# WildEx Project Status

## Current System Summary

WildEx is a FastAPI-based mobile web app for capturing wildlife observations, processing them through a background capture job pipeline, generating code-rendered collectible cards, and storing them in a per-user WildEx collection plus regional Dex.

Current major capabilities in local source:
- user registration/login with signed session cookies
- authenticated capture flow with background processing jobs
- per-user card ownership and per-user WildEx/Dex browsing
- image upload persistence to Cloudflare R2 with local `/uploads` fallback
- multi-provider species identification with retry and degraded handling
- code-rendered front/back cards in-app with download/export
- regional map unlocks and structured Dex navigation
- client-side offline queue in IndexedDB with later sync
- in-app background job notifications, repeat-state messaging, and favorite card background
- app/card sharing via native share when available, copy-link fallback otherwise

Live deployment target:
- Render
- live URL: `https://wildex-fsou.onrender.com`

This file reflects local source state. Live behavior depends on Render deployment freshness and environment configuration.

## Architecture And Stack

Backend:
- FastAPI app entrypoint in `main.py`
- SQLAlchemy models in `app/models.py`
- routers under `app/routers/`
- pipeline modules under `app/pipeline/`
- gameplay services under `app/services/`
- R2/local upload helper in `app/utils/storage.py`

Frontend:
- static HTML/JS pages under `app/static/`
- `home.html` for hub/map/index/card modal
- `login.html` for auth
- `index.html` for capture and job queue UI
- shared card renderer in `card_renderer.js` and `card_renderer.css`

Persistence:
- schema managed through startup-time additive migrations in `main.py`
- cards, Dex entries, discoveries, and capture jobs in PostgreSQL
- image persistence through R2 or local upload fallback
- browser-side offline queue through IndexedDB

## Key Routes

Page routes:
- `/` -> landing hub
- `/login` -> login/register page
- `/capture` -> capture page, requires auth
- `/wildex` -> landing hub / collection flow, requires auth

API routes:
- `POST /capture` -> queue capture job
- `GET /capture/jobs` -> background job state for current user
- `POST /identify` -> direct identify endpoint
- `GET /cards`
- `GET /cards/{id}`
- `DELETE /cards/{id}`
- `POST /cards/{id}/favorite`
- `POST /cards/{id}/reidentify`
- `GET /wilddex/entries`
- `POST /wilddex/seen`
- `GET /auth/me`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`

## Capture Flow

Happy path:
1. User opens `/capture`.
2. Frontend uploads media to `POST /capture`.
3. Backend persists the uploaded asset to R2 or local fallback and creates a `CaptureJob`.
4. Worker claims queued jobs, groups nearby shots into an encounter where appropriate, identifies species, generates card data, saves a `Card`, syncs to Dex, and updates job state.
5. Frontend polls `/capture/jobs`, shows queue state, and notifies when the card is ready.

Temporary outage path:
1. Upload still creates a job and preserves the media.
2. If identification providers are temporarily unavailable, the job becomes `needs_review` rather than silently failing.
3. If card-writing generation fails, deterministic fallback card data is used so save can still complete.

Offline path:
1. Browser stores media in IndexedDB when offline.
2. App retries queued uploads on reconnect/focus/interval.
3. Synced captures are converted into normal background jobs after upload.

## Capture Job State Model

`CaptureJob` states:
- `queued`
- `processing`
- `complete`
- `failed`
- `needs_review`

Important stored fields:
- uploaded image URL
- grouped encounter metadata
- resolved species/confidence
- `repeat_state` (`new_capture`, `first_capture_after_seen`, `repeat_capture`)
- linked `card_id`
- resolved region
- `region_unlocked`
- failure/review text

## Card System

Card rendering remains code-based, not generated bitmap layouts:
- shared renderer in `app/static/card_renderer.js`
- shared sizing/layout rules in `app/static/card_renderer.css`
- render metadata prepared in `app/services/card_render.py`

Recent renderer-related behavior:
- in-app flip view remains primary
- export/download still supported
- card SVG now scales to fit the viewport shell more safely on mobile
- share flow can export the front face to PNG blob for native share when supported

## Dex / Region Progression

Dex behavior:
- regional entries use `[REGION]-[KINGDOM]-[GROUP]-[NUMBER]`
- states remain `UNKNOWN`, `SEEN`, `CAPTURED`
- map unlock now keys off `CAPTURED`, not merely `SEEN`
- country codes are normalized into the six world regions: `AU`, `NA`, `SA`, `EU`, `AF`, `AS`
- older invalid region values are repaired through backfill

Repeat-state behavior:
- first capture of unseen species -> `new_capture`
- seen entry captured later -> `first_capture_after_seen`
- already captured species found again -> `repeat_capture`

## Storage

Upload persistence:
- primary target: Cloudflare R2
- fallback: local `/uploads`

Current behavior:
- capture save path stores `image_url`
- cards also store `supporting_image_urls` for grouped encounter evidence
- UI/API return persisted URLs instead of depending on temporary preview blobs

## What Was Implemented Most Recently

Most recent local work focused on restoring stable gameplay flow:
- background capture job system added
- grouped encounter processing added
- Dex sync and repeat-state tracking added
- stricter region unlock normalization/fixups added
- deterministic card fallback added for generation outages
- in-app queue/notification UI added
- share actions added
- favorite-card background behavior preserved

## What Is Working

Based on current source and local verification:
- auth routes and login flow exist
- capture creates background jobs instead of blocking the request
- successful jobs save cards and persist image URLs
- cards appear through `/cards` and `/wilddex/entries`
- repeat-state classification is stored and surfaced
- first capture in a supported region can unlock that region
- hub map/index consume normalized region data
- offline queue exists and syncs into the background job flow
- card sharing and app sharing UI exist with fallbacks

## What Is Incomplete Or Unverified

Still incomplete or not fully signed off:
- true multi-organism separation inside a single image/frame is not complete
- full manual browser/mobile verification pass on the live Render deployment is still required
- background worker is in-process, not an external queue worker
- R2 depends on live Render env configuration; local fallback works when R2 is unavailable
- live Render deployment may still be behind local source until pushed/deployed

## Immediate Next Priority

Highest-priority next step:
1. Push current source to GitHub.
2. Let Render deploy from `master`.
3. Verify live capture/save/unlock/mobile UI against `https://wildex-fsou.onrender.com`.
4. Fix any issues found during live mobile testing before calling the pass complete.

## Exact Files That Matter Most Right Now

- `main.py`
- `app/models.py`
- `app/pipeline/card_generator.py`
- `app/routers/capture.py`
- `app/routers/cards.py`
- `app/routers/dex.py`
- `app/services/capture_jobs.py`
- `app/services/card_render.py`
- `app/services/dex.py`
- `app/services/taxonomy.py`
- `app/utils/storage.py`
- `app/static/home.html`
- `app/static/index.html`
- `app/static/card_renderer.js`
- `app/static/card_renderer.css`

## Verification Caveat

This status reflects current local source and local verification work. It is not the same thing as confirmed live Render behavior until the current commit is deployed to `https://wildex-fsou.onrender.com`.
