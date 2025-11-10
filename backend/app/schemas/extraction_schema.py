"""
Extraction schemas for LandingAI ADE Extract API.
These schemas define what fields to extract from reinsurance contract documents.
"""
from typing import Optional
from pydantic import BaseModel, Field


class ReinsuranceContractFieldExtractionSchema(BaseModel):
    """
    Schema for extracting reinsurance contract fields from documents.
    This schema is optimized for typical reinsurance contract documents.
    """

    # Party Information
    cedant_name: str = Field(
        ...,
        description='The full legal name of the insurance company ceding risk under the contract.',
        title='Cedant Name',
    )
    reinsurer_name: str = Field(
        ...,
        description='The full legal name of the insurance company accepting risk under the contract.',
        title='Reinsurer Name',
    )

    # Contract Identification
    contract_name: str = Field(
        ...,
        description='The formal name or title of the reinsurance agreement.',
        title='Contract Name',
    )
    contract_type: str = Field(
        ...,
        description="The type of reinsurance contract, such as 'Treaty' or 'Facultative'.",
        title='Type of Contract',
    )
    contract_sub_type: str = Field(
        ...,
        description="The sub-type of reinsurance contract, such as 'Quota Share', 'Surplus', 'XOL' (Excess of Loss), 'Facultative Obligatory', or 'Facultative Optional'.",
        title='Contract Sub-Type',
    )
    contract_nature: str = Field(
        ...,
        description="The nature of the reinsurance contract, such as 'Proportional' or 'Non-Proportional'.",
        title='Nature of Contract',
    )

    # Financial Terms
    premium_amount: str = Field(
        ...,
        description='The premium amount or share to be paid by the cedant to the reinsurer for the coverage under this contract.',
        title='Premium Amount',
    )
    commission_rate: str = Field(
        ...,
        description='The commission rate or percentage paid by the reinsurer to the cedant or broker, typically expressed as a percentage.',
        title='Commission Rate',
    )
    deductible_amount: str = Field(
        ...,
        description='The amount or percentage of risk retained by the cedant before reinsurance coverage applies (also known as retention).',
        title='Deductible/Retention Amount',
    )
    limit_covered: str = Field(
        ...,
        description='The amount or percentage of coverage provided by the reinsurer under the contract.',
        title='Limit Covered',
    )
    upper_limit: str = Field(
        ...,
        description='The highest monetary or percentage limit up to which the reinsurer is liable under the contract.',
        title='Upper Limit',
    )

    # Coverage Details
    attachment_criteria: str = Field(
        ...,
        description='The criteria or conditions under which policies and claims attach to this reinsurance contract.',
        title='Attachment Criteria',
    )

    # Optional fields for additional contract details
    effective_date: Optional[str] = Field(
        None,
        description='The date when the contract becomes effective (format: YYYY-MM-DD or MM/DD/YYYY)',
        title='Effective Date',
    )
    expiration_date: Optional[str] = Field(
        None,
        description='The date when the contract expires (format: YYYY-MM-DD or MM/DD/YYYY)',
        title='Expiration Date',
    )
    contract_number: Optional[str] = Field(
        None,
        description='Unique contract or agreement number',
        title='Contract Number',
    )
    currency: Optional[str] = Field(
        None,
        description='Currency code (e.g., USD, EUR, GBP)',
        title='Currency',
    )
    line_of_business: Optional[str] = Field(
        None,
        description='Line of business: property, casualty, health, marine, aviation, etc.',
        title='Line of Business',
    )
    coverage_territory: Optional[str] = Field(
        None,
        description='Geographic coverage area or territory',
        title='Coverage Territory',
    )
    coverage_description: Optional[str] = Field(
        None,
        description='Description of coverage provided',
        title='Coverage Description',
    )
    terms_and_conditions: Optional[str] = Field(
        None,
        description='Summary of key terms and conditions',
        title='Terms and Conditions',
    )
    special_provisions: Optional[str] = Field(
        None,
        description='Any special provisions or clauses',
        title='Special Provisions',
    )

def get_extraction_schema() -> dict:
    """
    Get the JSON schema for extraction in the format required by LandingAI Extract API.
    Uses pydantic_to_json_schema from landingai_ade.lib for proper conversion.

    Returns:
        Dictionary containing the schema definition
    """
    from landingai_ade.lib import pydantic_to_json_schema
    return pydantic_to_json_schema(ReinsuranceContractFieldExtractionSchema)
