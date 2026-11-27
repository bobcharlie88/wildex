"""Curated, fact-checked card text and range data keyed by scientific name.

Used by the field-guide card front. Anything here overrides the generic
generated copy, so only add entries that have been checked.
"""
from __future__ import annotations

# Pilbara bioregion outline (lon, lat), simplified.
PILBARA = [
    (114.1, -21.8), (116.5, -20.6), (118.6, -20.2), (121.2, -19.8), (123.6, -21.3),
    (123.8, -23.8), (121.8, -26.2), (120.2, -27.0), (117.6, -27.6), (115.6, -28.7),
    (114.4, -27.6), (113.5, -25.6), (113.6, -23.2),
]

CURATED: dict[str, dict] = {
    "antaresia perthensis": {
        "info_text": (
            "The pygmy python is the world's smallest python \u2013 adults reach only about 50\u201360 cm. "
            "Non-venomous and found only in Western Australia's Pilbara and nearby regions, it shelters in "
            "spinifex, rocky ranges and termite mounds, ambushing geckos and small skinks."
        ),
        "fact_text": (
            "Despite its name, perthensis doesn't live near Perth \u2013 the first specimen was wrongly "
            "labelled as coming from there."
        ),
        "taxonomy": {
            "kingdom": "Animalia", "phylum": "Chordata", "class": "Reptilia",
            "order": "Squamata", "family": "Pythonidae",
        },
        "range_mode": "region",
        "range_regions": ["AU"],
        "range_polygons": [[list(p) for p in PILBARA]],
        "range_label": "Pilbara, WA",
        "biome_frame": "rocky",
    },
}


def curated_for(scientific_name: str | None) -> dict:
    if not scientific_name:
        return {}
    return CURATED.get(" ".join(str(scientific_name).lower().split()), {})
