"""Static catalogs that power the search box's instant-feeling UI bits:

- `suggest_models` (GET /api/models) - model name autocomplete.
- `get_model_options` (GET /api/model-options) - typical storage/colour
  choices for a model, so the Storage/Colour dropdowns can populate the
  instant a model is picked, with zero network round-trip.

Neither of these touches scraping or matching - those work off whatever the
adapters actually find, for any brand, and remain the source of truth for
what's genuinely available. This catalog only decides what to *offer* in the
dropdowns before a live search has run; hitting Search still queries the
real sources and is what actually confirms availability/price.
"""

# (storage options, colour options), most-recent/likely-picked first.
MODEL_SPECS: dict[str, tuple[list[str], list[str]]] = {
    "iPhone 17 Pro Max": (["256GB", "512GB", "1TB", "2TB"], ["Cosmic Orange", "Deep Blue", "Silver"]),
    "iPhone 17 Pro": (["256GB", "512GB", "1TB", "2TB"], ["Cosmic Orange", "Deep Blue", "Silver"]),
    "iPhone 17": (["256GB", "512GB"], ["Black", "White", "Lavender", "Sage", "Mist Blue"]),
    "iPhone 17e": (["128GB", "256GB", "512GB"], ["Black", "White"]),
    "iPhone 16 Pro Max": (["256GB", "512GB", "1TB"], ["Desert Titanium", "Natural Titanium", "White Titanium", "Black Titanium"]),
    "iPhone 16 Pro": (["128GB", "256GB", "512GB", "1TB"], ["Desert Titanium", "Natural Titanium", "White Titanium", "Black Titanium"]),
    "iPhone 16 Plus": (["128GB", "256GB", "512GB"], ["Black", "White", "Pink", "Teal", "Ultramarine"]),
    "iPhone 16": (["128GB", "256GB", "512GB"], ["Black", "White", "Pink", "Teal", "Ultramarine"]),
    "iPhone 16e": (["128GB", "256GB", "512GB"], ["Black", "White"]),
    "iPhone 15 Pro Max": (["256GB", "512GB", "1TB"], ["Black Titanium", "White Titanium", "Blue Titanium", "Natural Titanium"]),
    "iPhone 15 Pro": (["128GB", "256GB", "512GB", "1TB"], ["Black Titanium", "White Titanium", "Blue Titanium", "Natural Titanium"]),
    "iPhone 15 Plus": (["128GB", "256GB", "512GB"], ["Black", "Blue", "Green", "Yellow", "Pink"]),
    "iPhone 15": (["128GB", "256GB", "512GB"], ["Black", "Blue", "Green", "Yellow", "Pink"]),
    "iPhone 14 Pro Max": (["128GB", "256GB", "512GB", "1TB"], ["Space Black", "Silver", "Gold", "Deep Purple"]),
    "iPhone 14 Pro": (["128GB", "256GB", "512GB", "1TB"], ["Space Black", "Silver", "Gold", "Deep Purple"]),
    "iPhone 14 Plus": (["128GB", "256GB", "512GB"], ["Blue", "Purple", "Midnight", "Starlight", "(PRODUCT)RED"]),
    "iPhone 14": (["128GB", "256GB", "512GB"], ["Blue", "Purple", "Midnight", "Starlight", "(PRODUCT)RED"]),
    "iPhone 13 Pro Max": (["128GB", "256GB", "512GB", "1TB"], ["Graphite", "Gold", "Silver", "Sierra Blue", "Alpine Green"]),
    "iPhone 13 Pro": (["128GB", "256GB", "512GB", "1TB"], ["Graphite", "Gold", "Silver", "Sierra Blue", "Alpine Green"]),
    "iPhone 13 mini": (["128GB", "256GB", "512GB"], ["Pink", "Blue", "Midnight", "Starlight", "(PRODUCT)RED", "Green"]),
    "iPhone 13": (["128GB", "256GB", "512GB"], ["Pink", "Blue", "Midnight", "Starlight", "(PRODUCT)RED", "Green"]),
    "iPhone 12 Pro Max": (["128GB", "256GB", "512GB"], ["Graphite", "Silver", "Gold", "Pacific Blue"]),
    "iPhone 12 Pro": (["128GB", "256GB", "512GB"], ["Graphite", "Silver", "Gold", "Pacific Blue"]),
    "iPhone 12 mini": (["64GB", "128GB", "256GB"], ["Black", "White", "(PRODUCT)RED", "Green", "Blue", "Purple"]),
    "iPhone 12": (["64GB", "128GB", "256GB"], ["Black", "White", "(PRODUCT)RED", "Green", "Blue", "Purple"]),
    "iPhone 11 Pro Max": (["64GB", "256GB", "512GB"], ["Midnight Green", "Space Gray", "Silver", "Gold"]),
    "iPhone 11 Pro": (["64GB", "256GB", "512GB"], ["Midnight Green", "Space Gray", "Silver", "Gold"]),
    "iPhone 11": (["64GB", "128GB", "256GB"], ["Black", "White", "Green", "Yellow", "Purple", "(PRODUCT)RED"]),
    "iPhone SE (3rd generation)": (["64GB", "128GB", "256GB"], ["Midnight", "Starlight", "(PRODUCT)RED"]),
    "iPhone XS Max": (["64GB", "256GB", "512GB"], ["Space Gray", "Silver", "Gold"]),
    "iPhone XS": (["64GB", "256GB", "512GB"], ["Space Gray", "Silver", "Gold"]),
    "iPhone XR": (["64GB", "128GB", "256GB"], ["Black", "White", "Blue", "Yellow", "Coral", "(PRODUCT)RED"]),
    "iPhone X": (["64GB", "256GB"], ["Space Gray", "Silver"]),
    "Samsung Galaxy S24 Ultra": (["256GB", "512GB", "1TB"], ["Titanium Black", "Titanium Gray", "Titanium Violet", "Titanium Yellow"]),
    "Samsung Galaxy S24+": (["256GB", "512GB"], ["Onyx Black", "Marble Gray", "Cobalt Violet", "Amber Yellow"]),
    "Samsung Galaxy S24": (["128GB", "256GB"], ["Onyx Black", "Marble Gray", "Cobalt Violet", "Amber Yellow"]),
    "Google Pixel 9 Pro XL": (["128GB", "256GB", "512GB", "1TB"], ["Obsidian", "Porcelain", "Hazel", "Rose Quartz"]),
    "Google Pixel 9 Pro": (["128GB", "256GB", "512GB", "1TB"], ["Obsidian", "Porcelain", "Hazel", "Rose Quartz"]),
    "Google Pixel 9": (["128GB", "256GB"], ["Obsidian", "Porcelain", "Wintergreen", "Peony"]),
}

# Used for any model not explicitly curated above (a free-typed model, or one
# not yet added here) - broad-enough defaults so the dropdowns still have
# something sensible rather than being empty.
GENERIC_STORAGE_OPTIONS = ["64GB", "128GB", "256GB", "512GB", "1TB"]
GENERIC_COLOUR_OPTIONS = ["Black", "White", "Blue", "Silver", "Gold", "Green"]

KNOWN_MODELS = list(MODEL_SPECS.keys()) + [
    "Samsung Galaxy S23 Ultra", "Samsung Galaxy Z Fold 6", "Samsung Galaxy Z Flip 6",
    "Samsung Galaxy A55", "Samsung Galaxy A35",
    "OnePlus 13", "OnePlus 12", "OnePlus 12R", "OnePlus Nord 4",
    "Google Pixel 8a",
    "Xiaomi 14 Ultra", "Redmi Note 13 Pro", "Poco X6 Pro",
    "Vivo V30 Pro", "Oppo Reno 12 Pro", "Realme 12 Pro+",
    "Nothing Phone (1)", "Nothing Phone (2)", "Nothing Phone (2a)", "Nothing Phone (2a) Plus",
    "Nothing Phone (3)", "Nothing Phone (3a)", "Nothing Phone (3a) Pro",
    "Nothing CMF Phone 1", "Nothing CMF Phone 2 Pro",
    "Motorola Edge 50 Pro",
]


def suggest_models(query: str, limit: int = 10) -> list[str]:
    query = query.strip().lower()
    if not query:
        return KNOWN_MODELS[:limit]

    starts_with = [m for m in KNOWN_MODELS if m.lower().startswith(query)]
    contains = [m for m in KNOWN_MODELS if query in m.lower() and m not in starts_with]
    return (starts_with + contains)[:limit]


def get_model_options(model: str) -> dict[str, list[str]]:
    """Instant, no-network lookup of typical storage/colour choices for a
    model - an exact catalog hit if we have one, else a same-family match
    (e.g. "iphone 16 (256gb)" still matching "iPhone 16"), else generic
    defaults so the dropdowns are never just empty.
    """

    normalized = model.strip().lower()

    if not normalized:
        return {"storage": GENERIC_STORAGE_OPTIONS, "colour": GENERIC_COLOUR_OPTIONS}

    for name, (storage, colour) in MODEL_SPECS.items():
        if name.lower() == normalized:
            return {"storage": storage, "colour": colour}

    for name, (storage, colour) in MODEL_SPECS.items():
        if name.lower() in normalized or normalized in name.lower():
            return {"storage": storage, "colour": colour}

    return {"storage": GENERIC_STORAGE_OPTIONS, "colour": GENERIC_COLOUR_OPTIONS}
