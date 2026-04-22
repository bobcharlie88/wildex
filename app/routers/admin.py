from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import get_current_user, require_admin_user
from app.database import SessionLocal, db_available
from app.models import Card, CardAsset, CardTemplate, CaptureJob, TemplatePartAssignment, User
from app.services.agents.orchestrator import get_agent_dashboard, run_agent_task
from app.services.card_assets import (
    ALLOWED_ASSET_MIME_TYPES,
    TEMPLATE_PART_SLOTS,
    asset_to_dict,
    list_assets,
    normalize_tags,
    slugify,
)
from app.services.card_render import build_render_card
from app.services.card_templates import clear_template_cache, ensure_builtin_templates, list_templates, select_template
from app.utils.storage import upload_named_bytes

router = APIRouter(prefix="/admin", tags=["admin"])


def _template_to_dict(selection) -> dict:
    return {
        "id": selection.id,
        "name": selection.name,
        "kingdom": selection.kingdom,
        "side": selection.side,
        "asset_path": selection.asset_path,
        "asset_url": selection.asset_url,
        "version": selection.version,
        "slug": selection.slug,
        "category": selection.category,
        "family": selection.family,
        "environment": selection.environment,
        "layout_key": selection.layout_key,
        "config": selection.config or {},
        "active": selection.active,
        "label": selection.label,
        "notes": selection.notes,
        "parts": selection.parts or [],
    }


def _load_template_row(db, template_id: int) -> CardTemplate:
    row = db.query(CardTemplate).filter(CardTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    return row


def _coerce_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON payload: {exc}") from exc


def _fallback_sample(kingdom: str) -> dict:
    base = {
        "species_name": "Preview Species",
        "scientific_name": "Specimen adminus",
        "category": "animal",
        "sub_category": kingdom,
        "iconic_taxon": kingdom,
        "dex_id": "AU-ADM-PRV-001",
        "rarity_display": "Rare",
        "blurb": "Preview card generated from admin template builder.",
        "wikipedia_summary": "Use this preview to validate composition before activation.",
        "observations_count": 42,
        "stats": {"speed": 58, "attack": 61, "defence": 54, "hp": 63},
        "capture_country": "AU",
        "biome": "Preview Habitat",
    }
    if kingdom == "plant":
        base["category"] = "plant"
        base["iconic_taxon"] = "plantae"
    return base


def _card_source(card: Card) -> dict:
    return {
        "id": card.id,
        "species_name": card.species_name,
        "scientific_name": card.scientific_name,
        "rank": card.rank,
        "confidence": card.confidence,
        "provisional": card.provisional,
        "rarity_tier": card.rarity_tier,
        "rarity_display": card.rarity_display,
        "iconic_taxon": card.iconic_taxon,
        "conservation_status": card.conservation_status,
        "observations_count": card.observations_count,
        "blurb": card.blurb,
        "stats": {
            "speed": card.speed,
            "attack": card.attack,
            "defence": card.defence,
            "hp": card.hp,
            "stamina_regen": card.stamina_regen,
        },
        "category": card.category,
        "sub_category": card.sub_category,
        "capture_country": card.capture_country,
        "original_image_url": card.original_image_url or card.primary_card_image_url or card.image_url,
        "primary_card_image_url": card.primary_card_image_url or card.image_url,
        "image_url": card.primary_card_image_url or card.image_url,
        "front_template_name": card.front_template_name,
        "front_template_version": card.front_template_version,
        "back_template_name": card.back_template_name,
        "back_template_version": card.back_template_version,
        "dex_id": card.dex_id,
        "group_code": card.group_code,
        "evolution_chain_id": card.evolution_chain_id,
        "evolution_stage": card.evolution_stage,
        "sound_url": card.sound_url,
        "threat_level": card.threat_level,
        "aggression": card.aggression,
        "biome": card.biome,
        "biome_bonus": card.biome_bonus,
        "strength_name": card.strength_name,
        "strength_effect": card.strength_effect,
        "weakness_name": card.weakness_name,
        "weakness_effect": card.weakness_effect,
    }


@router.get("/login")
def admin_login_page():
    return FileResponse("app/static/admin_login.html")


@router.get("")
def admin_dashboard(request: Request):
    if get_current_user(request) is None:
        return RedirectResponse("/admin/login", status_code=303)
    require_admin_user(request)
    return FileResponse("app/static/admin.html")


@router.get("/me")
def admin_me(current_user: User = Depends(require_admin_user)):
    return {"id": current_user.id, "email": current_user.email}


@router.get("/bootstrap")
def admin_bootstrap(current_user: User = Depends(require_admin_user)):
    items: list[dict] = []
    assets: list[dict] = list_assets()
    samples: list[dict] = []
    if db_available():
        db = SessionLocal()
        try:
            ensure_builtin_templates(db)
            db.query(CardAsset).filter(
                CardAsset.asset_type == "map_asset",
                CardAsset.template_part.is_(None),
            ).update({"template_part": "map_frame"}, synchronize_session=False)
            db.commit()
            items = [_template_to_dict(selection) for selection in list_templates()]
            assets = list_assets()
            rows = (
                db.query(Card)
                .order_by(Card.captured_at.desc(), Card.id.desc())
                .limit(18)
                .all()
            )
            samples = [{
                "id": row.id,
                "species_name": row.species_name,
                "dex_id": row.dex_id,
                "render_card": build_render_card(row),
            } for row in rows]
        finally:
            db.close()
    if not items:
        items = [_template_to_dict(selection) for selection in list_templates()]
    return {
        "user": {"id": current_user.id, "email": current_user.email},
        "templates": items,
        "assets": assets,
        "template_slots": list(TEMPLATE_PART_SLOTS),
        "samples": samples,
        "agents": get_agent_dashboard(),
    }


@router.get("/templates")
def admin_templates(current_user: User = Depends(require_admin_user)):
    if db_available():
        db = SessionLocal()
        try:
            ensure_builtin_templates(db)
            db.commit()
        finally:
            db.close()
    return {"items": [_template_to_dict(selection) for selection in list_templates()]}


@router.post("/assets/upload")
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    asset_type: str = Form(...),
    category: str = Form("default"),
    kingdom: str = Form(""),
    family: str = Form(""),
    environment: str = Form(""),
    side: str = Form(""),
    template_part: str = Form(""),
    version: str = Form("1.0.0"),
    active: bool = Form(True),
    sort_order: int = Form(100),
    tags: str = Form(""),
    notes: str = Form(""),
    replace_asset_id: int | None = Form(None),
    current_user: User = Depends(require_admin_user),
):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload")
    guessed_mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if guessed_mime not in ALLOWED_ASSET_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {guessed_mime}")

    asset_slug = slugify(name)
    normalized_asset_type = (asset_type or "").strip().lower()
    normalized_template_part = (template_part or "").strip().lower()
    if normalized_asset_type == "map_asset" and not normalized_template_part:
        normalized_template_part = "map_frame"
    folder = "/".join(part for part in [asset_type, category or "default"] if part)
    uploaded_url = upload_named_bytes(
        data=data,
        content_type=guessed_mime,
        directory=folder,
        filename=file.filename or f"{asset_slug}{Path(file.filename or '').suffix}",
    )

    db = SessionLocal()
    try:
        if not replace_asset_id:
            existing = (
                db.query(CardAsset)
                .filter(CardAsset.slug == asset_slug, CardAsset.version == (version or "1.0.0").strip())
                .first()
            )
            if existing is not None:
                raise HTTPException(409, "An asset with that slug and version already exists. Use replace instead.")
        if replace_asset_id:
            row = db.query(CardAsset).filter(CardAsset.id == replace_asset_id).first()
            if row is None:
                raise HTTPException(404, "Asset to replace not found")
        else:
            row = CardAsset()
            db.add(row)
        row.name = name.strip()
        row.slug = asset_slug
        row.asset_type = normalized_asset_type
        row.file_path = uploaded_url
        row.mime_type = guessed_mime
        row.kingdom = (kingdom or "").strip().lower() or None
        row.family = (family or "").strip().lower() or None
        row.environment = (environment or "").strip().lower() or None
        row.side = (side or "").strip().lower() or None
        row.template_part = normalized_template_part or None
        row.version = (version or "1.0.0").strip()
        row.active = bool(active)
        row.sort_order = int(sort_order or 100)
        row.tags = normalize_tags(tags)
        row.notes = notes.strip() or None
        row.uploaded_by = current_user.id
        db.commit()
        db.refresh(row)
        clear_template_cache()
        return {"ok": True, "asset": asset_to_dict(row)}
    finally:
        db.close()


@router.post("/assets/{asset_id}/status")
async def update_asset_status(asset_id: int, request: Request, current_user: User = Depends(require_admin_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    payload = await request.json()
    active = bool(payload.get("active"))
    db = SessionLocal()
    try:
        row = db.query(CardAsset).filter(CardAsset.id == asset_id).first()
        if row is None:
            raise HTTPException(404, "Asset not found")
        row.active = active
        db.commit()
        clear_template_cache()
        return {"ok": True, "asset": asset_to_dict(row)}
    finally:
        db.close()


@router.post("/templates")
async def upsert_template(request: Request, current_user: User = Depends(require_admin_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    payload = await request.json()
    template_id = payload.get("id")
    db = SessionLocal()
    try:
        if template_id:
            row = _load_template_row(db, int(template_id))
        else:
            existing = (
                db.query(CardTemplate)
                .filter(
                    CardTemplate.name == ((payload.get("name") or "").strip() or f"{payload.get('kingdom', 'mammal')}-{payload.get('side', 'front')}-{payload.get('version', '1.0.0')}"),
                    CardTemplate.version == (payload.get("version") or "1.0.0").strip(),
                )
                .first()
            )
            if existing is not None:
                raise HTTPException(409, "A template with that name and version already exists")
            row = CardTemplate()
            db.add(row)
        row.name = (payload.get("name") or "").strip() or f"{payload.get('kingdom', 'mammal')}-{payload.get('side', 'front')}-{payload.get('version', '1.0.0')}"
        row.slug = slugify(payload.get("slug") or row.name)
        row.kingdom = (payload.get("kingdom") or "mammal").strip().lower()
        row.side = (payload.get("side") or "front").strip().lower()
        template_asset_path = (payload.get("asset_path") or "").strip()
        if not template_asset_path:
            fallback = select_template(kingdom=row.kingdom, side=row.side)
            template_asset_path = fallback.asset_url
        row.asset_path = template_asset_path
        row.version = (payload.get("version") or row.version or "1.0.0").strip()
        row.category = (payload.get("category") or "").strip().lower() or None
        row.family = (payload.get("family") or "").strip().lower() or None
        row.environment = (payload.get("environment") or "").strip().lower() or None
        row.layout_key = (payload.get("layout_key") or "master-front" if row.side == "front" else "master-back")
        row.config_json = json.dumps(payload.get("config") or {"layout_key": row.layout_key})
        row.label = (payload.get("label") or "").strip() or None
        row.notes = (payload.get("notes") or "").strip() or None
        row.created_by_id = row.created_by_id or current_user.id
        if payload.get("preview_card_id"):
            row.preview_card_id = int(payload["preview_card_id"])
        if payload.get("active"):
            (
                db.query(CardTemplate)
                .filter(
                    CardTemplate.kingdom == row.kingdom,
                    CardTemplate.side == row.side,
                    CardTemplate.category == row.category,
                )
                .update({"active": False}, synchronize_session=False)
            )
            row.active = True
        elif row.active is None:
            row.active = False
        db.commit()
        db.refresh(row)
        clear_template_cache()
        return {"ok": True, "template_id": row.id}
    finally:
        db.close()


@router.put("/templates/{template_id}/parts")
async def assign_template_parts(template_id: int, request: Request, current_user: User = Depends(require_admin_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    payload = await request.json()
    slots = payload.get("slots") or {}
    db = SessionLocal()
    try:
        row = _load_template_row(db, template_id)
        for slot_name, asset_id in slots.items():
            slot = (slot_name or "").strip().lower()
            if slot not in TEMPLATE_PART_SLOTS:
                continue
            existing = (
                db.query(TemplatePartAssignment)
                .filter(
                    TemplatePartAssignment.template_id == row.id,
                    TemplatePartAssignment.slot_name == slot,
                )
                .first()
            )
            if not asset_id:
                if existing:
                    db.delete(existing)
                continue
            asset = db.query(CardAsset).filter(CardAsset.id == int(asset_id)).first()
            if asset is None:
                raise HTTPException(404, f"Asset not found for slot {slot}")
            if existing is None:
                db.add(TemplatePartAssignment(template_id=row.id, slot_name=slot, asset_id=asset.id))
            else:
                existing.asset_id = asset.id
        db.commit()
        clear_template_cache()
        return {"ok": True}
    finally:
        db.close()


@router.post("/templates/preview")
async def preview_template(request: Request, current_user: User = Depends(require_admin_user)):
    payload = await request.json()
    front_template_id = payload.get("front_template_id")
    back_template_id = payload.get("back_template_id")
    sample_card_id = payload.get("sample_card_id")
    slot_overrides = payload.get("slot_overrides") or {}

    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        sample_card = None
        if sample_card_id:
            sample_card = db.query(Card).filter(Card.id == int(sample_card_id)).first()
        front_row = _load_template_row(db, int(front_template_id)) if front_template_id else None
        back_row = _load_template_row(db, int(back_template_id)) if back_template_id else None
        kingdom = (front_row.kingdom if front_row else (back_row.kingdom if back_row else "mammal"))
        source = sample_card or _fallback_sample(kingdom)
        render_card = build_render_card(source)
        if front_row:
            selection = select_template(
                kingdom=front_row.kingdom,
                side="front",
                preferred_name=front_row.name,
                preferred_version=front_row.version,
            )
            render_card["front_template"] = _template_to_dict(selection)
        if back_row:
            selection = select_template(
                kingdom=back_row.kingdom,
                side="back",
                preferred_name=back_row.name,
                preferred_version=back_row.version,
            )
            render_card["back_template"] = _template_to_dict(selection)

        for side_name, mapping in slot_overrides.items():
            template_key = "front_template" if side_name == "front" else "back_template"
            parts = [dict(item) for item in render_card[template_key].get("parts") or []]
            by_slot = {item.get("slot_name"): item for item in parts}
            for slot_name, asset_id in (mapping or {}).items():
                if not asset_id:
                    by_slot.pop(slot_name, None)
                    continue
                asset = db.query(CardAsset).filter(CardAsset.id == int(asset_id)).first()
                if asset is None:
                    continue
                by_slot[slot_name] = {
                    "id": asset.id,
                    "asset_id": asset.id,
                    "slot_name": slot_name,
                    "asset_url": asset.file_path,
                    "asset_type": asset.asset_type,
                    "template_part": asset.template_part,
                    "mime_type": asset.mime_type,
                    "name": asset.name,
                    "slug": asset.slug,
                    "version": asset.version,
                    "sort_order": asset.sort_order,
                    "active": bool(asset.active),
                }
            render_card[template_key]["parts"] = sorted(
                by_slot.values(),
                key=lambda item: (int(item.get("sort_order") or 100), item.get("slot_name") or ""),
            )
        return {"render_card": render_card}
    finally:
        db.close()


@router.post("/templates/{template_id}/activate")
def activate_template(template_id: int, current_user: User = Depends(require_admin_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        row = _load_template_row(db, template_id)
        (
            db.query(CardTemplate)
            .filter(
                CardTemplate.kingdom == row.kingdom,
                CardTemplate.side == row.side,
                CardTemplate.category == row.category,
            )
            .update({"active": False}, synchronize_session=False)
        )
        row.active = True
        db.commit()
        clear_template_cache()
        return {"ok": True, "id": row.id, "kingdom": row.kingdom, "side": row.side, "version": row.version}
    finally:
        db.close()


@router.get("/review-queue")
def review_queue(current_user: User = Depends(require_admin_user)):
    return {"items": get_agent_dashboard().get("review_queue", [])}


@router.post("/agents/tasks")
async def admin_agent_task(request: Request, current_user: User = Depends(require_admin_user)):
    payload = await request.json()
    agent_name = (payload.get("agent_name") or "").strip().lower()
    task_type = (payload.get("task_type") or "admin_request").strip()
    input_payload = dict(payload.get("payload") or {})
    card_id = int(payload["card_id"]) if payload.get("card_id") else None
    capture_job_id = int(payload["capture_job_id"]) if payload.get("capture_job_id") else None
    if not agent_name:
        raise HTTPException(400, "agent_name is required")

    if db_available():
        db = SessionLocal()
        try:
            if card_id:
                row = db.query(Card).filter(Card.id == card_id).first()
                if row is None:
                    raise HTTPException(404, "Card not found")
                input_payload.setdefault("card", build_render_card(row))
                input_payload.setdefault("source", _card_source(row))
                input_payload.setdefault("card_id", row.id)
                input_payload.setdefault("user_id", row.owner_id)
                input_payload.setdefault("region", row.region)
            if capture_job_id:
                job = db.query(CaptureJob).filter(CaptureJob.id == capture_job_id).first()
                if job is None:
                    raise HTTPException(404, "Capture job not found")
                input_payload.setdefault("capture_job_id", job.id)
                input_payload.setdefault("common_name", job.species_name)
                input_payload.setdefault("species_name", job.species_name)
                input_payload.setdefault("scientific_name", job.scientific_name)
                input_payload.setdefault("confidence", job.confidence)
                input_payload.setdefault("needs_review", job.status == "needs_review")
                input_payload.setdefault("review_reason", job.review_reason)
                input_payload.setdefault("evidence_summary", job.error_message or job.review_reason or "Capture job evidence inspected.")
                input_payload.setdefault("provisional", job.provisional)
                input_payload.setdefault("region", job.region)
                input_payload.setdefault("user_id", job.owner_id)
        finally:
            db.close()

    result = run_agent_task(
        agent_name=agent_name,
        task_type=task_type,
        payload=input_payload,
        actor_user_id=current_user.id,
        card_id=card_id,
        capture_job_id=capture_job_id,
    )
    return {"ok": True, "task": result}
