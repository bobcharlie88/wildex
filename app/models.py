from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    favorite_card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cards: Mapped[list["Card"]] = relationship(
        back_populates="owner",
        foreign_keys="Card.owner_id",
    )
    dex_discoveries: Mapped[list["UserDexDiscovery"]] = relationship(back_populates="user")


class DexEntry(Base):
    __tablename__ = "dex_entries"
    __table_args__ = (
        UniqueConstraint("region", "kingdom", "group_code", "number", name="uq_dex_entries_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dex_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    region: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    kingdom: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    group_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(200))
    scientific_name: Mapped[str | None] = mapped_column(String(200))
    canonical_key: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    category: Mapped[str | None] = mapped_column(String(50))
    sub_category: Mapped[str | None] = mapped_column(String(100))
    discovery_hint: Mapped[str | None] = mapped_column(String(200))

    evolution_chain_id: Mapped[str | None] = mapped_column(String(255), index=True)
    evolution_stage: Mapped[int | None] = mapped_column(Integer)
    evolution_length: Mapped[int | None] = mapped_column(Integer)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cards: Mapped[list["Card"]] = relationship(back_populates="dex_entry")
    discoveries: Mapped[list["UserDexDiscovery"]] = relationship(back_populates="dex_entry")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    species_name: Mapped[str] = mapped_column(String(200), nullable=False)
    scientific_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)

    taxon_id: Mapped[int | None] = mapped_column(Integer)
    iconic_taxon: Mapped[str | None] = mapped_column(String(100))
    conservation_status: Mapped[str | None] = mapped_column(String(100))
    observations_count: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[str | None] = mapped_column(String(50))
    sub_category: Mapped[str | None] = mapped_column(String(100))

    gbif_key: Mapped[int | None] = mapped_column(Integer)
    rarity_tier: Mapped[str | None] = mapped_column(String(50))
    rarity_display: Mapped[str | None] = mapped_column(String(50))
    invasive_at_location: Mapped[bool] = mapped_column(Boolean, default=False)

    blurb: Mapped[str | None] = mapped_column(Text)
    speed: Mapped[int | None] = mapped_column(Integer)
    attack: Mapped[int | None] = mapped_column(Integer)
    defence: Mapped[int | None] = mapped_column(Integer)
    hp: Mapped[int | None] = mapped_column(Integer)
    stamina_regen: Mapped[int | None] = mapped_column(Integer)
    threat_level: Mapped[str | None] = mapped_column(String(32))
    aggression: Mapped[str | None] = mapped_column(String(32))
    biome: Mapped[str | None] = mapped_column(String(120))
    biome_bonus: Mapped[str | None] = mapped_column(String(255))
    strength_name: Mapped[str | None] = mapped_column(String(120))
    strength_effect: Mapped[str | None] = mapped_column(String(255))
    weakness_name: Mapped[str | None] = mapped_column(String(120))
    weakness_effect: Mapped[str | None] = mapped_column(String(255))
    sound_url: Mapped[str | None] = mapped_column(String(1000))

    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    capture_country: Mapped[str | None] = mapped_column(String(10))
    original_image_url: Mapped[str | None] = mapped_column(String(1000))
    primary_card_image_url: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    supporting_image_urls: Mapped[str | None] = mapped_column(Text)
    front_template_name: Mapped[str | None] = mapped_column(String(120))
    front_template_version: Mapped[str | None] = mapped_column(String(32))
    back_template_name: Mapped[str | None] = mapped_column(String(120))
    back_template_version: Mapped[str | None] = mapped_column(String(32))
    dex_entry_id: Mapped[int | None] = mapped_column(ForeignKey("dex_entries.id"), index=True)
    dex_id: Mapped[str | None] = mapped_column(String(32), index=True)
    discovery_state: Mapped[str | None] = mapped_column(String(20))
    region: Mapped[str | None] = mapped_column(String(8))
    kingdom: Mapped[str | None] = mapped_column(String(32))
    group_code: Mapped[str | None] = mapped_column(String(32))
    evolution_chain_id: Mapped[str | None] = mapped_column(String(255))
    evolution_stage: Mapped[int | None] = mapped_column(Integer)

    owner: Mapped[User | None] = relationship(
        back_populates="cards",
        foreign_keys=[owner_id],
    )
    dex_entry: Mapped[DexEntry | None] = relationship(back_populates="cards")


class CaptureJob(Base):
    __tablename__ = "capture_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(32))
    original_image_url: Mapped[str | None] = mapped_column(String(1000))
    primary_image_url: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    encounter_id: Mapped[str | None] = mapped_column(String(64), index=True)
    primary_job_id: Mapped[int | None] = mapped_column(ForeignKey("capture_jobs.id"), index=True)
    grouped_job_ids: Mapped[str | None] = mapped_column(Text)
    grouped_count: Mapped[int] = mapped_column(Integer, default=1)
    species_name: Mapped[str | None] = mapped_column(String(200))
    scientific_name: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float | None] = mapped_column(Float)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_state: Mapped[str | None] = mapped_column(String(32))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), index=True)
    region: Mapped[str | None] = mapped_column(String(8))
    region_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    review_reason: Mapped[str | None] = mapped_column(Text)
    supporting_image_urls: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    owner: Mapped[User] = relationship()
    card: Mapped[Card | None] = relationship(foreign_keys=[card_id])
    primary_job: Mapped["CaptureJob | None"] = relationship(remote_side=[id], foreign_keys=[primary_job_id])


class CardTemplate(Base):
    __tablename__ = "card_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_card_templates_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    kingdom: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    side: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    asset_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(160), index=True)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    family: Mapped[str | None] = mapped_column(String(120), index=True)
    environment: Mapped[str | None] = mapped_column(String(120), index=True)
    layout_key: Mapped[str | None] = mapped_column(String(64))
    config_json: Mapped[str | None] = mapped_column(Text)
    preview_card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    preview_card: Mapped[Card | None] = relationship(foreign_keys=[preview_card_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    part_assignments: Mapped[list["TemplatePartAssignment"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
    )


class CardAsset(Base):
    __tablename__ = "card_assets"
    __table_args__ = (
        UniqueConstraint("slug", "version", name="uq_card_assets_slug_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    kingdom: Mapped[str | None] = mapped_column(String(32), index=True)
    family: Mapped[str | None] = mapped_column(String(120), index=True)
    environment: Mapped[str | None] = mapped_column(String(120), index=True)
    side: Mapped[str | None] = mapped_column(String(16), index=True)
    template_part: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    tags: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    uploader: Mapped[User | None] = relationship(foreign_keys=[uploaded_by])
    template_assignments: Mapped[list["TemplatePartAssignment"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
    )


class TemplatePartAssignment(Base):
    __tablename__ = "template_part_assignments"
    __table_args__ = (
        UniqueConstraint("template_id", "slot_name", name="uq_template_part_assignments_template_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("card_templates.id"), index=True, nullable=False)
    slot_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("card_assets.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template: Mapped[CardTemplate] = relationship(back_populates="part_assignments")
    asset: Mapped[CardAsset] = relationship(back_populates="template_assignments")


class UserDexDiscovery(Base):
    __tablename__ = "user_dex_discoveries"
    __table_args__ = (
        UniqueConstraint("user_id", "dex_entry_id", name="uq_user_dex_discoveries_user_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    dex_entry_id: Mapped[int] = mapped_column(ForeignKey("dex_entries.id"), index=True, nullable=False)
    discovery_state: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="dex_discoveries")
    dex_entry: Mapped[DexEntry] = relationship(back_populates="discoveries")
