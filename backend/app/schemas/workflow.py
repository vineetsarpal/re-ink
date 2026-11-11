"""Version 1 machine boundary. Keep the public review ExtractionResult unchanged.

Providers normalize before crossing this boundary. Validation never invents defaults,
repairs citations, reorders parties, or silently truncates provider output.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, StrictStr, TypeAdapter,
    ValidationError, field_validator, model_validator,
)

from .document import ExtractionResult

MAX_CALLBACK_BYTES = 5 * 1024 * 1024
MAX_JSON_DEPTH = 20
MAX_PARTIES = 100
MAX_SOURCE_QUOTE_CHARS = 8000
MAX_METADATA_BYTES = 16 * 1024


class WorkflowPayloadError(ValueError):
    """Safe machine-request rejection usable by routes before any mutation."""
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _nonblank(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a nonblank string")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("control characters are not permitted")
    return value


Identifier = Annotated[StrictStr, BeforeValidator(_nonblank), Field(max_length=128)]
Text = Annotated[StrictStr, Field(max_length=100_000)]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Confidence = Annotated[FiniteNumber, Field(ge=0, le=1)]


def _calendar_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be a YYYY-MM-DD string")
    date.fromisoformat(value)
    return value


CalendarDate = Annotated[StrictStr, BeforeValidator(_calendar_date)]
# ISO 4217 alpha codes, including fund/precious-metal and no-currency codes.
# Deliberately a release-owned set: provider aliases and made-up codes are rejected.
CURRENCY_CODES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC
CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF
GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF
KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP
MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK
PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS
SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN
UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG
XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG ZWL
""".split())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ContractFacts(StrictModel):
    contract_number: Text | None = None
    contract_name: Text | None = None
    contract_type: Literal["treaty", "facultative", "proportional", "non-proportional"] | None = None
    contract_sub_type: Literal["quota_share", "surplus", "xol", "stop_loss", "facultative_obligatory", "facultative_optional"] | None = None
    contract_nature: Literal["proportional", "non-proportional"] | None = None
    effective_date: CalendarDate | None = None
    expiration_date: CalendarDate | None = None
    inception_date: CalendarDate | None = None
    premium_description: Text | None = None
    premium_amount: FiniteNumber | None = None
    currency: StrictStr | None = None
    limit_description: Text | None = None
    limit_amount: FiniteNumber | None = None
    retention_description: Text | None = None
    retention_amount: FiniteNumber | None = None
    commission_description: Text | None = None
    commission_rate: FiniteNumber | None = None
    line_of_business: Text | None = None
    coverage_territory: Text | None = None
    coverage_description: Text | None = None
    terms_and_conditions: Text | None = None
    special_provisions: Text | None = None

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value: str | None) -> str | None:
        if value is not None and value not in CURRENCY_CODES:
            raise ValueError("currency must be an uppercase ISO 4217 code")
        return value


class PartyFacts(StrictModel):
    name: Annotated[Text, BeforeValidator(_nonblank)]
    role: Literal["cedant", "reinsurer", "broker"] | None = None
    email: Text | None = None
    phone: Text | None = None
    address_line1: Text | None = None
    address_line2: Text | None = None
    city: Text | None = None
    state: Text | None = None
    postal_code: Text | None = None
    country: Text | None = None
    registration_number: Text | None = None
    license_number: Text | None = None
    notes: Text | None = None


class SourceBox(StrictModel):
    left: Annotated[FiniteNumber, Field(ge=0, le=1)]
    top: Annotated[FiniteNumber, Field(ge=0, le=1)]
    right: Annotated[FiniteNumber, Field(ge=0, le=1)]
    bottom: Annotated[FiniteNumber, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def positive_area(self) -> SourceBox:
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("bbox must have positive area")
        return self


class WorkflowFieldSource(StrictModel):
    value: StrictStr | FiniteNumber | bool | None = None
    source_text: Annotated[StrictStr, Field(max_length=MAX_SOURCE_QUOTE_CHARS)] | None = None
    page_number: Annotated[int, Field(strict=True, ge=1)] | None = None
    chunk_id: Identifier | None = None
    bbox: SourceBox | None = None
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def real_citation(self) -> WorkflowFieldSource:
        if self.source_text is None or not self.source_text.strip():
            raise ValueError("source requires a nonblank source quotation; omit absent evidence")
        if self.bbox is not None and self.page_number is None:
            raise ValueError("bbox requires a one-based page_number")
        return self


class WorkflowFieldSources(StrictModel):
    contract: dict[str, WorkflowFieldSource] = Field(default_factory=dict)
    parties: list[dict[str, WorkflowFieldSource]]


# Metadata carries bounded provenance/scale semantics, never raw provider responses.
class WorkflowMetadata(StrictModel):
    model_config = ConfigDict(protected_namespaces=())
    workflow_version: Annotated[StrictStr, Field(max_length=256)] | None = None
    provider: Annotated[StrictStr, Field(max_length=256)] | None = None
    provider_version: Annotated[StrictStr, Field(max_length=256)] | None = None
    model: Annotated[StrictStr, Field(max_length=256)] | None = None
    model_version: Annotated[StrictStr, Field(max_length=256)] | None = None
    api_version: Annotated[StrictStr, Field(max_length=256)] | None = None
    confidence_semantics: Annotated[StrictStr, Field(max_length=1000)] | None = None
    warnings: Annotated[list[Annotated[StrictStr, Field(max_length=1000)]], Field(max_length=100)] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded_metadata(self) -> WorkflowMetadata:
        if len(json.dumps(self.model_dump(exclude_unset=True), ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError("metadata exceeds 16 KiB")
        return self


class NormalizedExtractionResult(StrictModel):
    contract_data: ContractFacts
    parties_data: Annotated[list[PartyFacts], Field(max_length=MAX_PARTIES)]
    field_sources: WorkflowFieldSources | None = None
    confidence_score: Confidence | None = None
    extraction_metadata: WorkflowMetadata | None = None

    @model_validator(mode="after")
    def useful_aligned_facts(self) -> NormalizedExtractionResult:
        contract = self.contract_data.model_dump(exclude_unset=True)
        if not self.parties_data and not any(
            value is not None and (not isinstance(value, str) or value.strip())
            for value in contract.values()
        ):
            raise ValueError("completed result requires useful contract or party facts")
        if self.field_sources is not None:
            if len(self.field_sources.parties) != len(self.parties_data):
                raise ValueError("party evidence must align exactly with parties_data")
            self._check_sources(self.field_sources.contract, contract, ContractFacts.model_fields)
            for party, sources in zip(self.parties_data, self.field_sources.parties):
                self._check_sources(sources, party.model_dump(exclude_unset=True), PartyFacts.model_fields)
        return self

    @staticmethod
    def _check_sources(sources: dict, facts: dict, supported: dict) -> None:
        for name in sources:
            if name not in supported or name not in facts or facts[name] is None:
                raise ValueError("source references an unsupported, missing, or null fact")

    def to_extraction_result(self) -> ExtractionResult:
        """Project the strict boundary back into the unchanged application shape."""
        return ExtractionResult.model_validate(self.model_dump(exclude_unset=True))


class WorkflowDispatch(StrictModel):
    schema_version: Literal["1"]
    operation: Literal["extract_reinsurance_contract"]
    job_id: Identifier
    attempt_id: Identifier


class WorkflowAcceptance(StrictModel):
    schema_version: Literal["1"]
    job_id: Identifier
    attempt_id: Identifier
    status: Literal["accepted"]
    workflow_execution_id: Identifier | None = None


def validate_acceptance(payload: Any, job_id: str, attempt_id: str) -> WorkflowAcceptance:
    acceptance = WorkflowAcceptance.model_validate(payload)
    if acceptance.job_id != job_id or acceptance.attempt_id != attempt_id:
        raise WorkflowPayloadError("acceptance identity does not match dispatch")
    return acceptance


class WorkflowClaimRequest(StrictModel):
    schema_version: Literal["1"]
    execution_key: Identifier


class WorkflowClaimResponse(StrictModel):
    schema_version: Literal["1"]
    job_id: Identifier
    attempt_id: Identifier
    decision: Literal["run", "already_claimed"]
    deadline_at: datetime


class EventEnvelope(StrictModel):
    schema_version: Literal["1"]
    job_id: Identifier
    attempt_id: Identifier
    event_id: Identifier
    workflow_execution_id: Identifier | None = None


class ProcessingEvent(EventEnvelope):
    status: Literal["processing"]


class CompletedEvent(EventEnvelope):
    status: Literal["completed"]
    result: NormalizedExtractionResult


class WorkflowError(StrictModel):
    code: Annotated[StrictStr, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
    message: Annotated[StrictStr, BeforeValidator(_nonblank), Field(max_length=1000)]
    retryable: bool


class FailedEvent(EventEnvelope):
    status: Literal["failed"]
    error: WorkflowError


WorkflowEvent = Annotated[ProcessingEvent | CompletedEvent | FailedEvent, Field(discriminator="status")]
EVENT_ADAPTER = TypeAdapter(WorkflowEvent)


class WorkflowEventAck(StrictModel):
    schema_version: Literal["1"]
    event_id: Identifier
    status: Literal["acknowledged"]


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON numbers are forbidden")


def parse_workflow_json(body: bytes, content_encoding: str | None = None) -> Any:
    """Reject request limits/JSON ambiguity before schema validation or DB work.

    Routes must also bound streaming reads at MAX_CALLBACK_BYTES + 1 rather than
    trusting Content-Length or buffering an unbounded request before this helper.
    """
    if content_encoding and content_encoding.lower().strip() != "identity":
        raise WorkflowPayloadError("compressed request bodies are unsupported", 413)
    if len(body) > MAX_CALLBACK_BYTES:
        raise WorkflowPayloadError("request exceeds 5 MiB", 413)
    # Scan container depth before json.loads, avoiding parser recursion exhaustion.
    depth, quoted, escaped = 0, False, False
    try:
        decoded = body.decode("utf-8")
        for char in decoded:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > MAX_JSON_DEPTH:
                    raise WorkflowPayloadError("JSON nesting exceeds 20", 413)
            elif char in "}]":
                depth -= 1
        payload = json.loads(decoded, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
        # JSON exponent overflow can become inf without invoking parse_constant.
        pending = [payload]
        while pending:
            value = pending.pop()
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("non-finite JSON numbers are forbidden")
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return payload
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, WorkflowPayloadError):
            raise
        raise WorkflowPayloadError("malformed UTF-8 JSON") from exc


def parse_workflow_event(body: bytes, content_encoding: str | None = None) -> WorkflowEvent:
    payload = parse_workflow_json(body, content_encoding)
    try:
        return EVENT_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        # Do not echo input values/provider text into HTTP errors or logs.
        raise WorkflowPayloadError("invalid workflow event") from exc
