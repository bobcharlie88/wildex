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
    invasive_at_location: Mapped[bool] = mapped_column(Boolean, default=False)

    blurb: Mapped[str | None] = mapped_column(Text)
    speed: Mapped[int | None] = mapped_column(Integer)
    attack: Mapped[int | None] = mapped_column(Integer)
    defence: Mapped[int | None] = mapped_column(Integer)
    hp: Mapped[int | None] = mapped_column(Integer)
    stamina_regen: Mapped[int | None] = mapped_column(Integer)

    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    capture_country: Mapped[str | None] = mapped_column(String(10))
    image_url: Mapped[str | None] = mapped_column(String(1000))
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
