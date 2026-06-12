"""
Unit tests for source grounding in the LandingAI extraction parser.

These use a synthetic fixture that mirrors the documented LandingAI ADE
response shape (parse `chunks` with id/page/box/markdown, and extract
`extraction_metadata` mapping each field to {value, references:[...]}). They
prove the reference-resolution logic end to end without a live API key.

NB: real-API grounding cannot be verified here — there is no live key — so the
mapping between `references` and parse chunk ids is exercised against the
documented contract, not a live response. See README for the caveat.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest  # noqa: E402

from app.services.landingai_service import landingai_service  # noqa: E402


def _chunk(chunk_id: str, page: int, markdown: str) -> dict:
    """A parse chunk mirroring the SDK ParseResponse.Chunk shape."""
    return {
        "id": chunk_id,
        "type": "chunkText",
        "markdown": markdown,
        "grounding": {
            "page": page,  # 0-indexed, as LandingAI returns it
            "box": {"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.3},
        },
    }


def _raw_results() -> dict:
    """A full raw_results payload mirroring parse + extract responses."""
    chunks = [
        _chunk("uuid-name", 0, "PROPERTY QUOTA SHARE REINSURANCE TREATY 2024"),
        _chunk("uuid-cedant", 0, "between Acme Insurance Co (the 'Company')"),
        _chunk("uuid-reinsurer", 0, "and Global Re Ltd (the 'Reinsurer')"),
        _chunk("uuid-premium", 1, "Reinsurer receives 100% of gross net written premium income."),
    ]
    extraction = {
        "contract_name": "Property Quota Share Reinsurance Treaty 2024",
        "contract_type": "Treaty",
        "cedant_name": "Acme Insurance Co",
        "reinsurer_name": "Global Re Ltd",
        "premium_text": "100% of gross net written premium income",
        # currency present but has no grounding reference -> "no source"
        "currency": "USD",
    }
    extraction_metadata = {
        "contract_name": {"value": extraction["contract_name"], "references": ["uuid-name"]},
        "cedant_name": {"value": extraction["cedant_name"], "references": ["uuid-cedant"]},
        "reinsurer_name": {"value": extraction["reinsurer_name"], "references": ["uuid-reinsurer"]},
        "premium_text": {"value": extraction["premium_text"], "references": ["uuid-premium"]},
        # contract_type references a table-cell id that is NOT a chunk -> page salvage
        "contract_type": {"value": "Treaty", "references": ["2-u"]},
        # currency has an empty references list -> no source
        "currency": {"value": "USD", "references": []},
    }
    return {
        "parse_result": {"markdown": "irrelevant", "chunks": chunks},
        "extract_result": {
            "extraction": extraction,
            "extraction_metadata": extraction_metadata,
        },
        "metadata": {"filename": "treaty.pdf"},
    }


@pytest.fixture
def parsed():
    return landingai_service.parse_extraction_results(_raw_results())


def test_field_sources_present(parsed):
    assert "field_sources" in parsed
    fs = parsed["field_sources"]
    assert set(fs.keys()) == {"contract", "parties"}


def test_contract_name_grounded_with_full_evidence(parsed):
    src = parsed["field_sources"]["contract"]["contract_name"]
    assert src["source_text"].startswith("PROPERTY QUOTA SHARE")
    assert src["page_number"] == 1  # 0-indexed page 0 -> 1-indexed
    assert src["chunk_id"] == "uuid-name"
    assert src["bbox"] == {"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.3}


def test_premium_description_maps_from_text_field(parsed):
    # Schema field is premium_text; display column is premium_description.
    contract_sources = parsed["field_sources"]["contract"]
    assert "premium_description" in contract_sources
    assert contract_sources["premium_description"]["page_number"] == 2


def test_unresolved_reference_salvages_page_only(parsed):
    # contract_type references "2-u" — a table-cell id, not a chunk.
    src = parsed["field_sources"]["contract"]["contract_type"]
    assert src["source_text"] is None
    assert src["page_number"] == 3  # "2-u" -> 0-indexed 2 -> 1-indexed 3


def test_field_without_references_has_no_source(parsed):
    # currency had an empty references list — should not appear at all.
    assert "currency" not in parsed["field_sources"]["contract"]


def test_party_sources_align_by_index(parsed):
    parties = parsed["parties_data"]
    party_sources = parsed["field_sources"]["parties"]
    assert len(party_sources) == len(parties)
    # cedant is first, reinsurer second
    assert parsed["parties_data"][0]["role"] == "cedant"
    assert party_sources[0]["name"]["chunk_id"] == "uuid-cedant"
    assert party_sources[1]["name"]["chunk_id"] == "uuid-reinsurer"


def test_source_text_strips_html_artifacts():
    # DPT chunk markdown carries anchor tags / comments that reviewers must
    # never see in the evidence panel.
    raw = _raw_results()
    raw["parse_result"]["chunks"][0]["markdown"] = (
        "<a id='f2767fd2-e8f4-42c2-a613-0a7f2ea59d6f'></a>\n\n"
        "<!-- page header -->\n\n"
        "REINSURANCE COVER NOTE\n\n\n\nAgreement No: 970038/39/40 &amp; Co"
    )
    parsed = landingai_service.parse_extraction_results(raw)
    text = parsed["field_sources"]["contract"]["contract_name"]["source_text"]
    assert text == "REINSURANCE COVER NOTE\n\nAgreement No: 970038/39/40 & Co"


def test_missing_grounding_does_not_break_parsing():
    # No chunks, no extraction_metadata at all — must still parse cleanly.
    raw = {
        "parse_result": {"markdown": "x"},
        "extract_result": {
            "extraction": {
                "contract_name": "Bare Treaty",
                "contract_type": "Treaty",
                "cedant_name": "A Co",
                "reinsurer_name": "B Re",
            }
        },
        "metadata": {},
    }
    parsed = landingai_service.parse_extraction_results(raw)
    assert parsed["contract_data"]["contract_name"] == "Bare Treaty"
    assert parsed["field_sources"]["contract"] == {}
    assert parsed["field_sources"]["parties"] == [{}, {}]
