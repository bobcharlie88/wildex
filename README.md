# WildEx
A real-world wildlife discovery and battle game where players film actual animals to build their collection.

## Features
- Live video capture with GPS and device metadata
- AI-powered species identification using iNaturalist and Google Vision
- Dynamic card generation with biology-based stats
- Personal WildDex encyclopedia
- Collection milestones and achievements
- **Offline AI Dr Agent** powered by Google Gemma for contextual wildlife guidance

## Tech Stack
- **Backend**: Python FastAPI
- **Database**: PostgreSQL
- **AI Services**: Gemini Flash, Grok Imagine, Google Vision, **Google Gemma (offline)**
- **Species Data**: iNaturalist API, GBIF API
- **Deployment**: Render (with Cloudflare R2-compatible object storage)

## Local Development
1. Install dependencies: `pip install -r requirements.txt`
2. Set up environment variables in `.env`
3. Run: `uvicorn main:app --reload`

## Dr Agent (AI Assistant)
The Dr Agent provides contextual wildlife guidance and can run offline using Google Gemma:

### Rule-Based Mode
Use `DR_AGENT_ENGINE=rule_based` for a lightweight deterministic assistant. This
is the Render default because production servers do not include local Gemma
weights.

### Offline Mode (Gemma)
Set `DR_AGENT_ENGINE=gemma` in environment variables for fully offline operation.

**Environment Variables for Offline Mode:**
```env
DR_AGENT_ENGINE=gemma
DR_GEMMA_MODEL=models/gemma-2-2b-it
DR_GEMMA_LOCAL_FILES_ONLY=true
DR_GEMMA_MAX_NEW_TOKENS=220
```

The system automatically falls back to rule-based responses if the Gemma model cannot be loaded.

## Deployment
See `DEPLOY.md` for Render deployment instructions. Keep API keys and database URLs in Render environment variables, not in Git.
