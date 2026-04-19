"""
Party name matching with normalization and multi-party splitting.

Why a dedicated module:
 - The raw rapidfuzz scorers fall apart on real reinsurance extractions. Two
   real failure modes: (a) the extractor returns several party names joined
   with commas (one name field for the whole party list), and (b) the DB
   holds "Acme Corp" while the extraction has "ACME CORPORATION" — case plus
   suffix differences sink token_sort_ratio below any useful threshold.
 - Normalizing names and splitting candidate lists before scoring consistently
   recovers the right matches, without lowering the threshold so far that the
   top result becomes noise.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from rapidfuzz import fuzz, process as rfprocess


# Corporate / legal-form tokens that carry no matching signal. Compared after
# lowercasing and punctuation stripping, so "L.L.C." → "llc" still matches.
_SUFFIX_TOKENS: frozenset[str] = frozenset(
    {
        "inc", "incorporated",
        "corp", "corporation", "corporations",
        "co", "company",
        "ltd", "limited",
        "llc", "llp", "lp",
        "plc",
        "sa", "s.a",
        "ag",
        "gmbh",
        "nv", "bv",
        "pty", "pte",
        "srl", "spa",
        "kk",
        "oy", "ab",
        "group", "holdings", "holding",
        "reinsurance", "re",
        "insurance",
    }
)

# Non-discriminative connector tokens stripped during normalization so
# "Property and Casualty" and "Property & Casualty" score identically.
_NOISE_TOKENS: frozenset[str] = frozenset({"the", "and", "of"})

# Tokens whose presence as the sole content of a split segment means the
# segment is a legal-form tail, not a real company name.
_STOPWORD_ONLY_SEGMENTS: frozenset[str] = frozenset(_SUFFIX_TOKENS | _NOISE_TOKENS)

_PUNCT_RE = re.compile(r"[^\w\s&]")
_WHITESPACE_RE = re.compile(r"\s+")

# Splitting only on commas, semicolons, and newlines. Splitting on " and "
# or " & " looks tempting for list joins ("Acme and Globex") but fires far
# more often on intra-name conjunctions ("Property and Casualty Insurance
# Company", "Hawaiian Insurance & Guaranty Company") and shreds real names.
_SPLIT_RE = re.compile(r"\s*[,;\n\r]\s*")


def normalize_name(name: str) -> str:
    """Return a canonical, lower-case form with suffixes and punctuation removed.

    The returned string is only used for *scoring* — the original display name
    is preserved separately so users still see the real company name in the UI.
    """
    if not name:
        return ""

    s = name.lower()
    s = s.replace("&", " and ")
    s = _PUNCT_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()

    if not s:
        return ""

    tokens = [
        t for t in s.split(" ")
        if t and t not in _SUFFIX_TOKENS and t not in _NOISE_TOKENS
    ]
    # If stripping leaves nothing (e.g. input was just "Inc" or "The and"),
    # fall back to the original token set so the name isn't reduced to empty.
    if not tokens:
        tokens = s.split(" ")

    return " ".join(tokens)


def split_party_names(raw: str) -> list[str]:
    """Split a single extracted ``name`` field into individual candidate names.

    Returns the original string if it doesn't look like a list. A segment is
    kept only if it has at least two tokens after normalization — this prevents
    legal-name tails like "Ltd." in "Smith, Jones & Co., Ltd." from being
    treated as a separate party.
    """
    if not raw or not raw.strip():
        return []

    segments = [seg.strip() for seg in _SPLIT_RE.split(raw) if seg and seg.strip()]

    if len(segments) <= 1:
        return [raw.strip()]

    plausible: list[str] = []
    for seg in segments:
        norm = normalize_name(seg)
        if not norm:
            continue
        if norm in _STOPWORD_ONLY_SEGMENTS:
            continue
        # A plausible standalone party has at least 2 meaningful tokens
        # (normalized). Single-token segments like "Ltd" or "Holdings" get
        # dropped; single-token segments that are a real distinctive word
        # (e.g. "Allianz") are kept by also allowing >= 5 chars.
        tokens = norm.split(" ")
        if len(tokens) >= 2 or (len(tokens) == 1 and len(tokens[0]) >= 5):
            plausible.append(seg)

    # If splitting produced nothing usable, fall back to the raw input — better
    # to score a long messy string than to return zero candidates.
    return plausible or [raw.strip()]


def match_names(
    extracted_names: Sequence[str],
    db_names: Iterable[str],
    *,
    threshold: float = 75.0,
    limit: int = 5,
) -> list[list[tuple[str, float]]]:
    """Match each extracted name against ``db_names`` with normalization.

    For each extracted name we:
      1. Split on list delimiters (comma, semicolon, " and ").
      2. Normalize each segment and every DB name.
      3. Score with ``fuzz.WRatio`` (blends partial/token-set/token-sort,
         which handles case, suffix, and substring drift well).
      4. Merge candidates across segments keeping the max score per DB name.

    Returns a list (one per extracted name) of ``(db_name, score)`` tuples,
    each sorted by score descending and capped at ``limit``.
    """
    db_name_list = list(db_names)
    if not db_name_list:
        return [[] for _ in extracted_names]

    # Pre-compute normalized DB names once; pass the raw name back for display.
    normalized_to_raw: dict[str, str] = {}
    for raw in db_name_list:
        norm = normalize_name(raw)
        if not norm:
            continue
        # If two different DB entries normalize identically, keep the first —
        # the endpoint resolves back to the Party row via its original name.
        normalized_to_raw.setdefault(norm, raw)

    normalized_db = list(normalized_to_raw.keys())

    results: list[list[tuple[str, float]]] = []
    for extracted in extracted_names:
        segments = split_party_names(extracted)
        merged: dict[str, float] = {}  # normalized DB name → best score

        for seg in segments:
            seg_norm = normalize_name(seg)
            if not seg_norm:
                continue

            matches = rfprocess.extract(
                seg_norm,
                normalized_db,
                scorer=fuzz.WRatio,
                limit=limit * 2,  # over-fetch; merge trims back to `limit`
                score_cutoff=threshold,
            )
            for norm_name, score, _idx in matches:
                if score > merged.get(norm_name, 0):
                    merged[norm_name] = score

        ranked = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        results.append([(normalized_to_raw[n], round(s, 1)) for n, s in ranked])

    return results
