# WildEx Project Status

## Current System Summary

WildEx is a FastAPI-based mobile web app for capturing wildlife or plant observations, identifying them with a multi-provider vision pipeline, generating collectible cards, and storing them in a per-user WildDex.

Current major capabilities in the repo:
- user registration/login with signed session cookies
- authenticated capture flow
- per-user card ownership and per-user WildDex browsing
- image upload persistence to Cloudflare R2 with `image_url` stored in the database
- multi-step species identification with fallback providers
- provisional "Pending identification" saves when identification is temporarily unavailable
- offline capture queue in the browser using IndexedDB, with later sync when reception returns

This file is intended as the handoff point for the next context window. It reflects local source state, not guaranteed live deployment state.

## Architecture And Stack

Backend:
- FastAPI app entrypoint in `main.py`
- SQLAlchemy models in `app/models.py`
- capture, cards, auth, and WildDex routers under `app/routers/`
- identification and enrichment pipeline under `app/pipeline/`
- Cloudflare R2 upload helper in `app/utils/storage.py`

Frontend:
- static HTML/JS pages under `app/static/`
- `home.html` for landing/account state
- `login.html` for auth
- `index.html` for capture/upload/offline queue
- `wildex.html` for browsing saved cards

Persistence:
- database schema is managed by startup-time additive migrations in `main.py`
- images are uploaded to R2 and persisted by URL
- browser-side offline queue uses IndexedDB

## Key Routes

Page routes:
- `/` -> home page
- `/login` -> login/register page
- `/capture` -> capture page, requires auth
- `/wildex` -> WildDex page, requires auth

API routes:
- `POST /capture` -> upload image/video, identify, generate/store card
- `POST /identify` -> direct identify endpoint, now returns `503` for temporary provider outages
- `GET /cards` -> current user's cards
- `GET /cards/{id}` -> current user's card detail
- `GET /auth/me` -> current session state
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`

## Capture Flow

Authenticated happy-path flow:
1. User opens `/capture`.
2. Frontend captures or uploads media.
3. Frontend posts to `POST /capture`.
4. Backend uploads the asset to R2.
5. Backend runs species identification with provider fallbacks.
6. Backend enriches data and generates a card payload.
7. Card is saved with `owner_id` and `image_url`.
8. Frontend renders the result and prefers persisted `image_url` over a temporary local blob.

Temporary-outage flow:
1. Identification providers fail with temporary outage/rate-limit style errors.
2. Backend retries temporary failures.
3. If still unavailable, backend saves a provisional "Pending identification" card instead of losing the capture.
4. The saved card still carries the persisted image URL if upload succeeded.

Offline flow:
1. If the browser is offline or upload fails due to reception drop, the capture is stored in IndexedDB.
2. The app retries queued captures when connectivity returns, on focus, and on a timed interval.
3. Queued media is normalized back into a `File` before re-upload.

## Card Generation Flow

Identification and card creation are split across pipeline modules:
- `app/pipeline/species_id.py` handles species/provider identification, confidence handling, and fallback logic.
- `app/pipeline/species_data.py` enriches with species metadata.
- `app/pipeline/card_generator.py` builds the final card fields/stat presentation.

Important current identification order:
1. Gemini
2. iNaturalist CV
3. Google Vision label/object path
4. Google Vision web detection
5. If all usable providers are temporarily unavailable, save pending for later follow-up instead of hard-failing

Plant ID has been tightened compared with earlier repo state:
- stronger plant-specific prompt guidance
- generic labels like "plant" / "weed" are treated as weak
- plant enrichment uses more plant-aware lookup constraints
- plant subcategory inference is improved

## Database And Storage Flow

Database:
- `cards` table stores generated captures
- `users` table stores account records
- `cards.owner_id` links cards to a specific user
- `cards.image_url` stores the persisted R2 image URL
- additive schema checks for `owner_id` and `image_url` happen at startup in `main.py`

Storage:
- captured assets are uploaded to Cloudflare R2 through `app/utils/storage.py`
- previously, frontend display depended on local preview blobs
- current code persists the remote image URL and surfaces it back through the API/UI

## Frontend Pages And How They Connect

`app/static/home.html`
- entry page
- checks auth state
- surfaces queue status
- links authenticated users into capture and WildDex
- also participates in processing the offline queue

`app/static/login.html`
- login/register UI
- talks to `/auth/login` and `/auth/register`
- redirects into the main app after success

`app/static/index.html`
- capture page
- handles media upload
- handles offline queueing and queue replay
- calls backend capture flow
- renders result cards
- prefers persisted `image_url` when present

`app/static/wildex.html`
- WildDex browser
- fetches current user's cards only
- uses `image_url` for rendered card media

## What Was Implemented Most Recently

Most recent repo direction is not battle systems or redesign work. It is resilience and persistence:
- Cloudflare R2 image persistence integration completed through capture save/display path
- identification fallback chain expanded to four providers before pending-save fallback
- temporary provider outage handling hardened
- per-user auth and card ownership added
- plant-ID quality improvements added
- offline capture queue added and then tightened so it retries from more than one page

## Cloudflare R2 Image Persistence Status

Previous save behavior:
- frontend could rely on local blob previews
- persistence of image URLs through the DB/UI path was incomplete or not fully wired through the result screen

Files changed for R2-related persistence:
- `app/utils/storage.py`
- `app/routers/capture.py`
- `app/models.py`
- `app/routers/cards.py`
- `app/static/index.html`
- `app/static/wildex.html`
- `main.py`

Current status checks:
- `boto3` is present in `requirements.txt`
- `image_url` is written to the database from capture flow
- `image_url` exists on the model and startup migration path
- frontend WildDex uses `image_url`
- capture result page now prefers `image_url` and falls back to local preview if needed

Remaining risks:
- not runtime-verified in this shell because there is no callable `python` or `py` on PATH
- live deployment may still be behind local code
- if R2 env/config is missing in deployment, upload can still fail independently of identification

## What Is Working

Based on current source:
- auth routes and login page exist
- user-specific card separation is implemented
- capture flow writes `owner_id`
- image persistence path to R2 is wired through capture, DB, API, and frontend
- result screen and WildDex both support persisted `image_url`
- offline queue exists and retries queued uploads
- temporary identification outages are classified and handled more safely
- four-provider fallback order exists before pending-save fallback
- plant identification heuristics are improved over earlier generic behavior

## What Is Incomplete Or Unverified

Still incomplete or not yet proven end-to-end here:
- no test execution in this shell because `python`/`py` is unavailable
- no live deployment verification from this environment
- pending-identification cards are saved, but there is not yet a dedicated later reprocessing worker for them
- offline queue exists client-side, but broader operational UX around queue inspection/management is still thin
- provider fallbacks depend on deployment env keys and external service availability

## Unfinished Work / TODO / Partial Integration To Watch

Known partial areas:
- deployment validation is still needed for auth cookies, R2 env vars, and provider keys
- pending identification is persisted, but automatic server-side later re-identification is not built
- offline queue currently focuses on sync/retry, not a full queue management page
- older prototype or experimental logic may still exist around legacy capture/display assumptions

The main risk is not missing code wiring inside the repo. The main risk is mismatched live config or undeployed local changes.

## Immediate Next Priority

Highest-priority safe next step:
1. Deploy and verify the current persistence/redundancy build end-to-end.
2. Confirm R2 uploads succeed in the live environment.
3. Confirm a temporary ID outage results in a saved pending card rather than a fatal red failure screen.
4. Confirm queued offline captures eventually upload and retain their image in the saved card.

If more code work is needed after that, the next tightly scoped storage-related task should be:
- add a safe server-side reprocessing path for pending identification records so captures saved during outages can be completed later without user loss

## Exact Files That Matter Most Right Now

- `main.py`
- `app/config.py`
- `app/models.py`
- `app/auth.py`
- `app/routers/auth.py`
- `app/routers/capture.py`
- `app/routers/cards.py`
- `app/routers/wildex.py`
- `app/pipeline/species_id.py`
- `app/utils/storage.py`
- `app/static/home.html`
- `app/static/login.html`
- `app/static/index.html`
- `app/static/wildex.html`
- `tests/test_species_id.py`

## Verification Caveat

This status reflects source inspection and implemented local changes. It is not the same thing as confirmed live behavior. The biggest unknowns are deployment freshness and environment configuration.
