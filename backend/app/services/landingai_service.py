"""
Service layer for integrating with LandingAI's ADE (Agentic Document Extraction) API.
Uses the official landingai-ade SDK for document parsing and field extraction.

"""
import logging
from typing import Dict, Any, Optional
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
        self.parse_model = settings.LANDINGAI_PARSE_MODEL
        self.extract_model = settings.LANDINGAI_EXTRACT_MODEL

    def _get_client(self, api_key: Optional[str] = None) -> LandingAIADE:
        """Return a LandingAIADE client using the provided key or the server default."""
        key = api_key or settings.LANDINGAI_API_KEY
        if not key:
            raise ValueError(
                "No LandingAI API key provided. "
                "Supply your key in the upload form or set LANDINGAI_API_KEY in the server environment."
            )
        return LandingAIADE(apikey=key)

    async def submit_document_for_extraction(
        self,
        file_path: str,
        api_key: Optional[str] = None,
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
            client = self._get_client(api_key)

            # Step 1: Parse document to markdown
            logger.info(f"Starting document parsing for: {file_path}")
            parse_result = await self._parse_document(
                file_path=file_path,
                model=parse_model or self.parse_model,
                client=client,
            )

            markdown = parse_result.get("markdown", "")
            if not markdown:
                raise Exception("Parse API returned empty markdown content")

            logger.info(f"Document parsed successfully. Markdown length: {len(markdown)}")

            # Step 2: Extract structured data from markdown
            logger.info("Starting field extraction from parsed document")
            extract_result = await self._extract_fields(
                markdown=markdown,
                model=extract_model or self.extract_model,
                client=client,
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
        client: LandingAIADE,
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
                lambda: client.parse(
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
        model: str,
        client: LandingAIADE,
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
            # Returns a JSON string — the SDK extract method expects it as a string
            schema = pydantic_to_json_schema(ReinsuranceContractFieldExtractionSchema)

            logger.info(f"Extracting fields with model: {model}")
            if isinstance(schema, str):
                import json as _json
                logger.debug(f"Schema keys: {list(_json.loads(schema).get('properties', {}).keys())}")
            else:
                logger.debug(f"Schema keys: {list(schema.get('properties', {}).keys())}")

            # Use the SDK's extract method
            # Convert markdown string to BytesIO for the SDK
            markdown_bytes = BytesIO(markdown.encode('utf-8'))

            import asyncio
            loop = asyncio.get_event_loop()
            extract_response = await loop.run_in_executor(
                None,
                lambda: client.extract(
                    schema=schema,
                    markdown=markdown_bytes,
                    model=model,
                )
            )

            # The SDK returns a response object
            # We need to convert it to a dictionary for our processing
            if hasattr(extract_response, 'model_dump'):
                result = extract_response.model_dump()
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
        Map the Extract API response onto Contract DB columns.

        The extraction schema (see extraction_schema.py) exposes a 1:1 shape with
        the DB model: raw `*_text` fields map to `*_description` columns and
        numeric `*_amount` / `*_rate` fields map directly. Dates arrive as ISO
        strings thanks to the `date` type hint; we still pass them through
        _normalize_date defensively.
        """
        contract_data: Dict[str, Any] = {}

        # Some SDKs wrap the payload; unwrap once if present.
        data = extract_result
        if "data" in extract_result:
            data = extract_result["data"]
        elif "extraction" in extract_result:
            data = extract_result["extraction"]

        logger.info(
            f"Processing contract data. Available keys: {list(data.keys()) if data else 'None'}"
        )

        # Identification
        if data.get("contract_name"):
            contract_data["contract_name"] = data["contract_name"]

        if data.get("contract_number"):
            contract_data["contract_number"] = data["contract_number"]
        elif data.get("contract_name"):
            import re
            contract_data["contract_number"] = re.sub(
                r"[^a-zA-Z0-9]", "-", data["contract_name"]
            )[:50]

        for field in ("contract_type", "contract_sub_type", "contract_nature"):
            if data.get(field):
                contract_data[field] = data[field]

        # Period
        for date_field in ("effective_date", "expiration_date"):
            if data.get(date_field):
                contract_data[date_field] = self._normalize_date(str(data[date_field]))

        # Currency (default USD, validate ISO 4217 length)
        if data.get("currency"):
            currency = str(data["currency"]).upper().strip()
            if len(currency) == 3:
                contract_data["currency"] = currency
        contract_data.setdefault("currency", "USD")

        # Financial terms — text/amount pairs map to description/amount columns
        for text_key, amount_key, desc_col, amount_col in (
            ("premium_text",    "premium_amount",    "premium_description",    "premium_amount"),
            ("retention_text",  "retention_amount",  "retention_description",  "retention_amount"),
            ("limit_text",      "limit_amount",      "limit_description",      "limit_amount"),
            ("commission_text", "commission_rate",   "commission_description", "commission_rate"),
        ):
            if data.get(text_key):
                contract_data[desc_col] = data[text_key]
            if data.get(amount_key) is not None:
                contract_data[amount_col] = self._clean_numeric_value(data[amount_key])

        # Coverage & terms
        for field in (
            "line_of_business",
            "coverage_territory",
            "coverage_description",
            "terms_and_conditions",
            "special_provisions",
        ):
            if data.get(field):
                contract_data[field] = data[field]

        if len(contract_data) <= 1:
            logger.warning("No contract data was extracted from the document!")
            logger.warning(f"Extract result had keys: {list(data.keys()) if data else 'Empty'}")

        return contract_data

    def _process_parties_data(self, extract_result: Dict[str, Any]) -> list:
        """
        Process extracted parties data from cedant and reinsurer fields.

        Args:
            extract_result: Raw extraction result from Extract API

        Returns:
            List of party dictionaries
        """
        parties_data = []

        # Check if data is nested
        data = extract_result
        if "data" in extract_result:
            data = extract_result["data"]
        elif "extraction" in extract_result:
            data = extract_result["extraction"]

        logger.info(f"Processing parties data from cedant/reinsurer fields")

        # Extract cedant
        if "cedant_name" in data and data["cedant_name"]:
            cedant = {
                "name": data["cedant_name"],
                "role": "cedant",  # Role on *this* contract; not a property of the party
                "is_active": True,
            }
            parties_data.append(cedant)
            logger.info(f"Processed cedant: {cedant['name']}")

        # Extract reinsurer
        if "reinsurer_name" in data and data["reinsurer_name"]:
            reinsurer = {
                "name": data["reinsurer_name"],
                "role": "reinsurer",  # Role on *this* contract
                "is_active": True,
            }
            parties_data.append(reinsurer)
            logger.info(f"Processed reinsurer: {reinsurer['name']}")

        logger.info(f"Total parties processed: {len(parties_data)}")
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


landingai_service = LandingAIService()
