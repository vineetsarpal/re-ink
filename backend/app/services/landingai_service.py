"""
Service layer for integrating with LandingAI's ADE (Agentic Document Extraction) API.
Uses the official landingai-ade SDK for document parsing and field extraction.

"""
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from io import BytesIO

from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from app.core.config import settings
from app.schemas.extraction_schema import ReinsuranceContractFieldExtractionSchema

logger = logging.getLogger(__name__)


class LandingAIService:
    """
    Service for interacting with LandingAI ADE API using the official SDK.

    Uses a two-step process:
    1. Parse: Convert document to structured markdown
    2. Extract: Pull specific fields using schema definitions
    """

    def __init__(self):
        self.api_key = settings.LANDINGAI_API_KEY
        self.parse_model = settings.LANDINGAI_PARSE_MODEL
        self.extract_model = settings.LANDINGAI_EXTRACT_MODEL

        # Initialize the LandingAI ADE client
        self.client = LandingAIADE(apikey=self.api_key)

    async def submit_document_for_extraction(
        self,
        file_path: str,
        parse_model: Optional[str] = None,
        extract_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete document processing workflow using LandingAI ADE SDK.

        Steps:
        1. Parse document to markdown using SDK parse method
        2. Extract structured data using SDK extract method with schema

        Args:
            file_path: Path to the document file
            parse_model: Optional parse model version (defaults to dpt-2-latest)
            extract_model: Optional extract model version (defaults to extract-latest)

        Returns:
            Dictionary containing:
            - parse_result: Raw parse response
            - extract_result: Structured extracted data
            - metadata: Combined metadata from both steps

        Raises:
            Exception: If any API request fails
        """
        try:
            # Step 1: Parse document to markdown
            logger.info(f"Starting document parsing for: {file_path}")
            parse_result = await self._parse_document(
                file_path=file_path,
                model=parse_model or self.parse_model
            )

            markdown = parse_result.get("markdown", "")
            if not markdown:
                raise Exception("Parse API returned empty markdown content")

            logger.info(f"Document parsed successfully. Markdown length: {len(markdown)}")

            # Step 2: Extract structured data from markdown
            logger.info("Starting field extraction from parsed document")
            extract_result = await self._extract_fields(
                markdown=markdown,
                model=extract_model or self.extract_model
            )

            logger.info("Field extraction completed successfully")

            # Combine results
            return {
                "parse_result": parse_result,
                "extract_result": extract_result,
                "metadata": {
                    "filename": Path(file_path).name,
                    "markdown_length": len(markdown),
                    "parse_model": parse_model or self.parse_model,
                    "extract_model": extract_model or self.extract_model,
                }
            }

        except Exception as e:
            logger.error(f"Error in document extraction workflow: {str(e)}", exc_info=True)
            raise

    async def _parse_document(
        self,
        file_path: str,
        model: str,
    ) -> Dict[str, Any]:
        """
        Step 1: Parse document using LandingAI ADE SDK.
        Converts PDF/DOCX to structured markdown format.

        Args:
            file_path: Path to the document file
            model: Parse model version (e.g., "dpt-2-latest" or "dpt-2")

        Returns:
            Dictionary containing markdown and metadata

        Raises:
            Exception: If the parsing fails
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            logger.info(f"Parsing document with model: {model}")

            # Use the SDK's parse method
            # Note: The SDK's parse method is synchronous, but we're in an async context
            # We'll run it in a thread pool executor to avoid blocking
            import asyncio
            loop = asyncio.get_event_loop()
            parse_response = await loop.run_in_executor(
                None,
                lambda: self.client.parse(
                    document=file_path_obj,
                    model=model,
                )
            )

            # Extract markdown from the parse response
            # The SDK returns a response object with a markdown attribute
            markdown = parse_response.markdown

            logger.info(f"Parse completed. Markdown length: {len(markdown)}")

            return {
                "markdown": markdown,
                "metadata": {
                    "filename": file_path_obj.name,
                    "parse_model": model,
                }
            }

        except Exception as e:
            logger.error(f"Error parsing document: {str(e)}", exc_info=True)
            raise Exception(f"Document parsing failed: {str(e)}")

    async def _extract_fields(
        self,
        markdown: str,
        model: str
    ) -> Dict[str, Any]:
        """
        Step 2: Extract structured fields using LandingAI ADE SDK.
        Applies schema to markdown to extract specific fields.

        Args:
            markdown: Markdown content from parse step
            model: Extract model version (e.g., "extract-latest")

        Returns:
            Dictionary containing extracted contract data

        Raises:
            Exception: If the extraction fails
        """
        try:
            # Get the extraction schema using the SDK's conversion function
            schema = pydantic_to_json_schema(ReinsuranceContractFieldExtractionSchema)

            # logger.info(f"Extracting fields with model: {model}")
            # logger.debug(f"Schema keys: {list(schema.get('properties', {}).keys())}")

            # Use the SDK's extract method
            # Convert markdown string to BytesIO for the SDK
            markdown_bytes = BytesIO(markdown.encode('utf-8'))

            import asyncio
            loop = asyncio.get_event_loop()
            extract_response = await loop.run_in_executor(
                None,
                lambda: self.client.extract(
                    schema=schema,
                    markdown=markdown_bytes,
                    model=model,
                )
            )

            # The SDK returns a response object
            # We need to convert it to a dictionary for our processing
            if hasattr(extract_response, 'model_dump'):
                # Pydantic model with model_dump method
                result = extract_response.model_dump()
            elif hasattr(extract_response, 'dict'):
                # Pydantic v1 model with dict method
                result = extract_response.dict()
            elif isinstance(extract_response, str):
                # String response (likely JSON) - parse it
                import json
                try:
                    result = json.loads(extract_response)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse string response as JSON: {e}")
                    logger.error(f"Response content: {extract_response[:500]}")
                    raise Exception(f"Extract API returned unparseable string: {str(e)}")
            elif isinstance(extract_response, dict):
                # Already a dictionary
                result = extract_response
            else:
                # Unknown type - try to convert to dict or raise error
                logger.error(f"Unexpected extract_response type: {type(extract_response)}")
                logger.error(f"Response value: {extract_response}")
                raise Exception(f"Extract API returned unexpected type: {type(extract_response)}")

            # Validate that result is a dictionary
            if not isinstance(result, dict):
                logger.error(f"Result is not a dictionary after conversion! Type: {type(result)}")
                raise Exception(f"Failed to convert extract response to dictionary. Got type: {type(result)}")

            logger.info(f"Extraction completed. Result type: {type(result)}")
            logger.debug(f"Extraction result keys: {list(result.keys())}")

            return result

        except Exception as e:
            logger.error(f"Error extracting fields: {str(e)}", exc_info=True)
            # Don't wrap the exception if it's already our exception
            if "Field extraction failed" in str(e):
                raise
            raise Exception(f"Field extraction failed: {str(e)}")

    def parse_extraction_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and structure the extraction results from the complete workflow.

        Args:
            raw_results: Combined results from parse and extract steps

        Returns:
            Structured dictionary with contract_data, parties_data, and metadata
        """
        try:
            extract_result = raw_results.get("extract_result", {})
            metadata = raw_results.get("metadata", {})

            # Debug logging to see actual structure
            logger.info(f"Raw results structure: {list(raw_results.keys())}")
            logger.info(f"Extract result structure: {list(extract_result.keys()) if extract_result else 'Empty'}")

            # Process the extracted data
            contract_data = self._process_contract_data(extract_result)
            parties_data = self._process_parties_data(extract_result)

            logger.info(f"Processed contract_data keys: {list(contract_data.keys()) if contract_data else 'Empty'}")
            logger.info(f"Processed parties_data count: {len(parties_data)}")

            # Calculate confidence score if available
            confidence_score = extract_result.get("confidence", None)

            return {
                "contract_data": contract_data,
                "parties_data": parties_data,
                "confidence_score": confidence_score,
                "extraction_metadata": metadata
            }

        except Exception as e:
            logger.error(f"Error parsing extraction results: {str(e)}", exc_info=True)
            raise

    def _process_contract_data(self, extract_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process extracted contract data from the new schema format.

        Args:
            extract_result: Raw extraction result from Extract API

        Returns:
            Dictionary with processed contract fields mapped to our database schema
        """
        contract_data: Dict[str, Any] = {}

        logger.info(
            "Processing contract data. Available keys: %s",
            list(extract_result.keys()) if isinstance(extract_result, dict) else "None",
        )

        normalized = self._normalize_extract_payload(extract_result)

        # Contract identification
        contract_name = self._extract_field_value(
            normalized,
            "contract_name",
            aliases=["contractName", "agreement_name", "agreementName"],
        )
        if contract_name:
            contract_data["contract_name"] = contract_name

        contract_number = self._extract_field_value(
            normalized,
            "contract_number",
            aliases=["contractNumber", "agreement_number", "agreementNumber"],
        )
        if contract_number:
            contract_data["contract_number"] = contract_number
        elif contract_name:
            import re

            contract_data["contract_number"] = re.sub(r"[^a-zA-Z0-9]", "-", contract_name)[:50]

        contract_type = self._extract_field_value(
            normalized,
            "contract_type",
            aliases=["contractType", "type_of_contract", "typeOfContract"],
        )
        if contract_type:
            contract_data["contract_type"] = contract_type

        contract_sub_type = self._extract_field_value(
            normalized,
            "contract_sub_type",
            aliases=["contract_subtype", "contractSubType", "contractSubtype"],
        )
        if contract_sub_type:
            contract_data["contract_sub_type"] = contract_sub_type

        contract_nature = self._extract_field_value(
            normalized,
            "contract_nature",
            aliases=["contractNature", "nature_of_contract", "natureOfContract"],
        )
        if contract_nature:
            contract_data["contract_nature"] = contract_nature

        # If nature is embedded within the type, split into separate fields
        if contract_type and not contract_nature:
            for separator in (" - ", " – ", " — ", ":"):
                if separator in contract_type:
                    head, tail = contract_type.split(separator, 1)
                    if head and head != contract_type:
                        contract_data["contract_type"] = head.strip()
                    if tail:
                        contract_data["contract_nature"] = tail.strip()
                    break

        # Date fields
        effective_date = self._extract_field_value(
            normalized,
            "effective_date",
            aliases=["effectiveDate", "inception_date", "inceptionDate"],
        )
        if effective_date:
            contract_data["effective_date"] = self._normalize_date(str(effective_date))

        expiration_date = self._extract_field_value(
            normalized,
            "expiration_date",
            aliases=["expirationDate", "expiry_date", "expiryDate", "expiration"],
        )
        if expiration_date:
            contract_data["expiration_date"] = self._normalize_date(str(expiration_date))

        # Financial terms
        premium_amount = self._extract_field_value(
            normalized,
            "premium_amount",
            aliases=["premiumAmount", "contract_premium", "contractPremium"],
        )
        if premium_amount:
            cleaned_premium = self._clean_numeric_value(premium_amount)
            if cleaned_premium is not None:
                contract_data["premium_amount"] = cleaned_premium

        commission_rate = self._extract_field_value(
            normalized,
            "commission_rate",
            aliases=["commissionRate", "broker_commission", "brokerCommission"],
        )
        if commission_rate:
            cleaned_commission = self._clean_numeric_value(commission_rate)
            if cleaned_commission is not None:
                contract_data["commission_rate"] = cleaned_commission

        deductible_amount = self._extract_field_value(
            normalized,
            "deductible_amount",
            aliases=["retention_amount", "retentionAmount", "deductibleAmount"],
        )
        if deductible_amount:
            cleaned_deductible = self._clean_numeric_value(deductible_amount)
            if cleaned_deductible is not None:
                contract_data["retention_amount"] = cleaned_deductible

        limit_covered = self._extract_field_value(
            normalized,
            "limit_covered",
            aliases=["limitCovered", "coverage_limit", "coverageLimit"],
        )
        if limit_covered:
            cleaned_limit = self._clean_numeric_value(limit_covered)
            if cleaned_limit is not None:
                contract_data["limit_amount"] = cleaned_limit

        upper_limit = self._extract_field_value(
            normalized,
            "upper_limit",
            aliases=["upperLimit", "maximum_limit", "maximumLimit"],
        )
        if upper_limit:
            cleaned_upper_limit = self._clean_numeric_value(upper_limit)
            if cleaned_upper_limit is not None and "limit_amount" not in contract_data:
                contract_data["limit_amount"] = cleaned_upper_limit

        # Coverage details
        attachment_criteria = self._extract_field_value(
            normalized,
            "attachment_criteria",
            aliases=["attachmentCriteria", "coverage_description", "coverageDescription"],
        )
        if attachment_criteria:
            contract_data["coverage_description"] = attachment_criteria

        optional_fields = {
            "line_of_business": ["lineOfBusiness", "lob"],
            "coverage_territory": ["coverageTerritory", "territory"],
            "terms_and_conditions": ["termsAndConditions", "terms_conditions"],
            "special_provisions": ["specialProvisions", "special_clauses"],
            "currency": ["currency_code", "currencyCode"],
        }
        for field, aliases in optional_fields.items():
            value = self._extract_field_value(normalized, field, aliases=aliases)
            if value:
                if field == "currency":
                    currency = str(value).upper()
                    if len(currency) == 3:
                        contract_data["currency"] = currency
                else:
                    contract_data[field] = value

        # Default currency if missing
        contract_data.setdefault("currency", "USD")

        if not contract_data:
            logger.warning("No contract data was extracted from the document!")
            if normalized:
                logger.warning("Extract result had keys: %s", list(normalized.keys()))
            else:
                logger.warning("Extract result payload was empty.")

        return contract_data

    def _normalize_extract_payload(self, extract_result: Any) -> Dict[str, Any]:
        """
        Flatten nested extraction payloads into a simple dictionary mapping
        field names to scalar values. Handles common LandingAI shapes where fields are
        nested under ``data``, ``extraction``, or ``fields`` arrays.
        """
        flattened: Dict[str, Any] = {}
        seen: set[int] = set()

        def walk(node: Any) -> None:
            node_id = id(node)
            if node_id in seen:
                return
            seen.add(node_id)

            if isinstance(node, dict):
                for key, value in node.items():
                    if not isinstance(key, str):
                        continue
                    lowered_key = key.lower()
                    if lowered_key in {"confidence", "confidence_score"}:
                        continue

                    if lowered_key == "fields" and isinstance(value, list):
                        for entry in value:
                            if not isinstance(entry, dict):
                                continue
                            name = (
                                entry.get("name")
                                or entry.get("field_name")
                                or entry.get("key")
                                or entry.get("label")
                            )
                            if not name:
                                continue
                            entry_value = (
                                entry.get("value")
                                or entry.get("text")
                                or entry.get("content")
                                or entry.get("raw")
                            )
                            if entry_value is None:
                                entry_value = entry
                            extracted = self._unwrap_field_value(entry_value)
                            if extracted is not None and name not in flattened:
                                flattened[name] = extracted
                            walk(entry)
                        continue

                    extracted = self._unwrap_field_value(value)
                    if extracted is not None and key not in flattened:
                        flattened[key] = extracted

                    walk(value)

            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(extract_result)
        return flattened

    @staticmethod
    def _unwrap_field_value(value: Any) -> Optional[Any]:
        """
        Extract the most relevant scalar value from nested field structures.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return value

        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None

        if isinstance(value, dict):
            priority_keys = ["value", "text", "content", "answer", "raw", "body"]
            for key in priority_keys:
                if key in value:
                    extracted = LandingAIService._unwrap_field_value(value[key])
                    if extracted is not None:
                        return extracted

            values = value.get("values")
            if isinstance(values, list):
                for item in values:
                    extracted = LandingAIService._unwrap_field_value(item)
                    if extracted is not None:
                        return extracted

            if len(value) == 1:
                extracted = LandingAIService._unwrap_field_value(next(iter(value.values())))
                if extracted is not None:
                    return extracted

            return None

        if isinstance(value, list):
            for item in value:
                extracted = LandingAIService._unwrap_field_value(item)
                if extracted is not None:
                    return extracted
            return None

        return value

    def _extract_field_value(
        self,
        normalized: Dict[str, Any],
        field_name: str,
        *,
        aliases: Optional[List[str]] = None,
    ) -> Optional[Any]:
        """
        Look up a field by name (or alias) within a normalized extraction payload.
        Keys are compared case-insensitively.
        """
        if not normalized:
            return None

        candidates = [field_name] + (aliases or [])
        for candidate in candidates:
            if candidate in normalized and normalized[candidate] not in (None, "", []):
                return normalized[candidate]

        lower_map = {key.lower(): value for key, value in normalized.items()}
        for candidate in candidates:
            lowered = candidate.lower()
            if lowered in lower_map and lower_map[lowered] not in (None, "", []):
                return lower_map[lowered]

        return None

    def _process_parties_data(self, extract_result: Dict[str, Any]) -> list:
        """
        Process extracted parties data from cedant and reinsurer fields.

        Args:
            extract_result: Raw extraction result from Extract API

        Returns:
            List of party dictionaries
        """
        parties_data = []

        normalized = self._normalize_extract_payload(extract_result)

        logger.info("Processing parties data from cedant/reinsurer fields")

        cedant_name = self._extract_field_value(
            normalized,
            "cedant_name",
            aliases=["cedent_name", "cedantName", "cedentName"],
        )
        if cedant_name:
            cedant = {
                "name": cedant_name,
                "party_type": "cedant",
                "is_active": True,
            }
            parties_data.append(cedant)
            logger.info("Processed cedant: %s", cedant_name)

        reinsurer_name = self._extract_field_value(
            normalized,
            "reinsurer_name",
            aliases=["reinsurerName", "reinsurer", "retrocessionaire_name"],
        )
        if reinsurer_name:
            reinsurer = {
                "name": reinsurer_name,
                "party_type": "reinsurer",
                "is_active": True,
            }
            parties_data.append(reinsurer)
            logger.info("Processed reinsurer: %s", reinsurer_name)

        logger.info("Total parties processed: %d", len(parties_data))
        return parties_data

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """
        Normalize date string to YYYY-MM-DD format.
        Handles common date formats.
        """
        from datetime import datetime

        if not date_str:
            return date_str

        # Try common date formats
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%m-%d-%Y",
            "%d-%m-%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y"
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # If no format matches, return as-is
        logger.warning(f"Could not normalize date format: {date_str}")
        return date_str

    @staticmethod
    def _clean_numeric_value(value: Any) -> Optional[str]:
        """
        Clean numeric value by removing currency symbols, commas, percentages, etc.
        Returns string representation suitable for Decimal conversion.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return str(value)

        if isinstance(value, str):
            # Remove common currency symbols, commas, and formatting
            cleaned = value.replace("$", "").replace("€", "").replace("£", "")
            cleaned = cleaned.replace(",", "").replace(" ", "").strip()

            # Handle percentages
            if "%" in cleaned:
                cleaned = cleaned.replace("%", "").strip()
                # If it's a percentage, we might want to keep it as-is or convert
                # For now, just remove the % sign

            # Try to convert to float to validate
            try:
                float(cleaned)
                return cleaned
            except ValueError:
                logger.warning(f"Could not clean numeric value: {value}")
                return None

        return None


# Singleton instance
landingai_service = LandingAIService()
