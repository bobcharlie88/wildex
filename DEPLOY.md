# Deploying WildEx to Render

This project is configured for Render using `render.yaml`.

## Required Render Environment Variables

Set these in the Render dashboard or through Blueprint secret prompts:

```env
DATABASE_URL=
SESSION_SECRET=
GEMINI_API_KEY=
INATURALIST_API_KEY=
GOOGLE_VISION_API_KEY=
GOOGLE_PLACES_API_KEY=
GROK_API_KEY=
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_BASE_URL=
```

Do not commit real values for these variables.

## Storage

WildEx uses Cloudflare R2 through the S3-compatible `boto3` client. The app does
not read `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`, or
`USE_S3_STORAGE`.

If R2 is not configured, uploads fall back to local `uploads/` storage. That is
fine for local development, but not for Render production because local disk is
ephemeral.

## Dr Agent

Render defaults `DR_AGENT_ENGINE=rule_based` in `render.yaml` so the web service
does not try to load local Gemma weights that are not present on the server.

For an offline/local machine, set:

```env
DR_AGENT_ENGINE=gemma
DR_GEMMA_MODEL=models/gemma-2-2b-it
DR_GEMMA_LOCAL_FILES_ONLY=true
```

See `OFFLINE_GEMMA.md` for local Gemma setup.

## Deploy Steps

1. Push the repo to GitHub.
2. In Render, create a new Blueprint from this repo.
3. Fill in all secret environment variables when prompted.
4. Deploy the web service.
5. Open `/health`; production should return `{"status":"healthy","database":true}`.

## Local Development

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Local `.env`, `uploads/`, `models/`, and Python cache files are intentionally
ignored by Git.
