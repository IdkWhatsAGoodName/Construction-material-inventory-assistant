"""Conservative deterministic catalogue matching."""

from __future__ import annotations

import re
import unicodedata

_TOKEN_ALIASES = {
    "inch": "in",
    "inches": "in",
    "foot": "ft",
    "feet": "ft",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "beams": "beam",
    "rebars": "rebar",
    "sheets": "sheet",
    "lengths": "length",
}
_IGNORED_TOKENS = {"a", "an", "the", "of", "for", "our"}


def normalize_text(value: str) -> str:
    """Normalize Unicode, casing, punctuation, controlled aliases, and filler words."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("_", " ")
    tokens = re.findall(r"[\w]+", normalized, flags=re.UNICODE)
    canonical = (
        _TOKEN_ALIASES.get(token, token) for token in tokens if token not in _IGNORED_TOKENS
    )
    return " ".join(canonical)


def normalized_tokens(value: str) -> frozenset[str]:
    return frozenset(normalize_text(value).split())


def all_tokens_match(query: str, fields: tuple[str, ...]) -> bool:
    query_tokens = normalized_tokens(query)
    if not query_tokens:
        return True
    field_tokens = normalized_tokens(" ".join(fields))
    return query_tokens <= field_tokens
