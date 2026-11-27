"""Token-auth JSON API for the WildEx Unity mobile app (stage 1).

Additive only: reuses the web app's password hashing, signed session tokens,
card serializer and capture-job pipeline. The token returned by
POST /api/m/login is the same signed session token the web cookie uses, sent
as `Authorization: Bearer <token>`.
"""
from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import desc

from app.auth import create_session_token, parse_session_token, verify_password
from app.database import SessionLocal, db_available
from app.models import Card, User, UserProgression
from app.services.capture_jobs import (
    confirm_capture_job_species,
    create_capture_job,
    get_capture_job_for_user,
    list_capture_jobs_for_user,
    retry_capture_job,
)
from app.utils.card_serializer import card_to_dict
from app.utils.media_urls import is_remote_media_url, local_upload_path_from_url

router = APIRouter(prefix="/api/m", tags=["mobile"])

API_VERSION = 1
XP_PER_CARD = 100
XP_PER_LEVEL = 500

# ---------------------------------------------------------------- auth

def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def require_mobile_user(request: Request) -> User:
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    user_id = parse_session_token(_bearer_token(request))
    if not user_id:
        raise HTTPException(401, "Sign in required")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
    if user is None:
        raise HTTPException(401, "Sign in required")
    return user


@router.get("/ping")
def ping():
    return {"ok": True, "api": API_VERSION}


@router.post("/login")
def login(payload: dict = Body(default={})):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    email = str((payload or {}).get("email") or "").strip().lower()
    password = str((payload or {}).get("password") or "")
    if not email or "@" not in email or not password:
        raise HTTPException(400, "Enter your email and password")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")
        return {"ok": True, "token": create_session_token(user.id), "user": {"id": user.id, "email": user.email}}
    finally:
        db.close()


@router.get("/me")
def me(user: User = Depends(require_mobile_user)):
    db = SessionLocal()
    try:
        count = db.query(Card).filter(Card.owner_id == user.id).count()
        prog = db.query(UserProgression).filter(UserProgression.user_id == user.id).first()
    finally:
        db.close()
    # Stage-1 placeholder progression: stored values if present, else derived from card count.
    xp = int(prog.xp) if prog and prog.xp else count * XP_PER_CARD
    level = int(prog.level) if prog and prog.level and prog.level > 1 else 1 + xp // XP_PER_LEVEL
    return {
        "id": user.id,
        "email": user.email,
        "card_count": count,
        "level": level,
        "xp": xp,
        "xp_into_level": xp % XP_PER_LEVEL,
        "xp_per_level": XP_PER_LEVEL,
    }

# ---------------------------------------------------------------- field-guide mapping (mirrors card_renderer.js fg*)

FG_BIOMES = [
    (r"polar|ice|snow|tundra|antarctic|arctic", "polar"),
    (r"urban|city|suburb|town|garden|park", "urban"),
    (r"coast|beach|dune|mangrove|estuar|shore|intertidal", "coastal"),
    (r"marine|ocean|reef|sea\b|pelagic|current", "marine"),
    (r"fresh|river|lake|wetland|swamp|creek|pond|billabong", "freshwater"),
    (r"rock|range|gorge|escarpment|outcrop|ironstone|pilbara", "rocky"),
    (r"mountain|alpine|highland|cliff|montane", "mountain"),
    (r"arid|desert|spinifex|sand|outback|grassland|savann|mallee|plain", "arid"),
    (r"forest|wood|rainforest|eucalypt|bush|jungle|scrub|canopy|botanical", "forest"),
]
FG_CLASS_TAXON = {
    "reptile": "Reptilia", "bird": "Aves", "mammal": "Mammalia", "fish": "Actinopterygii",
    "insect": "Insecta", "arachnid": "Arachnida", "amphibian": "Amphibia", "plant": "Magnoliopsida",
}


def _fg_biome(d: dict) -> str:
    if d.get("biome_frame"):
        return str(d["biome_frame"])
    for hay in (d.get("biome") or "", d.get("habitat_text") or ""):
        for pat, key in FG_BIOMES:
            if re.search(pat, hay, re.I):
                return key
    k = str(d.get("kingdom") or d.get("type_label") or "").lower()
    if k == "fish" or d.get("range_mode") == "ocean":
        return "marine"
    if k == "reptile":
        return "rocky"
    return "forest"


def _fg_group(d: dict) -> str:
    k = str(d.get("kingdom") or d.get("type_label") or "").lower()
    name = f"{d.get('species_name') or ''} {d.get('common_name') or ''}".lower()
    tax = d.get("taxonomy") or {}
    fam = str(tax.get("family") or "").lower()
    if re.search(r"python|snake|adder|taipan|boa|viper|cobra|serpent", name) or re.search(r"pythonidae|elapidae|colubridae|boidae|viperidae|typhlopidae", fam):
        return "snake"
    if re.search(r"spider|scorpion|tick|mite", name) or str(tax.get("class") or "") == "Arachnida":
        return "arachnid"
    if re.search(r"butterfly|moth", name):
        return "butterfly"
    if re.search(r"frog|toad|salamander|newt", name) or k == "amphibian":
        return "amphibian"
    if re.search(r"eagle|hawk|falcon|kite|owl|osprey|harrier", name):
        return "raptor"
    if re.search(r"whale|dolphin|seal|dugong|sea lion|porpoise", name):
        return "marine-mammal"
    if k in {"reptile", "bird", "mammal", "fish", "insect", "plant"}:
        return k
    return "other"


def _fg_class_key(group: str) -> str:
    return {"snake": "reptile", "raptor": "bird", "butterfly": "insect", "marine-mammal": "mammal"}.get(group, group)


def _fg_taxonomy(d: dict, group: str) -> list[dict]:
    t = d.get("taxonomy") or {}
    cls = _fg_class_key(group)
    plant = cls == "plant"
    phylum = t.get("phylum") or ("Tracheophyta" if plant else ("Arthropoda" if cls in {"insect", "arachnid"} else ("\u2014" if cls == "other" else "Chordata")))
    return [
        {"label": "Kingdom", "value": t.get("kingdom") or ("Plantae" if plant else "Animalia")},
        {"label": "Phylum", "value": phylum},
        {"label": "Class", "value": t.get("class") or FG_CLASS_TAXON.get(cls) or "\u2014"},
        {"label": "Order", "value": t.get("order") or "\u2014"},
        {"label": "Family", "value": t.get("family") or "\u2014"},
    ]


def _fg_number(d: dict) -> str:
    raw = str(d.get("card_number") or d.get("wildex_id") or d.get("dex_id") or d.get("card_id") or "")
    m = re.search(r"(\d+)\s*$", raw)
    return str(int(m.group(1))) if m else (raw[-3:] or "?")


def _mobile_card(c: Card, *, full: bool) -> dict:
    base = card_to_dict(c)
    rc = dict(base.get("render_card") or {})
    rc.setdefault("species_name", base.get("species_name"))
    group = _fg_group(rc)
    biome = _fg_biome(rc)
    title = rc.get("species_name") or rc.get("common_name") or rc.get("scientific_name") or "Unknown species"
    sci = rc.get("scientific_name") if rc.get("scientific_name") and rc.get("scientific_name") != title else ""
    out = {
        "id": c.id,
        "wildex_id": c.wildex_id,
        "number": _fg_number(rc),
        "title": title,
        "scientific_name": sci,
        "rarity": rc.get("rarity") or base.get("rarity_display") or "Common",
        "frame": biome,
        "group": group,
        "class_medallion": group,
        "biome_medallion": biome,
        "captured_at": base.get("captured_at"),
        "photo_url": f"/api/m/cards/{c.id}/photo",
        "thumb_url": f"/api/m/cards/{c.id}/photo?w=360",
    }
    if full:
        out.update({
            "taxonomy": _fg_taxonomy(rc, group),
            "stats": {"speed": rc.get("spd"), "defence": rc.get("def"), "attack": rc.get("atk"), "hp": rc.get("hp")},
            "info_text": rc.get("info_text") or base.get("blurb") or "",
            "fact_text": rc.get("fact_text") or "",
            "range_label": rc.get("range_label") or "",
            "biome": rc.get("biome") or base.get("biome"),
            "habitat_text": rc.get("habitat_text"),
            "diet_text": rc.get("diet_text"),
            "length_text": rc.get("length_text"),
            "abilities": rc.get("abilities") or [],
            "threat_level": rc.get("threat_level"),
            "sketch": "snake" if group == "snake" else None,
            "map_url": f"/api/m/cards/{c.id}/map.png",
            "provisional": base.get("provisional"),
        })
    return out


def _own_card(db, user: User, card_id: int) -> Card:
    row = db.query(Card).filter(Card.id == card_id, Card.owner_id == user.id).first()
    if not row:
        raise HTTPException(404, "Card not found")
    return row


@router.get("/cards")
def my_cards(user: User = Depends(require_mobile_user)):
    db = SessionLocal()
    try:
        rows = db.query(Card).filter(Card.owner_id == user.id).order_by(desc(Card.captured_at)).all()
        return {"cards": [_mobile_card(r, full=False) for r in rows]}
    finally:
        db.close()


@router.get("/cards/{card_id}")
def card_detail(card_id: int, user: User = Depends(require_mobile_user)):
    db = SessionLocal()
    try:
        return _mobile_card(_own_card(db, user, card_id), full=True)
    finally:
        db.close()

# ---------------------------------------------------------------- photo (JPEG, resized for phones)

def _load_image_bytes(url: str) -> bytes:
    if url.startswith("/uploads/"):
        path = local_upload_path_from_url(url)
        if not path.exists():
            raise HTTPException(404, "Photo file missing")
        return path.read_bytes()
    if not is_remote_media_url(url):
        raise HTTPException(404, "No photo")
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.content
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Photo could not be loaded") from exc


@router.get("/cards/{card_id}/photo")
def card_photo(card_id: int, w: int = Query(1280, ge=64, le=2048), user: User = Depends(require_mobile_user)):
    db = SessionLocal()
    try:
        row = _own_card(db, user, card_id)
        url = row.primary_card_image_url or row.image_url or row.original_image_url
    finally:
        db.close()
    if not url:
        raise HTTPException(404, "No photo")
    raw = _load_image_bytes(url)
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((w, w))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=86)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

# ---------------------------------------------------------------- FOUND IN map (PNG port of fgMap)

_JS = Path("app/static/card_renderer.js")


@lru_cache(maxsize=1)
def _world_paths() -> dict[str, list[list[tuple[float, float]]]]:
    import json

    src = _JS.read_text(encoding="utf-8")
    m = re.search(r"const MAP_WORLD = (\{.*?\});", src)
    world = json.loads(m.group(1)) if m else {}
    out = {}
    for key, d in world.items():
        polys = []
        for chunk in re.findall(r"M([^MZ]+)Z?", d):
            nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", chunk)]
            pts = list(zip(nums[0::2], nums[1::2]))
            if len(pts) >= 3:
                polys.append(pts)
        out[key] = polys
    return out


@lru_cache(maxsize=1)
def _iso_continent() -> dict:
    import json

    m = re.search(r"const MAP_ISO_CONTINENT = (\{.*?\});", _JS.read_text(encoding="utf-8"))
    return json.loads(m.group(1)) if m else {}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


RANGE_COLOURS = [
    (r"polar|ice|snow|tundra|antarctic|arctic", "#5aa8d8"), (r"urban|city|suburb|park|garden|town", "#7c8794"),
    (r"coast|beach|dune|mangrove|estuar|shore|intertidal", "#22a89a"), (r"marine|ocean|reef|sea|pelagic", "#1f6fb8"),
    (r"fresh|river|lake|wetland|swamp|creek|pond|billabong", "#2c9fc8"), (r"mountain|alpine|highland|cliff|montane", "#7d68b8"),
    (r"rock|range|gorge|escarpment|outcrop", "#b0643a"), (r"arid|desert|spinifex|sand|outback|grassland|scrub|mallee", "#d88a2c"),
    (r"forest|wood|rainforest|eucalypt|bush|jungle", "#3f9a3e"),
]


def _range_colour(d: dict) -> str:
    if d.get("range_colour"):
        return d["range_colour"]
    if d.get("range_mode") == "ocean":
        return "#1f6fb8"
    for hay in (d.get("biome") or "", d.get("habitat_text") or ""):
        for pat, col in RANGE_COLOURS:
            if re.search(pat, hay, re.I):
                return col
    return "#c07830"


def render_found_in_map(d: dict, width: int = 640, height: int = 250) -> bytes:
    from PIL import Image, ImageDraw

    ss = 3  # supersample
    W, H = width * ss, height * ss
    # SVG viewBox "0 27 200 78", xMidYMid slice
    vb_x, vb_y, vb_w, vb_h = 0.0, 27.0, 200.0, 78.0
    scale = max(W / vb_w, H / vb_h)
    off_x = (W - vb_w * scale) / 2 - vb_x * scale
    off_y = (H - vb_h * scale) / 2 - vb_y * scale

    def P(x, y, ty=10.0):
        return (off_x + x * scale, off_y + (y + ty) * scale)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img, "RGBA")
    world = _world_paths()
    regs = set(d.get("range_regions") or [])
    hl: set[str] = set()
    col = _range_colour(d)
    if d.get("range_mode") == "ocean":
        dr.rectangle([0, 0, W, H], fill=_hex(col) + (int(255 * 0.28),))
    else:
        if not regs or "GLOBAL" in regs:
            hl.update(world.keys())
        iso = _iso_continent()
        for r in regs:
            if r in world:
                hl.add(r)
            elif r in iso:
                hl.add(iso[r])
    # graticule
    gcol = _hex("#7a5d3a") + (56,)
    for gy in (40, 60, 80, 100):
        dr.line([P(0, gy, 0), P(200, gy, 0)], fill=gcol, width=max(1, int(0.25 * scale)))
    for gx in (40, 80, 120, 160):
        dr.line([P(gx, 0, 0), P(gx, 130, 0)], fill=gcol, width=max(1, int(0.25 * scale)))
    polys = d.get("range_polygons") or []
    use_polys = bool(polys) and "AU" in hl
    for key, plist in world.items():
        on = key in hl
        fill = _hex("#d7b98a") + (255,) if (on and use_polys) else (_hex(col) + (217,) if on else _hex("#bfa575") + (255,))
        stroke = _hex("#3a2410" if on else "#7a5d3a") + (255,)
        sw = max(1, round((0.5 if on else 0.35) * scale))
        for poly in plist:
            pts = [P(x, y) for x, y in poly]
            dr.polygon(pts, fill=fill)
            dr.line(pts + [pts[0]], fill=stroke, width=sw, joint="curve")
    X = lambda lon: (float(lon) + 180) * 200 / 360
    Y = lambda lat: 56.4 + (-float(lat)) * 0.768
    ring = None
    if use_polys:
        allpts = []
        for poly in polys:
            pts = [P(X(p[0]), Y(p[1])) for p in poly]
            allpts += [(X(p[0]), Y(p[1])) for p in poly]
            dr.polygon(pts, fill=_hex("#8e2f12") + (255,))
            dr.line(pts + [pts[0]], fill=_hex("#3a1606") + (255,), width=max(1, round(0.4 * scale)))
        ring = (sum(p[0] for p in allpts) / len(allpts), sum(p[1] for p in allpts) / len(allpts))
    elif len(hl) == 1:
        k = next(iter(hl))
        xs = [x for poly in world[k] for x, _ in poly]
        ys = [y for poly in world[k] for _, y in poly]
        ring = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    if ring:
        cx, cy = P(*ring)
        r = 5.4 * scale
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_hex("#2b1a0e") + (255,), width=max(1, round(0.9 * scale)))
    img = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@router.get("/cards/{card_id}/map.png")
def card_map(card_id: int, user: User = Depends(require_mobile_user)):
    db = SessionLocal()
    try:
        rc = card_to_dict(_own_card(db, user, card_id)).get("render_card") or {}
    finally:
        db.close()
    return Response(render_found_in_map(rc), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

# ---------------------------------------------------------------- capture (reuses the web capture-job pipeline)

@router.post("/capture")
async def upload_capture(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    user: User = Depends(require_mobile_user),
):
    content = await file.read()
    try:
        job = create_capture_job(owner_id=user.id, content=content, content_type=file.content_type, lat=lat, lon=lon)
    except ValueError as exc:
        raise HTTPException(415 if str(exc).startswith("Unsupported image type:") else 400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"ok": job["status"] != "failed", "job": _job_view(job)}


def _job_view(job: dict) -> dict:
    keep = ("id", "status", "species_name", "scientific_name", "confidence", "card_id", "error_message", "review_reason", "alternatives", "created_at", "updated_at")
    return {k: job.get(k) for k in keep}


@router.get("/capture/jobs")
def capture_jobs(limit: int = Query(20, ge=1, le=100), user: User = Depends(require_mobile_user)):
    data = list_capture_jobs_for_user(user.id, include_secondary=False, limit=limit)
    jobs = data.get("items", []) if isinstance(data, dict) else data
    return {"jobs": [_job_view(j) for j in (jobs or [])]}


@router.get("/capture/jobs/{job_id}")
def capture_job(job_id: int, user: User = Depends(require_mobile_user)):
    job = get_capture_job_for_user(user.id, job_id)
    if job is None:
        raise HTTPException(404, "Capture job not found")
    return {"job": _job_view(job)}


@router.post("/capture/jobs/{job_id}/confirm-species")
def confirm_species(job_id: int, payload: dict = Body(default={}), user: User = Depends(require_mobile_user)):
    """'I know what it is' manual ID for needs_review captures."""
    try:
        result = confirm_capture_job_species(
            user_id=user.id,
            job_id=job_id,
            scientific_name=(payload or {}).get("scientific_name"),
            common_name=(payload or {}).get("common_name"),
            sub_category=(payload or {}).get("sub_category"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"ok": True, **result}


@router.post("/capture/jobs/{job_id}/retry")
def retry_job(job_id: int, user: User = Depends(require_mobile_user)):
    try:
        job = retry_capture_job(user_id=user.id, job_id=job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"ok": True, "job": _job_view(job)}
