"""
Pydantic schemas for document upload and extraction.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from .contract import ContractCreate
from .party import PartyCreate


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document."""
    job_id: str
    filename: str
    file_path: str
    message: str
    status: str


class ExtractionResult(BaseModel):
    """Schema for extracted contract and party data from LandingAI."""
    contract_data: Dict[str, Any]
    parties_data: List[Dict[str, Any]]
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
    parties: List[PartyCreate]
    create_new_parties: bool = True  # Whether to create parties that don't exist


class ReviewApprovalResponse(BaseModel):
    """Response after approving extracted data."""
    contract_id: int
    party_ids: List[int]
    message: str
