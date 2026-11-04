"""
Pydantic schemas for document upload and extraction.
"""
from pydantic import BaseModel, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from .contract import ContractCreate
from .party import PartyAction


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document."""
    job_id: str
    filename: str
    file_path: str
    message: str
    status: str


class FieldSource(BaseModel):
    """
    Source evidence for a single extracted field, grounding it back to the
    uploaded document so reviewers can verify AI output quickly.
    """
    value: Optional[Any] = None          # The extracted value
    source_text: Optional[str] = None    # Verbatim chunk text from the document
    page_number: Optional[int] = None    # 1-indexed page the evidence sits on
    chunk_id: Optional[str] = None        # Parse chunk / element identifier
    bbox: Optional[Dict[str, float]] = None  # {left, top, right, bottom} (0..1)
    confidence: Optional[float] = None    # Per-field confidence, when available


class FieldSources(BaseModel):
    """
    Source evidence keyed for review:
    - ``contract``: display-column name -> FieldSource
    - ``parties``:  aligned by index with ``parties_data``; each maps a party
      field (currently just ``name``) -> FieldSource
    """
    contract: Dict[str, FieldSource] = {}
    parties: List[Dict[str, FieldSource]] = []


class ExtractionResult(BaseModel):
    """Schema for extracted contract and party data from the workflow."""
    contract_data: Dict[str, Any]
    parties_data: List[Dict[str, Any]]
    field_sources: Optional[FieldSources] = None
    confidence_score: Optional[float] = None
    extraction_metadata: Optional[Dict[str, Any]] = None


class DocumentExtractionStatus(BaseModel):
    """Status of a document extraction job."""
    job_id: str
    status: str  # queued, processing, completed, failed, timed_out
    message: Optional[str] = None
    result: Optional[ExtractionResult] = None
    created_at: datetime


class ReviewData(BaseModel):
    """Schema for reviewing and confirming extracted data."""
    contract: ContractCreate
    parties: List[PartyAction]  # Per-party: link to existing or create new

    @model_validator(mode="before")
    @classmethod
    def require_explicit_review_values(cls, data):
        if not isinstance(data, dict):
            return data
        contract = data.get("contract", {})
        if isinstance(contract, dict):
            for field in ("contract_number", "contract_name", "currency", "effective_date", "expiration_date"):
                value = contract.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ValueError(f"Review requires an explicit {field}")
        parties = data.get("parties")
        if isinstance(parties, list):
            for party in parties:
                if isinstance(party, dict):
                    role = party.get("role")
                    if not isinstance(role, str) or role not in {"cedant", "reinsurer", "broker"}:
                        raise ValueError("Review requires an explicit canonical party role")
                    party_data = party.get("party_data")
                    if party.get("action") == "create_new" and isinstance(party_data, dict):
                        name = party_data.get("name")
                        if isinstance(name, str) and not name.strip():
                            raise ValueError("Review requires a nonblank party name")
        return data


class ReviewApprovalResponse(BaseModel):
    """Response after approving extracted data."""
    contract_id: int
    party_ids: List[int]
    message: str
