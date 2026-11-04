"""Biome / terrain card content: 2 buffs, 2 debuffs and area info for the card back."""
from __future__ import annotations

# Each profile: keywords matched against name/sub_category/blurb.
PROFILES = [
    {
        "key": "arid", "biome": "Arid Grassland",
        "keywords": ["spinifex", "hummock", "desert", "arid", "dune", "sand", "outback", "gibber", "saltbush", "mulga", "pilbara"],
        "buffs": [
            {"name": "Hummock Cover", "effect": "+20% stealth sheltering in spinifex and low scrub"},
            {"name": "Open Sightlines", "effect": "+20% navigation across flat, open country"},
        ],
        "debuffs": [
            {"name": "Extreme Heat", "effect": "Heat fatigue: -25% stamina in midday sun (40°C+)"},
            {"name": "Dehydration", "effect": "-20% HP each turn without a water source"},
        ],
        "climate": "Hot, dry; summer days often 40°C+, cold clear nights, erratic rain",
        "hazards": "Heatstroke, dehydration, fatigue, sharp spinifex spines, bushfire",
        "life": "Hopping mice, dunnarts, dragons, skinks, termites, zebra finches",
    },
    {
        "key": "rock", "biome": "Rocky Outcrop",
        "keywords": ["rock", "granite", "sandstone", "limestone", "cliff", "gorge", "outcrop", "boulder", "scree", "range", "escarpment"],
        "buffs": [
            {"name": "Crevice Shelter", "effect": "+20% defence when sheltering among rocks"},
            {"name": "High Ground", "effect": "+20% scouting from elevated ledges"},
        ],
        "debuffs": [
            {"name": "Radiant Heat", "effect": "-20% stamina as rock surfaces bake in the sun"},
            {"name": "Loose Footing", "effect": "-15% speed on scree and unstable slopes"},
        ],
        "climate": "Exposed; rock stores heat by day and releases it at night",
        "hazards": "Falls, rockslides, heat reflection, flash floods in gorges",
        "life": "Rock wallabies, geckos, dragons, raptors, ferns in shaded clefts",
    },
    {
        "key": "water", "biome": "Wetland / Waterway",
        "keywords": ["river", "creek", "lake", "wetland", "swamp", "billabong", "estuary", "mangrove", "water", "pool", "marsh"],
        "buffs": [
            {"name": "Fresh Water", "effect": "+25% HP recovery near permanent water"},
            {"name": "Rich Foraging", "effect": "+20% food finds along the margins"},
        ],
        "debuffs": [
            {"name": "Deep Mud", "effect": "-25% speed in boggy ground"},
            {"name": "Biting Insects", "effect": "-15% stamina from mosquitoes and midges"},
        ],
        "climate": "Humid, cooler microclimate; levels change with season and floods",
        "hazards": "Drowning, strong currents, crocodiles (north), disease-carrying insects",
        "life": "Waterbirds, frogs, fish, turtles, rakali, reeds and sedges",
    },
    {
        "key": "coast", "biome": "Coastline",
        "keywords": ["beach", "coast", "shore", "reef", "ocean", "sea", "tidal", "headland", "bay"],
        "buffs": [
            {"name": "Sea Breeze", "effect": "+20% stamina from cooling onshore winds"},
            {"name": "Tidal Bounty", "effect": "+20% foraging at low tide"},
        ],
        "debuffs": [
            {"name": "Sun & Salt", "effect": "-20% HP from UV exposure and salt"},
            {"name": "Rip Currents", "effect": "-30% speed and high risk in surf"},
        ],
        "climate": "Mild and windy; strong sun, salt spray, tidal change twice daily",
        "hazards": "Rips, king waves, sunburn, stingers, slippery rock platforms",
        "life": "Shorebirds, crabs, dolphins, seagrass, dune plants",
    },
    {
        "key": "forest", "biome": "Forest / Woodland",
        "keywords": ["forest", "woodland", "jarrah", "karri", "eucalypt", "rainforest", "bush", "canopy", "tree"],
        "buffs": [
            {"name": "Canopy Shade", "effect": "+20% stamina under cool cover"},
            {"name": "Dense Cover", "effect": "+20% stealth among trunks and understorey"},
        ],
        "debuffs": [
            {"name": "Disorientation", "effect": "-20% navigation with few landmarks"},
            {"name": "Ticks & Leeches", "effect": "-10% HP from parasites in damp litter"},
        ],
        "climate": "Shaded and moderated; wetter and cooler than open country",
        "hazards": "Getting lost, falling limbs, bushfire, ticks, snakes",
        "life": "Possums, quolls, cockatoos, fungi, orchids, understorey shrubs",
    },
    {
        "key": "mountain", "biome": "Alpine / Highland",
        "keywords": ["mountain", "alpine", "peak", "summit", "highland", "snow", "plateau", "volcano"],
        "buffs": [
            {"name": "Vantage Point", "effect": "+25% scouting from altitude"},
            {"name": "Cool Air", "effect": "+15% endurance in low temperatures"},
        ],
        "debuffs": [
            {"name": "Exposure", "effect": "-25% HP in wind chill and sudden storms"},
            {"name": "Altitude Fatigue", "effect": "-20% stamina on steep climbs"},
        ],
        "climate": "Cold and changeable; snow or storms possible in any season",
        "hazards": "Hypothermia, whiteouts, falls, lightning, fatigue",
        "life": "Alpine herbs, pygmy possums, ravens, mosses and lichens",
    },
]

DEFAULT_PROFILE = {
    "key": "landscape", "biome": "Open Landscape",
    "buffs": [
        {"name": "Open Ground", "effect": "+15% navigation over open terrain"},
        {"name": "Local Knowledge", "effect": "+15% foraging once the area is mapped"},
    ],
    "debuffs": [
        {"name": "Sun Exposure", "effect": "-20% stamina without shade"},
        {"name": "Fatigue", "effect": "-15% speed over long distances"},
    ],
    "climate": "Varies with season and region",
    "hazards": "Heat, dehydration, fatigue, sudden weather change",
    "life": "Local plants, insects, birds and reptiles",
}


def terrain_profile(*texts: str | None) -> dict:
    hay = " ".join(t for t in texts if t).lower()
    best, best_hits = DEFAULT_PROFILE, 0
    for profile in PROFILES:
        hits = sum(1 for kw in profile["keywords"] if kw in hay)
        if hits > best_hits:
            best, best_hits = profile, hits
    return best
