import logging
import os
import socket

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from app.auth import get_current_user
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.capture import router as capture_router
from app.routers.cards import router as cards_router
from app.routers.dex import router as dex_router
from app.routers.wildex import router as wildex_router
from app.services.capture_jobs import start_capture_worker, stop_capture_worker

log = logging.getLogger("wildex")

app = FastAPI(title="WildEx API", version="0.1.0")
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(capture_router)
app.include_router(cards_router)
app.include_router(dex_router)
app.include_router(wildex_router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def startup():
    # Import models so SQLAlchemy registers them before create_all
    import app.models  # noqa: F401
    from app.database import SessionLocal, create_tables, db_available
    from app.services.card_templates import ensure_builtin_templates
    if db_available():
        try:
            create_tables()
            log.info("Database tables ready")
            # Migrate: add columns introduced after initial schema
            from app.database import engine
            with engine.connect() as conn:
                from sqlalchemy import text
                for col, typedef in [
                    ("owner_id",     "INTEGER"),
                    ("category",     "VARCHAR(50)"),
                    ("sub_category", "VARCHAR(100)"),
                    ("image_url",    "VARCHAR(1000)"),
                    ("supporting_image_urls", "TEXT"),
                    ("rarity_display", "VARCHAR(50)"),
                    ("threat_level", "VARCHAR(32)"),
                    ("aggression", "VARCHAR(32)"),
                    ("biome", "VARCHAR(120)"),
                    ("biome_bonus", "VARCHAR(255)"),
                    ("strength_name", "VARCHAR(120)"),
                    ("strength_effect", "VARCHAR(255)"),
                    ("weakness_name", "VARCHAR(120)"),
                    ("weakness_effect", "VARCHAR(255)"),
                    ("sound_url", "VARCHAR(1000)"),
                    ("original_image_url", "VARCHAR(1000)"),
                    ("primary_card_image_url", "VARCHAR(1000)"),
                    ("dex_entry_id", "INTEGER"),
                    ("dex_id",       "VARCHAR(32)"),
                    ("discovery_state", "VARCHAR(20)"),
                    ("region",       "VARCHAR(8)"),
                    ("kingdom",      "VARCHAR(32)"),
                    ("group_code",   "VARCHAR(32)"),
                    ("evolution_chain_id", "VARCHAR(255)"),
                    ("evolution_stage", "INTEGER"),
                    ("front_template_name", "VARCHAR(120)"),
                    ("front_template_version", "VARCHAR(32)"),
                    ("back_template_name", "VARCHAR(120)"),
                    ("back_template_version", "VARCHAR(32)"),
                ]:
                    try:
                        conn.execute(text(f"ALTER TABLE cards ADD COLUMN IF NOT EXISTS {col} {typedef}"))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_card_id INTEGER"))
                    conn.commit()
                except Exception:
                    conn.rollback()
                for col, typedef in [
                    ("media_type", "VARCHAR(32)"),
                    ("original_image_url", "VARCHAR(1000)"),
                    ("primary_image_url", "VARCHAR(1000)"),
                    ("image_url", "VARCHAR(1000)"),
                    ("latitude", "FLOAT"),
                    ("longitude", "FLOAT"),
                    ("encounter_id", "VARCHAR(64)"),
                    ("primary_job_id", "INTEGER"),
                    ("grouped_job_ids", "TEXT"),
                    ("grouped_count", "INTEGER DEFAULT 1"),
                    ("species_name", "VARCHAR(200)"),
                    ("scientific_name", "VARCHAR(200)"),
                    ("confidence", "FLOAT"),
                    ("provisional", "BOOLEAN DEFAULT FALSE"),
                    ("repeat_state", "VARCHAR(32)"),
                    ("card_id", "INTEGER"),
                    ("region", "VARCHAR(8)"),
                    ("region_unlocked", "BOOLEAN DEFAULT FALSE"),
                    ("error_message", "TEXT"),
                    ("review_reason", "TEXT"),
                    ("supporting_image_urls", "TEXT"),
                    ("started_at", "TIMESTAMP"),
                    ("completed_at", "TIMESTAMP"),
                    ("updated_at", "TIMESTAMP"),
                ]:
                    try:
                        conn.execute(text(f"ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS {col} {typedef}"))
                        conn.commit()
                    except Exception:
                        conn.rollback()
            db = SessionLocal()
            try:
                ensure_builtin_templates(db)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            log.warning(f"Could not create tables: {e}")
    else:
        log.warning(
            "Database not reachable — cards will not be saved. "
            "See README for PostgreSQL setup."
        )


    start_capture_worker()


@app.on_event("shutdown")
def shutdown():
    stop_capture_worker()


@app.get("/")
def root():
    return FileResponse("app/static/home.html")


@app.get("/capture")
def capture_page(request: Request):
    if get_current_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse("app/static/index.html")


@app.get("/health")
def health():
    from app.database import db_available
    return {"status": "healthy", "database": db_available()}


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    ip = _local_ip()
    print(f"\n  WildEx running at:")
    print(f"  Local  -> http://127.0.0.1:{port}")
    print(f"  WiFi   -> http://{ip}:{port}\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
