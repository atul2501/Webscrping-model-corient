"""Turns a messy, source-specific product name (plus optional structured hints
an adapter may already have, e.g. an explicit colour swatch value) into a
canonical brand / model / storage / colour, and a deterministic variant_key
used to group the same product/variant across sources.

Deliberately generic - no smartphone model is hard-coded as a special case
beyond a keyword table of brand names and a few colour aliases, so it works
for any brand/model the adapters hand it, not just iPhones.

Real product titles observed from the two live, working sources follow one
of two shapes:
  "Apple iPhone 17 Pro (256GB Storage, Black)"          (Vijay Sales / GraphQL)
  "OPPO Reno16c 256 GB, 8 GB RAM, Stellar Purple, Mobile Phone"  (Reliance Digital)
Both are comma/parenthesis-delimited spec lists with brand+model first and
colour last, once RAM/storage/filler segments are discarded - that shape
drives the segment-based colour extraction below, rather than trying to
guess colour from unstructured free text.
"""

import re
from dataclasses import dataclass

BRAND_KEYWORDS = {
    "apple": "Apple",
    "iphone": "Apple",
    "samsung": "Samsung",
    "galaxy": "Samsung",
    "oneplus": "OnePlus",
    "xiaomi": "Xiaomi",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "vivo": "Vivo",
    "oppo": "Oppo",
    "realme": "Realme",
    "google": "Google",
    "pixel": "Google",
    "nothing": "Nothing",
    "motorola": "Motorola",
    "moto": "Motorola",
    "iqoo": "iQOO",
    "asus": "Asus",
    "honor": "Honor",
    "infinix": "Infinix",
    "tecno": "Tecno",
    "lava": "Lava",
    "nokia": "Nokia",
}

# A handful of BRAND_KEYWORDS entries are product-line names, not just
# company-name synonyms - "iPhone"/"Galaxy"/"Pixel" are part of how a human
# reads the model ("iPhone 17 Pro", not just "17 Pro"), even though they're
# also enough on their own to identify the brand. These are used for brand
# *detection* like any other keyword, but kept in the model text rather than
# stripped out.
_PRODUCT_LINE_KEYWORDS = {"iphone", "galaxy", "pixel", "redmi", "poco", "moto"}

COLOUR_ALIASES = {
    "space grey": "Space Gray",
    "space gray": "Space Gray",
    "spacegray": "Space Gray",
    "product red": "(PRODUCT)RED",
    "ultra marine": "Ultramarine",
    "ultramarine": "Ultramarine",
}

_FILLER_WORDS = {
    "with", "mobile", "phone", "smartphone", "5g", "4g", "dual", "sim",
    "storage", "internal", "variant", "colour", "color", "new", "latest",
}

_RAM_RE = re.compile(r"\b\d{1,2}\s*-?\s*gb\s*ram\b", re.IGNORECASE)
_STORAGE_RE = re.compile(r"\b(\d{1,4})\s*-?\s*(gb|tb)\b(?!\s*ram)", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[(),/|_\-]+")
_MULTI_SPACE_RE = re.compile(r"\s+")
# Split "iphone17pro" -> "iphone 17 pro", but don't split a digit from a
# single trailing suffix letter like "17e"/"16e" (real Apple model names).
_ALPHA_NUM_BOUNDARY_RE = re.compile(r"(?<=[a-zA-Z])(?=\d)|(?<=\d)(?=[a-zA-Z]{2,})")
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
# Some sources (e.g. Vijay Sales' GraphQL search) append a trailing SKU code
# to the product name, e.g. "... Black) P245180" or even "...Black)P245180"
# with no space at all - strip it before parsing either way.
_TRAILING_SKU_RE = re.compile(r"\s*[A-Z]?\d{5,8}$")


@dataclass
class ParsedProduct:
    brand: str
    model: str
    storage: str | None  # human label, e.g. "256GB" or "1TB"
    storage_gb: int | None  # normalized integer for comparisons across units
    colour: str | None
    variant_key: str


def _storage_to_gb(value: int, unit: str) -> int:
    return value * 1024 if unit.lower() == "tb" else value


def _extract_storage(text: str) -> tuple[str | None, int | None, str]:
    match = _STORAGE_RE.search(text)
    if not match:
        return None, None, text
    value, unit = int(match.group(1)), match.group(2).upper()
    label = f"{value}{unit}"
    remaining = text[: match.start()] + " " + text[match.end() :]
    return label, _storage_to_gb(value, unit), remaining


def _segment_is_filler_or_empty(segment: str) -> bool:
    tokens = [t.lower() for t in _WORD_RE.findall(segment)]
    if not tokens:
        return True
    return all(token in _FILLER_WORDS for token in tokens)


def _segment_is_ram_only(segment: str) -> bool:
    if not _RAM_RE.search(segment):
        return False
    stripped = _RAM_RE.sub(" ", segment)
    return _segment_is_filler_or_empty(stripped)


def _segment_is_storage_only(segment: str) -> bool:
    _, storage_gb, remainder = _extract_storage(segment)
    if storage_gb is None:
        return False
    return _segment_is_filler_or_empty(remainder)


def _extract_colour_segment(segments: list[str]) -> str | None:
    """Among the spec segments after the model segment, the last segment
    that isn't purely storage/RAM/filler is treated as the colour - matches
    the comma/paren/pipe-delimited shape real listing titles use.
    """

    colour_candidate = None
    for segment in segments:
        if _segment_is_ram_only(segment) or _segment_is_storage_only(segment) or _segment_is_filler_or_empty(segment):
            continue
        colour_candidate = segment
    return colour_candidate


def _extract_brand(text: str) -> tuple[str | None, str]:
    lowered = text.lower()
    canonical_brand = None
    for keyword, canonical in sorted(BRAND_KEYWORDS.items(), key=lambda kv: -len(kv[0])):
        if keyword in lowered:
            canonical_brand = canonical
            break
    if canonical_brand is None:
        return None, text

    # Strip every non-product-line alias that maps to this brand (e.g.
    # "apple" is redundant with the brand field and gets removed), but keep
    # product-line keywords like "iphone"/"galaxy" in the model text - they
    # read as part of the model name, not just a brand signal.
    aliases = [
        kw for kw, canon in BRAND_KEYWORDS.items()
        if canon == canonical_brand and kw not in _PRODUCT_LINE_KEYWORDS
    ]
    if not aliases:
        return canonical_brand, text
    pattern = re.compile(r"\b(" + "|".join(re.escape(a) for a in aliases) + r")\b", re.IGNORECASE)
    return canonical_brand, pattern.sub(" ", text)


def _normalize_colour(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _MULTI_SPACE_RE.sub(" ", _NON_WORD_RE.sub(" ", raw)).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in COLOUR_ALIASES:
        return COLOUR_ALIASES[lowered]
    return " ".join(word.capitalize() for word in cleaned.split(" "))


def _normalize_model_text(text: str) -> str:
    cleaned = _NON_WORD_RE.sub(" ", text)
    cleaned = _RAM_RE.sub(" ", cleaned)
    tokens = [t for t in cleaned.split() if t.lower() not in _FILLER_WORDS]
    cleaned = " ".join(tokens)
    # "iphone17pro" -> "iphone 17 pro"
    cleaned = _ALPHA_NUM_BOUNDARY_RE.sub(" ", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()

    def _title(word: str) -> str:
        if word.lower() == "iphone":
            return "iPhone"
        if re.fullmatch(r"\d+[a-z]?", word, re.IGNORECASE):
            return word.lower()
        return word.capitalize()

    return " ".join(_title(w) for w in cleaned.split(" "))


def parse_product_name(
    raw_name: str,
    *,
    colour_hint: str | None = None,
    storage_hint: str | None = None,
    brand_hint: str | None = None,
) -> ParsedProduct:
    """Parse a raw, source-specific product title into normalized fields.

    `*_hint` values come from structured source data (e.g. a colour swatch
    attribute) when an adapter has it - these are far more reliable than
    parsing free text and take priority over what's extracted from raw_name.
    """

    raw_name = _TRAILING_SKU_RE.sub("", raw_name.strip())

    storage_label, storage_gb, _ = _extract_storage(raw_name)
    if storage_hint:
        hint_label, hint_gb, _ = _extract_storage(storage_hint)
        if hint_gb:
            storage_label, storage_gb = hint_label, hint_gb

    # Real listing titles delimit their spec list with commas/parens
    # ("Apple iPhone 17 Pro (256GB Storage, Black)") or with pipes
    # ("Nothing Phone (4a) Pro 5G (8GB RAM, 128GB Storage) | Snapdragon ... |
    # Silver") - normalize both shapes to the same comma-segment split.
    flattened = raw_name.replace("(", ",").replace(")", "").replace("|", ",")
    segments = [s.strip() for s in flattened.split(",") if s.strip()]
    model_segment = segments[0] if segments else raw_name
    rest_segments = segments[1:]

    # Some product lines put part of the model number in the very next
    # parenthetical right after the brand name, e.g. "Nothing Phone (4a)
    # Pro 5G ..." rather than starting the spec list there. If the first
    # segment strips down to nothing once the brand name is removed, and
    # the next segment isn't itself a spec segment (storage/RAM), it's
    # really a continuation of the model name, not the start of specs.
    brand, model_working = _extract_brand(model_segment)
    while not _normalize_model_text(model_working) and rest_segments and not (
        _segment_is_ram_only(rest_segments[0]) or _segment_is_storage_only(rest_segments[0])
    ):
        model_segment = f"{model_segment} {rest_segments[0]}"
        rest_segments = rest_segments[1:]
        brand, model_working = _extract_brand(model_segment)

    if brand_hint:
        brand = brand_hint

    colour_segment = _extract_colour_segment(rest_segments)
    colour = _normalize_colour(colour_hint) if colour_hint else _normalize_colour(colour_segment)

    # Storage can still be embedded inside the model segment itself, e.g.
    # "Reno16c 256 GB" - strip it out of the text used for the model name.
    _, _, model_working = _extract_storage(model_working)
    model = _normalize_model_text(model_working)

    variant_key = "|".join(
        [
            (brand or "unknown").lower(),
            model.lower(),
            str(storage_gb) if storage_gb else "unknown",
            (colour or "any").lower(),
        ]
    )

    return ParsedProduct(
        brand=brand or "Unknown",
        model=model,
        storage=storage_label,
        storage_gb=storage_gb,
        colour=colour,
        variant_key=variant_key,
    )
