from __future__ import annotations


REGION_LABELS = {
    "AU": "Australia",
    "NA": "North America",
    "SA": "South America",
    "EU": "Europe",
    "AF": "Africa",
    "AS": "Asia",
}


GROUP_META = {
    "DRG": ("Animals", "Reptiles", "Dragons"),
    "GEK": ("Animals", "Reptiles", "Geckos"),
    "SKN": ("Animals", "Reptiles", "Skinks"),
    "SNK": ("Animals", "Reptiles", "Snakes"),
    "TRT": ("Animals", "Reptiles", "Turtles"),
    "CRO": ("Animals", "Reptiles", "Crocs"),
    "LIZ": ("Animals", "Reptiles", "Lizards"),
    "MAR": ("Animals", "Mammals", "Marsupials"),
    "BAT": ("Animals", "Mammals", "Bats"),
    "SEA": ("Animals", "Mammals", "Marine Mammals"),
    "ROD": ("Animals", "Mammals", "Rodents"),
    "MAM": ("Animals", "Mammals", "Mammals"),
    "RAP": ("Animals", "Birds", "Raptors"),
    "PAR": ("Animals", "Birds", "Parrots"),
    "BRD": ("Animals", "Birds", "Birds"),
    "EST": ("Animals", "Fish / Marine", "Estuary Fish"),
    "REF": ("Animals", "Fish / Marine", "Reef Fish"),
    "SHK": ("Animals", "Fish / Marine", "Sharks / Rays"),
    "FSH": ("Animals", "Fish / Marine", "Fish"),
    "MED": ("Plants", "Medicinal", "Medicinal"),
    "TRE": ("Plants", "Trees", "Trees"),
    "FLW": ("Plants", "Flowers", "Flowers"),
    "GRS": ("Plants", "Grasses", "Grasses"),
    "CCT": ("Plants", "Cacti", "Cacti"),
    "AQP": ("Plants", "Aquatic", "Aquatic"),
    "SHB": ("Plants", "Shrubs", "Shrubs"),
    "BOT": ("Plants", "Botanical", "Botanical"),
    "LEP": ("Insects", "Butterflies / Moths", "Butterflies / Moths"),
    "BET": ("Insects", "Beetles", "Beetles"),
    "ODO": ("Insects", "Dragonflies", "Dragonflies"),
    "INS": ("Insects", "Insects", "Insects"),
    "FRG": ("Animals", "Amphibians", "Frogs"),
    "AMP": ("Animals", "Amphibians", "Amphibians"),
    "FNG": ("Fungi", "Fungi", "Fungi"),
    "WTR": ("Terrain", "Terrain", "Water Features"),
    "SOL": ("Terrain", "Terrain", "Soils"),
    "ROC": ("Terrain", "Terrain", "Rock Formations"),
}


def taxonomy_for_entry(
    *,
    category: str | None,
    sub_category: str | None,
    group_code: str | None,
    kingdom: str | None = None,
) -> dict:
    group_code = (group_code or "").upper()
    if group_code in GROUP_META:
        kingdom_root, major_category, family = GROUP_META[group_code]
    else:
        category_l = (category or "").lower()
        sub_l = (sub_category or kingdom or "").lower()
        if category_l == "plant":
            kingdom_root, major_category, family = "Plants", "Plants", group_code or "Group"
        elif category_l == "fungi":
            kingdom_root, major_category, family = "Fungi", "Fungi", group_code or "Group"
        elif category_l == "terrain":
            kingdom_root, major_category, family = "Terrain", "Terrain", group_code or "Group"
        elif sub_l in {"insect", "arachnid"}:
            kingdom_root, major_category, family = "Insects", "Insects", group_code or "Group"
        elif sub_l == "reptile":
            kingdom_root, major_category, family = "Animals", "Reptiles", group_code or "Group"
        elif sub_l == "mammal":
            kingdom_root, major_category, family = "Animals", "Mammals", group_code or "Group"
        elif sub_l == "bird":
            kingdom_root, major_category, family = "Animals", "Birds", group_code or "Group"
        elif sub_l in {"fish", "marine"}:
            kingdom_root, major_category, family = "Animals", "Fish / Marine", group_code or "Group"
        elif sub_l == "amphibian":
            kingdom_root, major_category, family = "Animals", "Amphibians", group_code or "Group"
        else:
            kingdom_root, major_category, family = "Other", "Other", group_code or "Group"

    return {
        "kingdom_root": kingdom_root,
        "major_category": major_category,
        "family": family,
    }
