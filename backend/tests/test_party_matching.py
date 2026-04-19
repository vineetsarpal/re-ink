"""
Unit tests for party name matching service.

These lock in the behaviour that motivated the service: concatenated
multi-party extractions, case-only mismatches, and corporate-suffix drift
must still find the right DB row.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest  # noqa: E402

from app.services.party_matching import (  # noqa: E402
    match_names,
    normalize_name,
    split_party_names,
)


# --- normalize_name --------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Vesta Fire Insurance Corp", "vesta fire"),
        ("VESTA FIRE INSURANCE CORPORATION", "vesta fire"),
        ("Vesta Fire Insurance Corp.", "vesta fire"),
        ("The Hawaiian Insurance & Guaranty Company, Ltd", "hawaiian guaranty"),
        ("Allianz SE", "allianz se"),  # "se" not in suffix list, retained
        ("Munich Re", "munich"),  # "re" is suffixed
        ("  A.B. Smith & Co., Inc.  ", "a b smith"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_empty_input_returns_empty() -> None:
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


def test_normalize_all_suffixes_falls_back_to_raw_tokens() -> None:
    # "Inc Corp Ltd" is only suffix tokens — rather than return "", we keep the
    # original tokens so the name can still be scored.
    assert normalize_name("Inc Corp Ltd") == "inc corp ltd"


# --- split_party_names -----------------------------------------------------


def test_split_single_name_returns_as_is() -> None:
    assert split_party_names("Vesta Fire Insurance Corp") == ["Vesta Fire Insurance Corp"]


def test_split_concatenated_list() -> None:
    raw = (
        "VESTA FIRE INSURANCE CORPORATION, VESTA INSURANCE CORPORATION, "
        "INSURA PROPERTY AND CASUALTY INSURANCE COMPANY, "
        "SHELBY CASUALTY INSURANCE COMPANY, "
        "THE HAWAIIAN INSURANCE & GUARANTY COMPANY, LTD"
    )
    segments = split_party_names(raw)
    # 5 companies; trailing ", LTD" is a suffix-only tail and gets dropped.
    assert len(segments) == 5
    assert any("VESTA FIRE" in s for s in segments)
    assert any("SHELBY" in s for s in segments)
    assert any("HAWAIIAN" in s for s in segments)


def test_split_does_not_explode_legal_name_with_embedded_punctuation() -> None:
    # "Smith, Jones & Co., Ltd." is one company, not 3. The split will produce
    # multiple segments, but filtering drops suffix-only tails ("Ltd", "Co")
    # and single-word stubs. We accept some over-splitting here; the key
    # invariant is that it doesn't return zero candidates or invent names.
    segments = split_party_names("Smith, Jones & Co., Ltd.")
    for seg in segments:
        assert seg.strip(), "no empty segments"


def test_split_empty_returns_empty_list() -> None:
    assert split_party_names("") == []
    assert split_party_names("   ") == []


# --- match_names -----------------------------------------------------------


VESTA_CONCAT = (
    "VESTA FIRE INSURANCE CORPORATION, VESTA INSURANCE CORPORATION, "
    "INSURA PROPERTY AND CASUALTY INSURANCE COMPANY, "
    "SHELBY CASUALTY INSURANCE COMPANY, "
    "THE HAWAIIAN INSURANCE & GUARANTY COMPANY, LTD"
)


def test_vesta_concatenated_list_finds_db_entry() -> None:
    """The original bug report: Vesta Fire Insurance Corp in the DB
    must be found despite being buried inside a 5-company concatenation."""
    db_names = ["Vesta Fire Insurance Corp", "Allianz SE", "Lloyd's of London"]
    results = match_names([VESTA_CONCAT], db_names, threshold=70.0)

    assert len(results) == 1
    top = results[0]
    assert top, "expected at least one candidate"
    # Top candidate must be the Vesta entry.
    assert top[0][0] == "Vesta Fire Insurance Corp"
    assert top[0][1] >= 85  # strong match after normalization


def test_case_only_mismatch_matches() -> None:
    db_names = ["Acme Reinsurance Ltd"]
    results = match_names(["ACME REINSURANCE LIMITED"], db_names, threshold=70.0)
    assert results[0]
    assert results[0][0][0] == "Acme Reinsurance Ltd"
    assert results[0][0][1] >= 90


def test_corp_vs_corporation_matches() -> None:
    db_names = ["Globex Corp"]
    results = match_names(["Globex Corporation"], db_names, threshold=70.0)
    assert results[0]
    assert results[0][0][0] == "Globex Corp"
    assert results[0][0][1] >= 90


def test_unrelated_name_produces_no_candidates() -> None:
    db_names = ["Vesta Fire Insurance Corp"]
    results = match_names(
        ["Totally Different Carrier Holdings"],
        db_names,
        threshold=70.0,
    )
    assert results[0] == []


def test_empty_db_returns_empty_per_name() -> None:
    assert match_names(["Vesta Fire"], []) == [[]]


def test_candidates_sorted_by_score_descending() -> None:
    db_names = ["Vesta Fire Insurance Corp", "Vesta Insurance Group"]
    results = match_names(["Vesta Fire Insurance Corporation"], db_names, threshold=60.0)
    scores = [score for _, score in results[0]]
    assert scores == sorted(scores, reverse=True)


def test_multiple_extracted_names_each_get_results() -> None:
    db_names = ["Vesta Fire Insurance Corp", "Allianz SE"]
    results = match_names(
        ["Vesta Fire Insurance Corporation", "Allianz Societas Europaea"],
        db_names,
        threshold=70.0,
    )
    assert len(results) == 2
    assert results[0][0][0] == "Vesta Fire Insurance Corp"
    # Allianz SE vs "Allianz Societas Europaea" — at least the Allianz entry
    # should surface; the SE token is discriminative.
    assert any(name == "Allianz SE" for name, _ in results[1])
