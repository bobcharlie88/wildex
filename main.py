import logging
import os
import socket

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.routers.capture import router as capture_router
from app.routers.cards import router as cards_router
from app.routers.wildex import router as wildex_router

log = logging.getLogger("wildex")

app = FastAPI(title="WildEx API", version="0.1.0")
app.include_router(capture_router)
app.include_router(cards_router)
app.include_router(wildex_router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def startup():
    # Import models so SQLAlchemy registers them before create_all
    import app.models  # noqa: F401
    from app.database import create_tables, db_available
    if db_available():
        try:
            create_tables()
            log.info("Database tables ready")
            # Migrate: add columns introduced after initial schema
            from app.database import engine
            with engine.connect() as conn:
                from sqlalchemy import text
                for col, typedef in [
                    ("category",     "VARCHAR(50)"),
                    ("sub_category", "VARCHAR(100)"),
                    ("image_url",    "VARCHAR(1000)"),
                ]:
                    try:
                        conn.execute(text(f"ALTER TABLE cards ADD COLUMN IF NOT EXISTS {col} {typedef}"))
                        conn.commit()
                    except Exception:
                        conn.rollback()
        except Exception as e:
            log.warning(f"Could not create tables: {e}")
    else:
        log.warning(
            "Database not reachable — cards will not be saved. "
            "See README for PostgreSQL setup."
        )


@app.get("/")
def root():
    return FileResponse("app/static/home.html")


@app.get("/capture")
def capture_page():
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
