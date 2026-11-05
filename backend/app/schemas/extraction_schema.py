"""
Extraction schemas for LandingAI ADE Extract API.
"""
from typing import Optional, Literal
from datetime import date
from pydantic import BaseModel, Field


class ReinsuranceContractFieldExtractionSchema(BaseModel):
    """Schema for extracting reinsurance contract fields from parsed markdown."""

    # ---------------------------------------------------------------------
    # Contract Identification
    # ---------------------------------------------------------------------
    contract_name: str = Field(
        ...,
        description=(
            "The formal title of the reinsurance agreement as it appears in the "
            "document header or cover page. Example: 'Property Quota Share "
            "Reinsurance Treaty 2024' or 'Facultative Certificate of Reinsurance'."
        ),
        title="Contract Name",
        json_schema_extra={
            "x-alternativeNames": [
                "Agreement Title", "Treaty Name", "Slip Title",
                "Reinsurance Agreement", "Wording Title",
            ]
        },
    )
    contract_number: Optional[str] = Field(
        None,
        description=(
            "Unique contract, treaty, or certificate number as printed in the "
            "document. Examples: 'RT-2024-0012', 'FAC/2024/0091'. Return null "
            "if no explicit identifier is stated."
        ),
        title="Contract Number",
        json_schema_extra={
            "x-alternativeNames": [
                "Treaty Number", "Certificate Number", "Reference Number",
                "UMR", "Unique Market Reference", "Slip Reference",
            ]
        },
    )
    contract_type: Literal["Treaty", "Facultative"] = Field(
        ...,
        description=(
            "Top-level reinsurance form. 'Treaty' covers a portfolio of risks "
            "under a single agreement; 'Facultative' covers a single risk. "
            "Infer from document type if not stated explicitly."
        ),
        title="Contract Type",
        json_schema_extra={"x-alternativeNames": ["Form of Reinsurance", "Reinsurance Form"]},
    )
    contract_sub_type: Optional[
        Literal[
            "Quota Share",
            "Surplus",
            "Excess of Loss",
            "Stop Loss",
            "Facultative Obligatory",
            "Facultative Optional",
        ]
    ] = Field(
        None,
        description=(
            "Specific reinsurance structure. 'Quota Share' and 'Surplus' are "
            "proportional; 'Excess of Loss' (XOL) and 'Stop Loss' are non-"
            "proportional. Return null if not clearly identifiable."
        ),
        title="Contract Sub-Type",
        json_schema_extra={
            "x-alternativeNames": [
                "Reinsurance Structure", "Cover Type", "XOL", "Excess-of-Loss",
            ]
        },
    )
    contract_nature: Optional[Literal["Proportional", "Non-Proportional"]] = Field(
        None,
        description=(
            "Whether premiums and losses are shared proportionally (Quota Share, "
            "Surplus) or non-proportionally (XOL, Stop Loss). Derive from "
            "contract_sub_type if not explicitly stated."
        ),
        title="Nature of Contract",
    )

    # ---------------------------------------------------------------------
    # Parties
    # ---------------------------------------------------------------------
    cedant_name: str = Field(
        ...,
        description=(
            "Full legal name of the insurer ceding risk to the reinsurer. "
            "Usually introduced as 'between [CEDANT], hereinafter referred to "
            "as the Reinsured/Company' at the start of the wording."
        ),
        title="Cedant Name",
        json_schema_extra={
            "x-alternativeNames": [
                "Ceding Company", "Reinsured", "Insurer", "Original Insurer",
                "Company", "The Reinsured", "Cedent",
            ]
        },
    )
    reinsurer_name: str = Field(
        ...,
        description=(
            "Full legal name of the company assuming risk from the cedant. "
            "Often introduced as 'and [REINSURER], hereinafter the Reinsurer'."
        ),
        title="Reinsurer Name",
        json_schema_extra={
            "x-alternativeNames": [
                "Assuming Company", "Assuming Reinsurer", "The Reinsurer",
                "Reinsurance Company",
            ]
        },
    )

    # ---------------------------------------------------------------------
    # Contract Period
    # ---------------------------------------------------------------------
    effective_date: Optional[date] = Field(
        None,
        description=(
            "Date coverage under this contract begins. Normalize to ISO-8601 "
            "(YYYY-MM-DD). Return null if only a period ('12 months') is given "
            "without an anchor date."
        ),
        title="Effective Date",
        json_schema_extra={
            "x-alternativeNames": [
                "Inception Date", "Attachment Date", "Start Date",
                "Period From", "Commencement Date",
            ]
        },
    )
    expiration_date: Optional[date] = Field(
        None,
        description=(
            "Date coverage under this contract ends. Normalize to ISO-8601 "
            "(YYYY-MM-DD)."
        ),
        title="Expiration Date",
        json_schema_extra={
            "x-alternativeNames": [
                "Expiry Date", "Termination Date", "End Date",
                "Period To", "Anniversary Date",
            ]
        },
    )

    # ---------------------------------------------------------------------
    # Financial Terms — each term has an as-written `_text` and a
    # normalized numeric variant. The model should fill both when possible.
    # ---------------------------------------------------------------------
    currency: Optional[str] = Field(
        None,
        description=(
            "Three-letter ISO 4217 currency code for all financial amounts in "
            "this contract, e.g. 'USD', 'EUR', 'GBP'. Infer from currency "
            "symbols ($, €, £) or context if not stated explicitly."
        ),
        title="Currency",
        json_schema_extra={"x-alternativeNames": ["Currency Code", "Settlement Currency"]},
    )

    premium_text: Optional[str] = Field(
        None,
        description=(
            "Premium as written in the document, preserving phrasing. Examples: "
            "'100% of gross net written premium income', '$10,000,000 flat', "
            "'25% of GNWPI'. Use this field for descriptive or formulaic "
            "premiums that cannot be reduced to a single number."
        ),
        title="Premium (As Written)",
        json_schema_extra={
            "x-alternativeNames": [
                "Reinsurance Premium", "Deposit Premium", "Minimum Premium",
                "GNWPI", "Gross Net Written Premium Income",
            ]
        },
    )
    premium_amount: Optional[float] = Field(
        None,
        description=(
            "Premium as a single numeric value in the contract currency, when "
            "the document states a flat monetary sum. Example: for '$10,000,000 "
            "flat premium' return 10000000. Return null for percentage-based or "
            "formulaic premiums."
        ),
        title="Premium Amount (Numeric)",
    )

    commission_text: Optional[str] = Field(
        None,
        description=(
            "Ceding commission as written. Examples: '27.5% ceding commission', "
            "'sliding scale 20%/30%/40%', 'profit commission of 20% after 5% "
            "management expense'."
        ),
        title="Ceding Commission (As Written)",
        json_schema_extra={
            "x-alternativeNames": [
                "Ceding Commission", "Reinsurance Commission", "Override Commission",
                "Profit Commission", "Sliding Scale Commission",
            ]
        },
    )
    commission_rate: Optional[float] = Field(
        None,
        description=(
            "Ceding commission as a percentage number (not a decimal). Example: "
            "for '27.5% ceding commission' return 27.5. Return null for sliding-"
            "scale or profit commissions that cannot be reduced to one rate."
        ),
        title="Commission Rate (%)",
    )

    retention_text: Optional[str] = Field(
        None,
        description=(
            "Cedant retention / deductible as written. Examples: '$250,000 "
            "each and every loss', '$5M per occurrence', '10% of each risk'."
        ),
        title="Retention (As Written)",
        json_schema_extra={
            "x-alternativeNames": [
                "Deductible", "Net Retention", "Priority", "Attachment Point",
                "Cedant Retention", "Each and Every Loss Retention",
                "Self-Insured Retention",
            ]
        },
    )
    retention_amount: Optional[float] = Field(
        None,
        description=(
            "Retention as a single numeric value in the contract currency when "
            "stated as a flat sum. Example: for '$250,000 each and every loss' "
            "return 250000. Return null for percentage-based retentions."
        ),
        title="Retention Amount (Numeric)",
    )

    limit_text: Optional[str] = Field(
        None,
        description=(
            "Reinsurer's limit of liability as written. Examples: '$10,000,000 "
            "excess of $250,000 each and every loss', '100% quota share up to "
            "$5M per risk', 'Aggregate limit $50M'."
        ),
        title="Limit (As Written)",
        json_schema_extra={
            "x-alternativeNames": [
                "Limit of Liability", "Reinsurer's Liability", "Cover Limit",
                "Layer Limit", "Aggregate Limit", "Line", "Each and Every Loss Limit",
            ]
        },
    )
    limit_amount: Optional[float] = Field(
        None,
        description=(
            "Limit as a single numeric value in the contract currency when "
            "stated as a flat sum. For '$10,000,000 xs $250,000' return "
            "10000000 (the excess amount, not the sum). Return null for "
            "percentage-based limits."
        ),
        title="Limit Amount (Numeric)",
    )

    # ---------------------------------------------------------------------
    # Coverage
    # ---------------------------------------------------------------------
    line_of_business: Optional[str] = Field(
        None,
        description=(
            "Class of business covered. Examples: 'Property', 'Casualty', "
            "'Marine Hull', 'Aviation', 'Cyber', 'Health'. Return the most "
            "specific label the document uses."
        ),
        title="Line of Business",
        json_schema_extra={
            "x-alternativeNames": [
                "Class of Business", "Business Class", "Branch", "Risk Class",
            ]
        },
    )
    coverage_territory: Optional[str] = Field(
        None,
        description=(
            "Geographic scope of coverage. Examples: 'Worldwide', 'USA and "
            "Canada only', 'Europe excluding UK'."
        ),
        title="Coverage Territory",
        json_schema_extra={"x-alternativeNames": ["Territorial Scope", "Geographic Scope"]},
    )
    coverage_description: Optional[str] = Field(
        None,
        description=(
            "Brief prose description of what is covered, including attachment "
            "criteria and any notable inclusions. Keep under 500 characters; "
            "put detailed legal language in terms_and_conditions."
        ),
        title="Coverage Description",
        json_schema_extra={
            "x-alternativeNames": [
                "Scope of Cover", "Attachment Criteria", "Business Covered",
                "Subject Matter of Reinsurance",
            ]
        },
    )
    terms_and_conditions: Optional[str] = Field(
        None,
        description=(
            "Verbatim or near-verbatim key terms and conditions clauses. "
            "Preserve numbering and structure from the source."
        ),
        title="Terms and Conditions",
    )
    special_provisions: Optional[str] = Field(
        None,
        description=(
            "Non-standard clauses, endorsements, exclusions, or special "
            "warranties. Examples: 'NMA 2918 Nuclear Exclusion', 'Cyber "
            "Exclusion Clause', 'Sunset Clause 36 months'."
        ),
        title="Special Provisions",
        json_schema_extra={
            "x-alternativeNames": [
                "Endorsements", "Exclusions", "Warranties",
                "Special Conditions", "Additional Clauses",
            ]
        },
    )


def get_extraction_schema() -> dict:
    """Return the JSON schema in the format expected by LandingAI Extract."""
    from landingai_ade.lib import pydantic_to_json_schema
    return pydantic_to_json_schema(ReinsuranceContractFieldExtractionSchema)
