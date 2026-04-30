import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-001")
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash,gemini-1.5-flash").split(",")
    if model.strip()
]
GROK_API_KEY = os.getenv("GROK_API_KEY")
INATURALIST_API_KEY = os.getenv("INATURALIST_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("SECRET_KEY") or "wildex-dev-session-secret"
if (
    SESSION_SECRET == "wildex-dev-session-secret"
    and (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower() in {"prod", "production"}
):
    raise RuntimeError("SESSION_SECRET must be set in production.")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "wildex_session")
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", "2592000"))
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
PASSWORD_RESET_TOKEN_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TOKEN_TTL_SECONDS", "3600"))
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
EMAIL_FROM = os.getenv("EMAIL_FROM") or SMTP_USERNAME or "no-reply@wildex.local"
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
}
SUBMISSION_CLEAR_THRESHOLD = float(os.getenv("SUBMISSION_CLEAR_THRESHOLD", "0.90"))
SUBMISSION_REJECT_THRESHOLD = float(os.getenv("SUBMISSION_REJECT_THRESHOLD", "0.45"))
DR_AGENT_ENGINE = os.getenv("DR_AGENT_ENGINE", "gemma").strip().lower()
DR_GEMMA_MODEL = os.getenv("DR_GEMMA_MODEL", "models/gemma-2-2b-it")
DR_GEMMA_LOCAL_FILES_ONLY = os.getenv("DR_GEMMA_LOCAL_FILES_ONLY", "true").lower() in {"1", "true", "yes", "on"}
DR_GEMMA_MAX_NEW_TOKENS = int(os.getenv("DR_GEMMA_MAX_NEW_TOKENS", "220"))
