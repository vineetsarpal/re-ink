"""
Pydantic schemas for document upload and extraction.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from .contract import ContractCreate
from .party import PartyCreate, PartyAction


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
    value: Optional[Any] = None          # The value LandingAI extracted
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
    """Schema for extracted contract and party data from LandingAI."""
    contract_data: Dict[str, Any]
    parties_data: List[Dict[str, Any]]
    field_sources: Optional[FieldSources] = None
    confidence_score: Optional[float] = None
    extraction_metadata: Optional[Dict[str, Any]] = None


class DocumentExtractionStatus(BaseModel):
    """Status of a document extraction job."""
    job_id: str
    status: str  # processing, completed, failed
    message: Optional[str] = None
    result: Optional[ExtractionResult] = None
    created_at: datetime


class ReviewData(BaseModel):
    """Schema for reviewing and confirming extracted data."""
    contract: ContractCreate
    parties: List[PartyAction]  # Per-party: link to existing or create new


class ReviewApprovalResponse(BaseModel):
    """Response after approving extracted data."""
    contract_id: int
    party_ids: List[int]
    message: str
