from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from typing import Any

from app.database import SessionLocal, db_available
from app.models import DexEntry, SubmissionRequest, UserDexDiscovery
from app.pipeline.species_id import SpeciesResult
from app.services.agents.schemas import (
    AgentCandidate,
    CardBuilderOutput,
    CardStatsPayload,
    DrAgentOutput,
    MapAgentOutput,
    ResearchSource,
    ResearchConfirmationSchema,
    ReviewAgentOutput,
    SpeciesResultSchema,
    VerificationReportSchema,
)
from app.services.card_render import build_card_payload, build_render_card
from app.services.dex import DISCOVERY_CAPTURED, DISCOVERY_SEEN
from app.services.submission_verification import verify_submission_image

DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"
HIGH_RELIABILITY_DOMAINS = (
    ".gov",
    ".edu",
    ".ac.",
    "gbif.org",
    "inaturalist.org",
    "ala.org.au",
    "biodiversity.org.au",
    "iucnredlist.org",
    "museum",
)
MEDIUM_RELIABILITY_HINTS = (
    "wikipedia.org",
    "nationalgeographic.com",
    "britannica.com",
    "abc.net.au",
    "theconversation.com",
)
LOW_RELIABILITY_HINTS = (
    "reddit.com",
    "facebook.com",
    "forum",
    "blog",
    "wordpress.com",
)


def _normalize_card_source(source: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(source or {})
    stats = dict(normalized.get("stats") or {})
    if "defence" not in stats and "defense" in stats:
        stats["defence"] = stats["defense"]
    if "speed" not in stats and "spd" in stats:
        stats["speed"] = stats["spd"]
    if "attack" not in stats and "atk" in stats:
        stats["attack"] = stats["atk"]
    if "hp" not in stats and "health" in stats:
        stats["hp"] = stats["health"]
    if stats:
        normalized["stats"] = stats

    if not normalized.get("species_name") and normalized.get("common_name"):
        normalized["species_name"] = normalized["common_name"]
    if not normalized.get("common_name") and normalized.get("species_name"):
        normalized["common_name"] = normalized["species_name"]
    if not normalized.get("rarity_display") and normalized.get("rarity"):
        normalized["rarity_display"] = normalized["rarity"]
    if not normalized.get("blurb"):
        normalized["blurb"] = normalized.get("short_blurb") or normalized.get("flavor_text")
    if not normalized.get("wikipedia_summary"):
        normalized["wikipedia_summary"] = normalized.get("fact_text")
    if not normalized.get("diet") and normalized.get("diet_text"):
        normalized["diet"] = normalized.get("diet_text")
    if not normalized.get("habitat") and normalized.get("habitat_text"):
        normalized["habitat"] = normalized.get("habitat_text")
    if not normalized.get("sound_url") and normalized.get("audio_url"):
        normalized["sound_url"] = normalized.get("audio_url")

    kingdom = str(normalized.get("kingdom") or "").strip().lower()
    if kingdom and not normalized.get("sub_category"):
        kingdom_map = {
            "reptile": "reptile",
            "mammal": "mammal",
            "bird": "bird",
            "fish": "fish",
            "marine": "marine",
            "insect": "insect",
            "arachnid": "arachnid",
            "plant": "plant",
        }
        normalized["sub_category"] = kingdom_map.get(kingdom)
    if kingdom == "plant" and not normalized.get("category"):
        normalized["category"] = "plant"

    return normalized


def _candidate_list(species: SpeciesResult) -> list[AgentCandidate]:
    candidates = [
        AgentCandidate(
            label=species.common_name or species.scientific_name,
            scientific_name=species.scientific_name,
            confidence=round(float(species.confidence or 0.0), 4),
            reason=species.reasoning,
        )
    ]
    if species.iconic_taxon:
        candidates.append(
            AgentCandidate(
                label=f"Iconic taxon: {species.iconic_taxon}",
                confidence=max(0.2, round(float(species.confidence or 0.0) - 0.18, 4)),
                reason="Higher-level taxon fallback if species certainty degrades.",
            )
        )
    return candidates


def normalize_species_result(payload: dict[str, Any]) -> SpeciesResultSchema:
    species = payload.get("species")
    raw_candidates = payload.get("candidate_list") or []
    parsed_candidates = [
        item if isinstance(item, AgentCandidate) else AgentCandidate.model_validate(item)
        for item in raw_candidates
    ]
    raw_alternatives = payload.get("alternatives") or []
    parsed_alternatives = [
        item if isinstance(item, AgentCandidate) else AgentCandidate.model_validate(item)
        for item in raw_alternatives
    ]
    if isinstance(species, SpeciesResult):
        confidence = round(float(species.confidence or 0.0), 4)
        needs_review = bool(payload.get("needs_review", species.provisional or confidence < 0.7))
        review_reason = payload.get("review_reason") or (
            "Confidence is below automatic-save threshold." if needs_review else None
        )
        return SpeciesResultSchema(
            common_name=species.common_name or species.scientific_name,
            scientific_name=species.scientific_name,
            confidence=confidence,
            needs_review=needs_review,
            review_reason=review_reason,
            evidence_summary=species.reasoning or "Species identified from submitted evidence.",
            candidate_list=parsed_candidates or _candidate_list(species),
            category=species.category,
            sub_category=species.sub_category,
            rank=species.rank,
            taxon_id=species.taxon_id,
            iconic_taxon=species.iconic_taxon,
            provisional=species.provisional,
            consensus_score=payload.get("consensus_score"),
            location_validated=payload.get("location_validated"),
            alternatives=parsed_alternatives,
        )

    confidence = round(float(payload.get("confidence") or 0.0), 4)
    common_name = payload.get("common_name") or payload.get("species_name") or "Unknown species"
    scientific_name = payload.get("scientific_name") or "Unknown species"
    evidence_summary = payload.get("evidence_summary") or payload.get("reasoning") or "Stored species evidence inspected."
    if common_name.strip().lower() in {"animal", "bird", "plant", "fish", "insect", "unknown"}:
        common_name = scientific_name if scientific_name != "Unknown species" else "Unresolved species"
    return SpeciesResultSchema(
        common_name=common_name,
        scientific_name=scientific_name,
        confidence=confidence,
        needs_review=bool(payload.get("needs_review")),
        review_reason=payload.get("review_reason"),
        evidence_summary=evidence_summary,
        candidate_list=parsed_candidates or [
            AgentCandidate(
                label=common_name,
                scientific_name=scientific_name if scientific_name != "Unknown species" else None,
                confidence=confidence,
                reason=payload.get("reasoning") or payload.get("review_reason") or evidence_summary,
            )
        ],
        category=payload.get("category"),
        sub_category=payload.get("sub_category"),
        rank=payload.get("rank"),
        taxon_id=payload.get("taxon_id"),
        iconic_taxon=payload.get("iconic_taxon"),
        provisional=bool(payload.get("provisional")),
        consensus_score=payload.get("consensus_score"),
        location_validated=payload.get("location_validated"),
        alternatives=parsed_alternatives,
    )


def build_card_payload_tool(source: dict[str, Any]) -> CardBuilderOutput:
    normalized_source = _normalize_card_source(source)
    card_payload = build_card_payload(normalized_source)
    render_card = build_render_card(normalized_source)
    slot_content = dict(render_card.get("slot_content") or {})
    flavor_text = card_payload["flavor_text"]
    fact_snippets = [item for item in (card_payload.get("fact_snippets") or []) if item and item != flavor_text]
    moves = [str(item).strip() for item in (card_payload.get("moves") or []) if str(item).strip()]
    if len(moves) < 3:
        theme = (card_payload.get("render_hints") or {}).get("theme") or "field"
        fallback_moves = {
            "reptile": ["Thermal Bask", "Ambush Snap", "Rocky Sprint"],
            "mammal": ["Territory Sense", "Burst Sprint", "Survival Kick"],
            "fish": ["Current Surge", "Deep Turn", "Hunter Sweep"],
            "bird": ["Sky Scan", "Dive Arc", "Wind Lift"],
            "insect": ["Camouflage Hold", "Rapid Scuttle", "Defensive Burst"],
            "plant": ["Root Hold", "Spore Drift", "Sun Draw"],
        }.get(theme, ["Field Adaptation", "Survey Burst", "Territory Shift"])
        for move in fallback_moves:
            if move not in moves:
                moves.append(move)
            if len(moves) >= 3:
                break
    moves = moves[:4]
    abilities = []
    strength_name = card_payload.get("strength_name")
    strength_effect = card_payload.get("strength_effect")
    weakness_name = card_payload.get("weakness_name")
    weakness_effect = card_payload.get("weakness_effect")
    if strength_name or strength_effect:
        abilities.append(f"{strength_name or 'Strength'}: {strength_effect or ''}".strip(": "))
    if weakness_name or weakness_effect:
        abilities.append(f"{weakness_name or 'Weakness'}: {weakness_effect or ''}".strip(": "))
    for fact in fact_snippets:
        if fact not in abilities:
            abilities.append(fact)
        if len(abilities) >= 3:
            break
    slot_content["moves_panel"] = {"rows": moves}
    slot_content["abilities_panel"] = {"rows": abilities[:3] or moves[:2]}
    return CardBuilderOutput(
        card_title=card_payload["card_title"],
        scientific_name=card_payload["scientific_name"],
        rarity=card_payload["rarity"],
        stats=CardStatsPayload.model_validate(card_payload["stats"]),
        moves=moves,
        diet=card_payload["diet"],
        habitat_text=card_payload["habitat_text"],
        flavor_text=flavor_text,
        fact_snippets=fact_snippets or card_payload.get("fact_snippets") or [],
        slot_content=slot_content,
        render_hints=card_payload.get("render_hints") or {},
        front_template=render_card.get("front_template") or {},
        back_template=render_card.get("back_template") or {},
    )


def inspect_map_progress(payload: dict[str, Any]) -> MapAgentOutput:
    user_id = payload.get("user_id")
    region = payload.get("region")
    counts = {"captured": 0, "seen": 0}
    if user_id and db_available() and SessionLocal is not None:
        db = SessionLocal()
        try:
            query = (
                db.query(UserDexDiscovery.discovery_state)
                .join(DexEntry, DexEntry.id == UserDexDiscovery.dex_entry_id)
                .filter(UserDexDiscovery.user_id == user_id)
            )
            if region:
                query = query.filter(DexEntry.region == region)
            for (state,) in query.all():
                if state == DISCOVERY_CAPTURED:
                    counts["captured"] += 1
                elif state == DISCOVERY_SEEN:
                    counts["seen"] += 1
        finally:
            db.close()
    return MapAgentOutput(
        region=region,
        unlocked=bool(payload.get("region_unlocked")),
        repeat_state=payload.get("repeat_state"),
        counts=counts,
        summary=payload.get("summary")
        or (
            f"Region {region or 'unknown'} now has {counts['captured']} captured and {counts['seen']} seen entries."
            if counts["captured"] or counts["seen"]
            else "Map state inspected."
        ),
    )


def build_review_recommendation(payload: dict[str, Any]) -> ReviewAgentOutput:
    confidence = float(payload.get("confidence") or 0.0)
    rarity = str(payload.get("rarity") or "").lower()
    needs_review = bool(payload.get("needs_review"))
    priority = "medium"
    if rarity in {"legendary", "mythic", "cryptic", "extinct"} or confidence < 0.45:
        priority = "high"
    elif confidence >= 0.7 and not needs_review:
        priority = "low"
    return ReviewAgentOutput(
        needs_review=needs_review,
        priority=priority,
        reason=payload.get("reason") or ("Capture requires manual review." if needs_review else "No review action required."),
        evidence_summary=payload.get("evidence_summary") or "",
        queue_status="recommended" if needs_review else "not_required",
    )


def build_dr_response(payload: dict[str, Any]) -> DrAgentOutput:
    card = payload.get("card") or {}
    question = str(payload.get("question") or "").strip()
    question_lower = question.lower()
    requested_mode = str(payload.get("mode") or "").strip().lower()
    mode = requested_mode or (
        "feeding_advice" if any(token in question_lower for token in ("feed", "feeding", "hungry", "hunger")) else
        "biome_tip" if any(token in question_lower for token in ("biome", "habitat", "where")) else
        "what_next" if any(token in question_lower for token in ("next", "what should", "now what")) else
        "read_aloud" if "read aloud" in question_lower else
        "card_explain"
    )
    mode = mode if mode in {"card_explain", "feeding_advice", "biome_tip", "what_next", "read_aloud"} else "card_explain"

    biome = payload.get("biome") or card.get("biome") or card.get("habitat_text")
    player_region = payload.get("player_region") or card.get("region")
    collection = payload.get("collection") or {}
    hunger_state = payload.get("hunger_state")
    feed_state = payload.get("feed_state")
    species_name = card.get("species_name") or card.get("card_title")
    scientific_name = card.get("scientific_name")
    rarity = card.get("rarity_display") or card.get("rarity")
    habitat = card.get("habitat_text") or card.get("biome")
    diet = card.get("diet_text") or card.get("diet")
    fact = card.get("fact_text") or (card.get("fact_snippets") or [""])[0]

    missing_context: list[str] = []
    if mode in {"card_explain", "read_aloud"} and not card:
        missing_context.append("current card")
    if mode == "biome_tip" and not biome:
        missing_context.append("biome")
    if mode == "what_next":
        if not player_region:
            missing_context.append("player region")
        if not collection:
            missing_context.append("collection summary")
    if mode == "feeding_advice":
        if not hunger_state:
            missing_context.append("hunger state")
        if not feed_state:
            missing_context.append("feed state")
        if not diet:
            missing_context.append("card diet")

    if missing_context:
        reply = f"I need {', '.join(missing_context)} to answer in {mode.replace('_', ' ')} mode."
        follow_up = "Send that context and I will keep the answer specific to this card."
        suggested_actions: list[str] = []
    else:
        follow_up = None
        suggested_actions = []
        if mode == "card_explain":
            reply_bits = [species_name or "This card"]
            if rarity:
                reply_bits.append(f"is logged as {rarity}")
            if biome:
                reply_bits.append(f"with a main biome of {biome}")
            reply = " ".join(reply_bits) + "."
            if fact:
                follow_up = f"Best field note: {fact}"
            suggested_actions = ["Flip to the card back for map and trait details"]
        elif mode == "feeding_advice":
            reply = f"Hunger is {hunger_state} and feed state is {feed_state}. Match feeding to the card diet: {diet}."
            if habitat:
                follow_up = f"This species is strongest around {habitat}, so use food or encounters that fit that environment."
            suggested_actions = ["Check the card diet before feeding again"]
        elif mode == "biome_tip":
            region_text = f" in {player_region}" if player_region else ""
            reply = f"Best biome lead{region_text}: {biome}."
            if habitat:
                follow_up = f"Look for similar conditions to {habitat} to improve your next encounter."
            suggested_actions = ["Search nearby spots that match this biome"]
        elif mode == "what_next":
            captured = int(collection.get("captured_count") or 0)
            unlocked = int(collection.get("regions_unlocked") or 0)
            reply = f"You have {captured} captured cards across {unlocked} unlocked regions. Best next move: chase a new branch in {player_region} before repeating common finds."
            if species_name:
                follow_up = f"If you stay near {species_name}'s biome, use repeats only to strengthen evidence, not as your main progression."
            suggested_actions = ["Open the regional Dex and target an uncaptured entry"]
        else:
            intro = species_name or "This record"
            species_line = f" Scientific name: {scientific_name}." if scientific_name else ""
            rarity_line = f" Rarity: {rarity}." if rarity else ""
            biome_line = f" Biome: {biome}." if biome else ""
            note_line = f" Field note: {fact}." if fact else ""
            reply = f"{intro}.{species_line}{rarity_line}{biome_line}{note_line}".strip()
            follow_up = "Open the back if you want the map, strengths, and weakness summary."
            suggested_actions = ["Use the card back for the detailed field summary"]
    return DrAgentOutput(
        mode=mode,
        reply=reply.strip(),
        follow_up=follow_up,
        missing_context=missing_context,
        suggested_actions=suggested_actions,
        referenced_card_id=payload.get("card_id"),
        referenced_capture_job_id=payload.get("capture_job_id"),
    )


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_search_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [None])[0]
        if target:
            return unquote(target)
    return raw_url


def _source_profile(url: str) -> tuple[str, str]:
    domain = (urlparse(url).netloc or "").lower().replace("www.", "")
    if any(token in domain for token in HIGH_RELIABILITY_DOMAINS):
        if any(token in domain for token in ("gbif.org", "inaturalist.org", "ala.org.au", "biodiversity.org.au", "iucnredlist.org")):
            return "biodiversity_database", "high"
        if "museum" in domain or ".edu" in domain or ".ac." in domain:
            return "museum_university", "high"
        return "official", "high"
    if any(token in domain for token in LOW_RELIABILITY_HINTS):
        return "community", "low"
    if any(token in domain for token in MEDIUM_RELIABILITY_HINTS):
        if "abc.net.au" in domain or "theconversation.com" in domain:
            return "journalism", "medium"
        return "reference", "medium"
    return "unknown", "medium"


def _search_duckduckgo(query: str, *, max_results: int = 8) -> list[dict[str, str]]:
    response = httpx.get(
        DDG_SEARCH_URL,
        params={"q": query},
        headers={"User-Agent": "WildEx Research Agent/1.0"},
        timeout=20.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    html = response.text
    matches = re.findall(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, title in matches:
        url = _extract_search_result_url(unescape(href))
        if not url.startswith("http"):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({"title": _clean_text(title), "url": url})
        if len(results) >= max_results:
            break
    return results


def _fetch_source_summary(url: str) -> tuple[str, str]:
    response = httpx.get(
        url,
        headers={"User-Agent": "WildEx Research Agent/1.0"},
        timeout=20.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    html = response.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ) or re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = _clean_text(title_match.group(1)) if title_match else url
    summary = _clean_text(meta_match.group(1)) if meta_match else ""
    if not summary:
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, flags=re.IGNORECASE | re.DOTALL)
        summary = _clean_text(body_match.group(1))[:320] if body_match else ""
    return title[:180], summary[:420]


def _build_research_sources(query: str, *, scientific_name: str, final_species: str) -> tuple[list[ResearchSource], list[str]]:
    uncertainty_notes: list[str] = []
    try:
        search_results = _search_duckduckgo(query)
    except Exception as exc:
        return [], [f"Web search was unavailable while researching this result: {exc}"]

    sources: list[ResearchSource] = []
    for result in search_results:
        try:
            title, summary = _fetch_source_summary(result["url"])
        except Exception:
            title = result["title"] or result["url"]
            summary = ""
        source_type, reliability = _source_profile(result["url"])
        combined = f"{title} {summary}".lower()
        supports_final = scientific_name.lower() in combined or final_species.lower() in combined
        sources.append(
            ResearchSource(
                title=title or result["title"] or result["url"],
                url=result["url"],
                domain=(urlparse(result["url"]).netloc or "").lower().replace("www.", ""),
                source_type=source_type,
                reliability=reliability,
                summary=summary,
                supports_final=supports_final,
            )
        )
    if not sources:
        uncertainty_notes.append("No external research sources were retrieved for this query.")
    return sources, uncertainty_notes


def build_research_confirmation(payload: dict[str, Any]) -> ResearchConfirmationSchema:
    top_candidates = payload.get("top_candidates") or []
    selected = dict(top_candidates[0] or {})
    alternatives = [
        AgentCandidate(
            label=item.get("common_name") or item.get("label") or item.get("scientific_name") or "Unknown",
            scientific_name=item.get("scientific_name"),
            confidence=float(item.get("confidence") or 0.0),
            reason=item.get("location_reason") or item.get("reason"),
        )
        for item in payload.get("alternatives") or top_candidates[1:4]
    ]
    reasoning = payload.get("reasoning") or selected.get("reason") or "Consensus research confirmation completed."
    final_species = (
        payload.get("final_species")
        or selected.get("common_name")
        or selected.get("label")
        or selected.get("scientific_name")
        or "Unknown species"
    )
    scientific_name = payload.get("scientific_name") or selected.get("scientific_name") or "Unknown species"
    location_terms = " ".join(
        str(payload.get(key) or "").strip()
        for key in ("country", "state", "location_text")
        if str(payload.get(key) or "").strip()
    ).strip()
    query = " ".join(part for part in [scientific_name or final_species, location_terms, "distribution"] if part).strip()
    sources, uncertainty_notes = _build_research_sources(query or scientific_name or final_species, scientific_name=scientific_name, final_species=final_species)
    high_sources = [source for source in sources if source.reliability == "high"]
    medium_sources = [source for source in sources if source.reliability == "medium"]
    support_count = sum(1 for source in sources if source.supports_final and source.reliability in {"high", "medium"})
    conflict_notes: list[str] = []
    if sources and not support_count:
        conflict_notes.append("Fetched sources did not clearly confirm the selected final species.")
    if len(high_sources) < 2:
        uncertainty_notes.append("Fewer than two high-reliability sources were available for cross-checking.")
    source_quality_summary = (
        f"{len(high_sources)} high-reliability, {len(medium_sources)} medium-reliability, "
        f"{max(0, len(sources) - len(high_sources) - len(medium_sources))} low-reliability sources checked."
    )
    return ResearchConfirmationSchema(
        final_species=final_species,
        scientific_name=scientific_name,
        confidence=float(payload.get("confidence") or selected.get("confidence") or 0.0),
        consensus_score=float(payload.get("consensus_score") or selected.get("consensus_score") or 0.0),
        location_validated=bool(payload.get("location_validated") if "location_validated" in payload else selected.get("location_validated")),
        alternatives=alternatives,
        reasoning=reasoning,
        category=payload.get("category") or selected.get("category"),
        sub_category=payload.get("sub_category") or selected.get("sub_category"),
        rank=payload.get("rank") or selected.get("rank"),
        taxon_id=payload.get("taxon_id") or selected.get("taxon_id"),
        iconic_taxon=payload.get("iconic_taxon") or selected.get("iconic_taxon"),
        provisional=bool(payload.get("provisional")),
        source_quality_summary=source_quality_summary,
        uncertainty_notes=uncertainty_notes,
        conflict_notes=conflict_notes,
        sources=sources[:8],
    )


def build_verification_report(payload: dict[str, Any], *, tool_context: dict[str, Any] | None = None) -> VerificationReportSchema:
    context = tool_context or {}
    submission = payload.get("submission") or {}
    if context.get("data") is not None:
        report = verify_submission_image(
            data=context["data"],
            filename=str(payload.get("filename") or "submission-image"),
            content_type=payload.get("content_type"),
            observed_date=payload.get("observed_date"),
        )
    elif payload.get("report"):
        report = dict(payload["report"])
    elif submission:
        report = dict(submission.get("report") or {})
    else:
        report = {
            "authenticity_confidence": 0.0,
            "ai_suspicion_score": 0.5,
            "metadata_present": False,
            "metadata_summary": {"error": "No submission verification context was provided."},
            "gps_present": False,
            "capture_datetime": None,
            "date_time_check_result": "No verification context supplied.",
            "device_info": None,
            "suspicious_findings": ["No image or stored verification report was provided to the verification agent."],
            "recommendation": "manual_review",
            "status": "manual_review",
            "verification_reason": "Verification could not run without image or stored report context.",
            "raw_report": {},
        }
    report.setdefault("status", payload.get("status") or submission.get("status") or "manual_review")
    report.setdefault(
        "verification_reason",
        payload.get("verification_reason")
        or submission.get("verification_reason")
        or "Stored verification report inspected.",
    )
    report.setdefault("metadata_summary_text", payload.get("metadata_summary_text"))
    summary = report.get("metadata_summary") or {}
    metadata_text = payload.get("metadata_summary_text")
    if not metadata_text:
        device = report.get("device_info") or "unknown device"
        capture_time = report.get("capture_datetime") or "unknown capture time"
        gps_text = "GPS present" if report.get("gps_present") else "GPS missing"
        metadata_text = f"{device}; {capture_time}; {gps_text}."
    report["metadata_summary_text"] = metadata_text
    report.setdefault("metadata_summary", summary if isinstance(summary, dict) else {"summary": summary})
    report.setdefault("raw_report", {})
    return VerificationReportSchema.model_validate(report)
