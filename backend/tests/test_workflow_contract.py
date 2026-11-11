"""Deterministic boundary checks, without provider calls or accuracy claims."""
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.workflow import (
    MAX_CALLBACK_BYTES, NormalizedExtractionResult, WorkflowClaimRequest,
    WorkflowClaimResponse, WorkflowDispatch, WorkflowPayloadError,
    parse_workflow_event, parse_workflow_json, validate_acceptance,
)


@pytest.fixture
def completed():
    return {"schema_version": "1", "job_id": "job-1", "attempt_id": "attempt-1",
        "event_id": "event-1", "status": "completed", "result": {
            "contract_data": {"contract_name": "Synthetic Treaty", "currency": "CAD",
                "effective_date": "2024-02-29", "commission_rate": 12.5},
            "parties_data": [{"name": "Synthetic Insurer"}],
            "field_sources": {"contract": {"contract_name": {"source_text": "Synthetic Treaty",
                "page_number": 1, "bbox": {"left": 0, "top": 0, "right": 1, "bottom": 1}}},
                "parties": [{}]}, "extraction_metadata": {"workflow_version": "demo-v1"}}}


def parse(value):
    return parse_workflow_event(json.dumps(value).encode())


def test_roundtrip_preserves_review_shape_and_unknown_role(completed):
    result = parse(completed).result.to_extraction_result()
    assert result.contract_data == completed["result"]["contract_data"]
    assert result.parties_data == [{"name": "Synthetic Insurer"}]
    assert result.field_sources.parties == [{}]
    assert result.confidence_score is None


def test_stop_loss_subtype_from_production_provider_schema(completed):
    completed["result"]["contract_data"]["contract_sub_type"] = "stop_loss"
    assert parse(completed).result.to_extraction_result().contract_data["contract_sub_type"] == "stop_loss"


@pytest.mark.parametrize("data", [{"contract_name": "partial"}, {"premium_amount": 0}])
def test_partial_facts_without_evidence(data):
    assert NormalizedExtractionResult(contract_data=data, parties_data=[]).to_extraction_result().field_sources is None


@pytest.mark.parametrize("data", [{}, {"contract_name": None}, {"contract_name": "  "}])
def test_empty_success_rejected(data):
    with pytest.raises(ValidationError):
        NormalizedExtractionResult(contract_data=data, parties_data=[])


@pytest.mark.parametrize("key,value", [
    ("status", "approved"), ("is_active", True), ("id", 12), ("premium_text", "million"),
    ("currency", "usd"), ("currency", "ZZZ"), ("effective_date", "2025-02-29"),
    ("expiration_date", "2026-1-01"), ("inception_date", "2026-01-01T00:00:00Z"),
    ("premium_amount", "100"), ("limit_amount", True), ("retention_amount", float("inf")),
    ("commission_rate", float("nan")), ("contract_name", {"value": "bad"}),
    ("contract_type", "Treaty"), ("contract_nature", "invented"),
])
def test_business_field_types(completed, key, value):
    completed["result"]["contract_data"][key] = value
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


@pytest.mark.parametrize("party", [
    {"name": ""}, {"name": " "}, {"name": 12}, {"name": "A", "role": "unknown"},
    {"name": "A", "is_active": True}, {"name": "A", "id": 1}, {"name": "A", "email": []},
])
def test_party_boundary(completed, party):
    completed["result"]["parties_data"] = [party]
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


@pytest.mark.parametrize("change", [
    {"source_text": ""}, {"source_text": None}, {"source_text": "x" * 8001},
    {"page_number": 0}, {"page_number": True}, {"page_number": 1.5}, {"page_number": None},
    {"confidence": -0.01}, {"confidence": 1.01}, {"value": {"nested": "bad"}}, {"unknown": True},
])
def test_source_integrity(completed, change):
    completed["result"]["field_sources"]["contract"]["contract_name"].update(change)
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


@pytest.mark.parametrize("box", [
    {"left": -1, "top": 0, "right": 1, "bottom": 1},
    {"left": 0, "top": 0, "right": 0, "bottom": 1},
    {"left": 0, "top": 1, "right": 1, "bottom": 0},
    {"left": 0, "top": 0, "right": 2, "bottom": 1},
    {"left": False, "top": 0, "right": 1, "bottom": 1},
    {"left": 0, "top": 0, "right": float("nan"), "bottom": 1},
])
def test_invalid_boxes(completed, box):
    completed["result"]["field_sources"]["contract"]["contract_name"]["bbox"] = box
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


@pytest.mark.parametrize("sources", [[], [{}, {}], [{"role": {"source_text": "cedant"}}]])
def test_party_evidence_alignment_and_dangling_fields(completed, sources):
    completed["result"]["field_sources"]["parties"] = sources
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


def test_limits_and_unknown_metadata(completed):
    original = deepcopy(completed)
    completed["result"]["parties_data"] *= 101
    completed["result"].pop("field_sources")
    with pytest.raises(WorkflowPayloadError):
        parse(completed)
    for metadata in ({"warnings": ["x" * 1000] * 17}, {"raw_response": "forbidden"}):
        original["result"]["extraction_metadata"] = metadata
        with pytest.raises(WorkflowPayloadError):
            parse(original)


@pytest.mark.parametrize("body,encoding,status", [
    (b"x" * (MAX_CALLBACK_BYTES + 1), None, 413), (b"{}", "gzip", 413),
    (b"\xff", None, 422), (b'{"x":1,"x":2}', None, 422), (b'{"x":NaN}', None, 422),
    (b'{"x":1e9999}', None, 422), (b'[] trailing', None, 422),
    (b"[" * 21 + b"0" + b"]" * 21, None, 413),
])
def test_raw_limits(body, encoding, status):
    with pytest.raises(WorkflowPayloadError) as err:
        parse_workflow_json(body, encoding)
    assert err.value.status_code == status


def test_depth_limit_and_brackets_in_strings():
    assert parse_workflow_json(b"[" * 20 + b"0" + b"]" * 20)
    assert parse_workflow_json(json.dumps({"quoted": '[[["[[['}).encode()) == {"quoted": '[[["[[['}


@pytest.mark.parametrize("key,value", [
    ("schema_version", "2"), ("schema_version", 1), ("event_id", "x" * 129),
    ("attempt_id", " "), ("workflow_execution_id", "bad\nkey"),
    ("status", "timed_out"), ("extra", "secret"),
])
def test_envelope(completed, key, value):
    completed[key] = value
    with pytest.raises(WorkflowPayloadError):
        parse(completed)


def test_event_variants_and_safe_error(completed):
    event = {key: value for key, value in completed.items() if key != "result"}
    event["status"] = "processing"
    assert parse(event).status == "processing"
    event["status"] = "failed"
    event["error"] = {"code": "NO_CONTRACT_DATA", "message": "No useful data.", "retryable": False}
    assert parse(event).error.retryable is False
    event["error"]["message"] = "x" * 1001
    with pytest.raises(WorkflowPayloadError):
        parse(event)
    completed["result"]["contract_data"]["forbidden"] = "sensitive input value"
    with pytest.raises(WorkflowPayloadError) as err:
        parse(completed)
    assert str(err.value) == "invalid workflow event"


def test_dispatch_acceptance_and_claim():
    dispatch = WorkflowDispatch(schema_version="1", operation="extract_reinsurance_contract", job_id="job-1", attempt_id="attempt-1")
    accepted = {"schema_version": "1", "job_id": dispatch.job_id, "attempt_id": dispatch.attempt_id, "status": "accepted"}
    assert validate_acceptance(accepted, "job-1", "attempt-1").status == "accepted"
    with pytest.raises(WorkflowPayloadError):
        validate_acceptance(accepted, "different", "attempt-1")
    with pytest.raises(ValidationError):
        validate_acceptance({"status": "ok"}, "job-1", "attempt-1")
    assert WorkflowClaimRequest(schema_version="1", execution_key="n8n:123").execution_key == "n8n:123"
    response = WorkflowClaimResponse(schema_version="1", job_id="job-1", attempt_id="attempt-1", decision="run", deadline_at=datetime.now(timezone.utc))
    assert response.model_dump(mode="json")["deadline_at"].endswith("Z")
