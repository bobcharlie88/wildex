from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Card, DexEntry, UserDexDiscovery

DISCOVERY_UNKNOWN = "UNKNOWN"
DISCOVERY_SEEN = "SEEN"
DISCOVERY_CAPTURED = "CAPTURED"
DISCOVERY_STATES = {
    DISCOVERY_UNKNOWN: 0,
    DISCOVERY_SEEN: 1,
    DISCOVERY_CAPTURED: 2,
}

KINGDOM_CODE_MAP = {
    "reptile": "REP",
    "mammal": "MAM",
    "fish": "FSH",
    "marine": "FSH",
    "bird": "BRD",
    "plant": "PLT",
    "insect": "INS",
    "arachnid": "INS",
    "amphibian": "AMP",
    "fungi": "FUN",
    "terrain": "TRN",
}

ANIMAL_SUBCATEGORIES = {
    "reptile",
    "mammal",
    "fish",
    "marine",
    "bird",
    "insect",
    "arachnid",
    "amphibian",
}

MARSUPIAL_HINTS = {
    "bandicoot",
    "bettong",
    "devil",
    "kangaroo",
    "koala",
    "numbat",
    "possum",
    "quokka",
    "quoll",
    "wallaby",
    "wombat",
}


@dataclass
class EvolutionProfile:
    chain_id: str
    stage: int
    length: int


def normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def derive_region_code(capture_country: str | None, lat: float | None = None, lon: float | None = None) -> str:
    if capture_country:
        return re.sub(r"[^A-Z]", "", capture_country.upper())[:4] or "UNK"
    return "UNK"


def derive_kingdom(category: str | None, sub_category: str | None, iconic_taxon: str | None = None) -> tuple[str, str]:
    sub = (sub_category or "").strip().lower()
    cat = (category or "").strip().lower()
    iconic = (iconic_taxon or "").strip().lower()

    if sub in ANIMAL_SUBCATEGORIES:
        if sub == "marine":
            return "fish", KINGDOM_CODE_MAP["marine"]
        return sub, KINGDOM_CODE_MAP.get(sub, "ANM")
    if cat == "plant" or iconic == "plantae":
        return "plant", KINGDOM_CODE_MAP["plant"]
    if cat == "fungi" or iconic == "fungi":
        return "fungi", KINGDOM_CODE_MAP["fungi"]
    if cat == "terrain" or iconic == "terrain":
        return "terrain", KINGDOM_CODE_MAP["terrain"]
    if cat == "animal":
        return "animal", "ANM"
    return "unknown", "UNK"


def derive_group_code(
    kingdom: str,
    common_name: str | None,
    scientific_name: str | None,
    sub_category: str | None,
) -> str:
    text = f"{common_name or ''} {scientific_name or ''}".lower()
    sub = (sub_category or "").lower()

    if kingdom == "reptile":
        if "dragon" in text:
            return "DRG"
        if "gecko" in text:
            return "GEK"
        if "skink" in text:
            return "SKN"
        if any(token in text for token in ("python", "snake", "adder", "cobra", "viper")):
            return "SNK"
        if any(token in text for token in ("turtle", "terrapin", "tortoise")):
            return "TRT"
        if "croc" in text:
            return "CRO"
        return "LIZ"

    if kingdom == "mammal":
        if any(token in text for token in MARSUPIAL_HINTS):
            return "MAR"
        if "bat" in text:
            return "BAT"
        if any(token in text for token in ("dolphin", "whale", "seal", "dugong")):
            return "SEA"
        if any(token in text for token in ("mouse", "rat", "rodent")):
            return "ROD"
        return "MAM"

    if kingdom == "bird":
        if any(token in text for token in ("eagle", "hawk", "falcon", "owl", "kite")):
            return "RAP"
        if any(token in text for token in ("parrot", "cockatoo", "lorikeet")):
            return "PAR"
        if any(token in text for token in ("pelican", "tern", "gull", "albatross", "cormorant")):
            return "SEA"
        return "BRD"

    if kingdom == "fish":
        if any(token in text for token in ("estuary", "mangrove", "mullet", "bream", "flathead")):
            return "EST"
        if any(token in text for token in ("reef", "coral", "clownfish", "angelfish", "wrasse")):
            return "REF"
        if any(token in text for token in ("shark", "ray")):
            return "SHK"
        return "FSH"

    if kingdom == "plant":
        if any(token in text for token in ("aloe", "medicinal", "healing", "vera")):
            return "MED"
        if sub == "tree":
            return "TRE"
        if sub == "flower":
            return "FLW"
        if sub == "grass":
            return "GRS"
        if sub == "cactus":
            return "CCT"
        if sub == "aquatic_plant":
            return "AQP"
        if sub == "shrub":
            return "SHB"
        return "BOT"

    if kingdom == "insect":
        if any(token in text for token in ("caterpillar", "butterfly", "moth", "chrysalis", "pupa", "cocoon", "larva")):
            return "LEP"
        if "beetle" in text:
            return "BET"
        if any(token in text for token in ("dragonfly", "damselfly")):
            return "ODO"
        return "INS"

    if kingdom == "amphibian":
        if any(token in text for token in ("tadpole", "frog", "toad", "froglet")):
            return "FRG"
        return "AMP"

    if kingdom == "fungi":
        return "FNG"

    if kingdom == "terrain":
        if "water" in text or "river" in text or "lake" in text:
            return "WTR"
        if "soil" in text or "sand" in text:
            return "SOL"
        return "ROC"

    return "UNK"


def canonical_species_key(
    region: str,
    kingdom_code: str,
    group_code: str,
    scientific_name: str | None,
    common_name: str | None,
) -> str:
    species_key = normalize_text(scientific_name) or normalize_text(common_name) or "unknown"
    return f"{region}:{kingdom_code}:{group_code}:{species_key}"


def _is_metamorphosis_term(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def infer_evolution_profile(
    region: str,
    kingdom: str,
    kingdom_code: str,
    group_code: str,
    common_name: str | None,
    scientific_name: str | None,
) -> EvolutionProfile | None:
    combined = f"{common_name or ''} {scientific_name or ''}".lower()

    if kingdom == "insect" and group_code == "LEP":
        if _is_metamorphosis_term(combined, ("caterpillar", "larva")):
            stage = 1
        elif _is_metamorphosis_term(combined, ("chrysalis", "pupa", "cocoon")):
            stage = 2
        else:
            stage = 3
        root = normalize_text(re.sub(r"\b(caterpillar|larva|chrysalis|pupa|cocoon|butterfly|moth)\b", "", combined))
        root = root or normalize_text(scientific_name) or "lepidoptera"
        return EvolutionProfile(
            chain_id=f"{region}:{kingdom_code}:{group_code}:evo:{root}",
            stage=stage,
            length=3,
        )

    if kingdom == "amphibian" and group_code == "FRG":
        if "tadpole" in combined:
            stage = 1
        elif "froglet" in combined:
            stage = 2
        elif any(token in combined for token in ("frog", "toad")):
            stage = 3
        else:
            return None
        root = normalize_text(re.sub(r"\b(tadpole|froglet|frog|toad)\b", "", combined))
        root = root or normalize_text(scientific_name) or "frog"
        return EvolutionProfile(
            chain_id=f"{region}:{kingdom_code}:{group_code}:evo:{root}",
            stage=stage,
            length=3,
        )

    return None


def _base_category_for_kingdom(kingdom: str) -> tuple[str | None, str | None]:
    if kingdom in ANIMAL_SUBCATEGORIES or kingdom in {"animal", "reptile", "mammal", "fish", "bird", "insect", "amphibian"}:
        return "animal", kingdom if kingdom in ANIMAL_SUBCATEGORIES else None
    if kingdom == "plant":
        return "plant", None
    if kingdom == "fungi":
        return "fungi", None
    if kingdom == "terrain":
        return "terrain", None
    return None, None


def _next_group_number(db: Session, region: str, kingdom: str, group_code: str) -> int:
    current = (
        db.query(func.max(DexEntry.number))
        .filter(
            DexEntry.region == region,
            DexEntry.kingdom == kingdom,
            DexEntry.group_code == group_code,
        )
        .scalar()
    )
    return int(current or 0) + 1


def _make_dex_id(region: str, kingdom_code: str, group_code: str, number: int) -> str:
    return f"{region}-{kingdom_code}-{group_code}-{number:03d}"


def _ensure_group_capacity(
    db: Session,
    *,
    region: str,
    kingdom: str,
    kingdom_code: str,
    group_code: str,
    minimum_total: int,
) -> None:
    total = (
        db.query(DexEntry)
        .filter(
            DexEntry.region == region,
            DexEntry.kingdom == kingdom,
            DexEntry.group_code == group_code,
        )
        .count()
    )
    category, sub_category = _base_category_for_kingdom(kingdom)
    while total < minimum_total:
        number = _next_group_number(db, region, kingdom, group_code)
        db.add(
            DexEntry(
                dex_id=_make_dex_id(region, derive_kingdom(category, sub_category)[1], group_code, number),
                region=region,
                kingdom=kingdom,
                group_code=group_code,
                number=number,
                category=category,
                sub_category=sub_category,
                is_placeholder=True,
            )
        )
        total += 1


def _populate_entry(
    entry: DexEntry,
    *,
    canonical_key: str,
    common_name: str | None,
    scientific_name: str | None,
    category: str | None,
    sub_category: str | None,
) -> DexEntry:
    entry.canonical_key = canonical_key
    entry.display_name = common_name or scientific_name or "Unknown"
    entry.scientific_name = scientific_name
    entry.discovery_hint = common_name or scientific_name
    entry.category = category
    entry.sub_category = sub_category
    entry.is_placeholder = False
    return entry


def resolve_or_create_dex_entry(
    db: Session,
    *,
    common_name: str | None,
    scientific_name: str | None,
    category: str | None,
    sub_category: str | None,
    iconic_taxon: str | None,
    capture_country: str | None,
) -> DexEntry:
    region = derive_region_code(capture_country)
    kingdom, kingdom_code = derive_kingdom(category, sub_category, iconic_taxon)
    group_code = derive_group_code(kingdom, common_name, scientific_name, sub_category)
    canonical_key = canonical_species_key(region, kingdom_code, group_code, scientific_name, common_name)

    existing = db.query(DexEntry).filter(DexEntry.canonical_key == canonical_key).first()
    if existing:
        return existing

    evo = infer_evolution_profile(region, kingdom, kingdom_code, group_code, common_name, scientific_name)
    if evo:
        chain_entry = (
            db.query(DexEntry)
            .filter(
                DexEntry.evolution_chain_id == evo.chain_id,
                DexEntry.evolution_stage == evo.stage,
            )
            .first()
        )
        if not chain_entry:
            start_number = _next_group_number(db, region, kingdom, group_code)
            category_value, sub_category_value = _base_category_for_kingdom(kingdom)
            for offset in range(evo.length):
                number = start_number + offset
                db.add(
                    DexEntry(
                        dex_id=_make_dex_id(region, kingdom_code, group_code, number),
                        region=region,
                        kingdom=kingdom,
                        group_code=group_code,
                        number=number,
                        category=category_value or category,
                        sub_category=sub_category_value or sub_category,
                        evolution_chain_id=evo.chain_id,
                        evolution_stage=offset + 1,
                        evolution_length=evo.length,
                        is_placeholder=True,
                    )
                )
            db.flush()
            chain_entry = (
                db.query(DexEntry)
                .filter(
                    DexEntry.evolution_chain_id == evo.chain_id,
                    DexEntry.evolution_stage == evo.stage,
                )
                .first()
            )
        entry = _populate_entry(
            chain_entry,
            canonical_key=canonical_key,
            common_name=common_name,
            scientific_name=scientific_name,
            category=category,
            sub_category=sub_category,
        )
    else:
        placeholder = (
            db.query(DexEntry)
            .filter(
                DexEntry.region == region,
                DexEntry.kingdom == kingdom,
                DexEntry.group_code == group_code,
                DexEntry.is_placeholder.is_(True),
                DexEntry.canonical_key.is_(None),
                DexEntry.evolution_chain_id.is_(None),
            )
            .order_by(DexEntry.number.asc())
            .first()
        )
        if placeholder is None:
            number = _next_group_number(db, region, kingdom, group_code)
            placeholder = DexEntry(
                dex_id=_make_dex_id(region, kingdom_code, group_code, number),
                region=region,
                kingdom=kingdom,
                group_code=group_code,
                number=number,
                category=category,
                sub_category=sub_category,
                is_placeholder=True,
            )
            db.add(placeholder)
            db.flush()
        entry = _populate_entry(
            placeholder,
            canonical_key=canonical_key,
            common_name=common_name,
            scientific_name=scientific_name,
            category=category,
            sub_category=sub_category,
        )

    db.flush()
    actual_count = (
        db.query(DexEntry)
        .filter(
            DexEntry.region == region,
            DexEntry.kingdom == kingdom,
            DexEntry.group_code == group_code,
            DexEntry.is_placeholder.is_(False),
        )
        .count()
    )
    _ensure_group_capacity(
        db,
        region=region,
        kingdom=kingdom,
        kingdom_code=kingdom_code,
        group_code=group_code,
        minimum_total=max(3, actual_count + 2),
    )
    db.flush()
    return entry


def set_discovery_state(
    db: Session,
    *,
    user_id: int,
    dex_entry_id: int,
    state: str,
    card_id: int | None = None,
) -> UserDexDiscovery:
    discovery = (
        db.query(UserDexDiscovery)
        .filter(
            UserDexDiscovery.user_id == user_id,
            UserDexDiscovery.dex_entry_id == dex_entry_id,
        )
        .first()
    )
    if discovery is None:
        discovery = UserDexDiscovery(
            user_id=user_id,
            dex_entry_id=dex_entry_id,
            discovery_state=state,
        )
        db.add(discovery)
        db.flush()

    current_rank = DISCOVERY_STATES.get(discovery.discovery_state, 0)
    target_rank = DISCOVERY_STATES.get(state, 0)
    if target_rank >= current_rank:
        discovery.discovery_state = state
    if state in {DISCOVERY_SEEN, DISCOVERY_CAPTURED} and discovery.first_seen_at is None:
        discovery.first_seen_at = datetime.utcnow()
    if state == DISCOVERY_CAPTURED and discovery.first_captured_at is None:
        discovery.first_captured_at = datetime.utcnow()
    if card_id is not None:
        discovery.last_card_id = card_id
    db.flush()
    return discovery


def sync_card_to_dex(db: Session, card: Card) -> DexEntry:
    entry = resolve_or_create_dex_entry(
        db,
        common_name=card.species_name,
        scientific_name=card.scientific_name,
        category=card.category,
        sub_category=card.sub_category,
        iconic_taxon=card.iconic_taxon,
        capture_country=card.capture_country,
    )
    card.dex_entry_id = entry.id
    card.dex_id = entry.dex_id
    card.discovery_state = DISCOVERY_CAPTURED
    card.region = entry.region
    card.kingdom = entry.kingdom
    card.group_code = entry.group_code
    card.evolution_chain_id = entry.evolution_chain_id
    card.evolution_stage = entry.evolution_stage
    if card.owner_id:
        set_discovery_state(
            db,
            user_id=card.owner_id,
            dex_entry_id=entry.id,
            state=DISCOVERY_CAPTURED,
            card_id=card.id,
        )
    return entry


def backfill_user_cards(db: Session, user_id: int) -> None:
    rows = (
        db.query(Card)
        .filter(
            Card.owner_id == user_id,
            Card.dex_entry_id.is_(None),
        )
        .order_by(Card.captured_at.asc(), Card.id.asc())
        .all()
    )
    changed = False
    for row in rows:
        sync_card_to_dex(db, row)
        changed = True
    if changed:
        db.commit()

