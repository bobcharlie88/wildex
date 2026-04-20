from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Species identity ──────────────────────────────────────────
    species_name:        Mapped[str]        = mapped_column(String(200), nullable=False)
    scientific_name:     Mapped[str]        = mapped_column(String(200), nullable=False)
    rank:                Mapped[str | None] = mapped_column(String(50))
    confidence:          Mapped[float | None] = mapped_column(Float)
    provisional:         Mapped[bool]       = mapped_column(Boolean, default=False)

    # ── iNaturalist ───────────────────────────────────────────────
    taxon_id:            Mapped[int | None] = mapped_column(Integer)
    iconic_taxon:        Mapped[str | None] = mapped_column(String(100))
    conservation_status: Mapped[str | None] = mapped_column(String(100))
    observations_count:  Mapped[int]        = mapped_column(Integer, default=0)

    # ── Category ──────────────────────────────────────────────────
    category:            Mapped[str | None] = mapped_column(String(50))   # animal/plant/fungi/terrain
    sub_category:        Mapped[str | None] = mapped_column(String(100))  # mammal/bird/tree/rock/etc.

    # ── GBIF ──────────────────────────────────────────────────────
    gbif_key:            Mapped[int | None] = mapped_column(Integer)
    rarity_tier:         Mapped[str | None] = mapped_column(String(50))
    invasive_at_location: Mapped[bool]      = mapped_column(Boolean, default=False)

    # ── Generated card ────────────────────────────────────────────
    blurb:         Mapped[str | None] = mapped_column(Text)
    speed:         Mapped[int | None] = mapped_column(Integer)
    attack:        Mapped[int | None] = mapped_column(Integer)
    defence:       Mapped[int | None] = mapped_column(Integer)
    hp:            Mapped[int | None] = mapped_column(Integer)
    stamina_regen: Mapped[int | None] = mapped_column(Integer)

    # ── Capture metadata ──────────────────────────────────────────
    captured_at:     Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow)
    latitude:        Mapped[float | None] = mapped_column(Float)
    longitude:       Mapped[float | None] = mapped_column(Float)
    capture_country: Mapped[str | None]  = mapped_column(String(10))
    image_url:       Mapped[str | None]  = mapped_column(String(1000))
