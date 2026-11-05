"""
Service layer for integrating with LandingAI's ADE (Agentic Document Extraction) API.
Uses the official landingai-ade SDK for document parsing and field extraction.

"""
import html
import logging
import re
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

            # Capture the per-chunk grounding (id, page, bounding box, markdown
            # text). Extract's `extraction_metadata` references these chunk ids,
            # so we must carry them forward to build source evidence later.
            chunks = self._serialize_chunks(getattr(parse_response, "chunks", None))

            logger.info(
                f"Parse completed. Markdown length: {len(markdown)}, chunks: {len(chunks)}"
            )

            return {
                "markdown": markdown,
                "chunks": chunks,
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
            parse_result = raw_results.get("parse_result", {})
            metadata = raw_results.get("metadata", {})

            # Debug logging to see actual structure
            logger.info(f"Raw results structure: {list(raw_results.keys())}")
            logger.info(f"Extract result structure: {list(extract_result.keys()) if extract_result else 'Empty'}")

            # --- Source grounding -------------------------------------------
            # LandingAI's extract response carries a per-field `extraction_metadata`
            # mapping (field -> {value, references:[chunk_id|cell_id, ...]}). Each
            # reference points at a parse chunk (id, page, bounding box, markdown
            # text). We resolve those into reviewer-facing source evidence.
            #
            # NB: this LandingAI key is unrelated to our own output
            # `extraction_metadata` (processing metadata: filename, models).
            chunk_index = self._build_chunk_index(parse_result.get("chunks"))
            field_refs = extract_result.get("extraction_metadata") or {}
            if isinstance(field_refs, dict) and "data" in field_refs and "extraction" not in field_refs:
                # Some SDK shapes nest the per-field map under `data`.
                field_refs = field_refs.get("data") or field_refs
            field_sources: Dict[str, Any] = {"contract": {}, "parties": []}

            # Process the extracted data (also records source evidence in-place)
            contract_data = self._process_contract_data(
                extract_result, field_refs, chunk_index, field_sources["contract"]
            )
            parties_data = self._process_parties_data(
                extract_result, field_refs, chunk_index, field_sources["parties"]
            )

            logger.info(f"Processed contract_data keys: {list(contract_data.keys()) if contract_data else 'Empty'}")
            logger.info(f"Processed parties_data count: {len(parties_data)}")
            logger.info(
                f"Source evidence: {len(field_sources['contract'])} contract fields, "
                f"{sum(1 for p in field_sources['parties'] if p)} parties grounded"
            )

            # Calculate confidence score if available
            confidence_score = extract_result.get("confidence", None)

            return {
                "contract_data": contract_data,
                "parties_data": parties_data,
                "field_sources": field_sources,
                "confidence_score": confidence_score,
                "extraction_metadata": metadata
            }

        except Exception as e:
            logger.error(f"Error parsing extraction results: {str(e)}", exc_info=True)
            raise

    def _process_contract_data(
        self,
        extract_result: Dict[str, Any],
        field_refs: Optional[Dict[str, Any]] = None,
        chunk_index: Optional[Dict[str, Any]] = None,
        contract_sources: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Map the Extract API response onto Contract DB columns.

        The extraction schema (see extraction_schema.py) exposes a 1:1 shape with
        the DB model: raw `*_text` fields map to `*_description` columns and
        numeric `*_amount` / `*_rate` fields map directly. Dates arrive as ISO
        strings thanks to the `date` type hint; we still pass them through
        _normalize_date defensively.

        When `field_refs` and `chunk_index` are supplied, source evidence for
        each populated column is recorded in `contract_sources`, keyed by the
        *display* column name (e.g. `premium_description`), resolved from the
        underlying schema field (e.g. `premium_text`).
        """
        contract_data: Dict[str, Any] = {}
        field_refs = field_refs or {}
        chunk_index = chunk_index or {}
        if contract_sources is None:
            contract_sources = {}

        def record(display_name: str, schema_field: str) -> None:
            """Resolve and store source evidence for one display column."""
            source = self._resolve_source(schema_field, field_refs, chunk_index)
            if source:
                contract_sources[display_name] = source

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
            record("contract_name", "contract_name")

        if data.get("contract_number"):
            contract_data["contract_number"] = data["contract_number"]
            record("contract_number", "contract_number")
        elif data.get("contract_name"):
            import re
            contract_data["contract_number"] = re.sub(
                r"[^a-zA-Z0-9]", "-", data["contract_name"]
            )[:50]

        for field in ("contract_type", "contract_sub_type", "contract_nature"):
            if data.get(field):
                contract_data[field] = data[field]
                record(field, field)

        # Period
        for date_field in ("effective_date", "expiration_date"):
            if data.get(date_field):
                contract_data[date_field] = self._normalize_date(str(data[date_field]))
                record(date_field, date_field)

        # Currency (default USD, validate ISO 4217 length)
        if data.get("currency"):
            currency = str(data["currency"]).upper().strip()
            if len(currency) == 3:
                contract_data["currency"] = currency
                record("currency", "currency")
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
                record(desc_col, text_key)
            if data.get(amount_key) is not None:
                contract_data[amount_col] = self._clean_numeric_value(data[amount_key])
                record(amount_col, amount_key)

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
                record(field, field)

        if len(contract_data) <= 1:
            logger.warning("No contract data was extracted from the document!")
            logger.warning(f"Extract result had keys: {list(data.keys()) if data else 'Empty'}")

        return contract_data

    def _process_parties_data(
        self,
        extract_result: Dict[str, Any],
        field_refs: Optional[Dict[str, Any]] = None,
        chunk_index: Optional[Dict[str, Any]] = None,
        party_sources: Optional[list] = None,
    ) -> list:
        """
        Process extracted parties data from cedant and reinsurer fields.

        Args:
            extract_result: Raw extraction result from Extract API
            field_refs: LandingAI per-field reference map (optional)
            chunk_index: Resolved parse-chunk index (optional)
            party_sources: List filled in lockstep with the returned parties so
                each entry's source evidence aligns by index (optional)

        Returns:
            List of party dictionaries
        """
        parties_data = []
        field_refs = field_refs or {}
        chunk_index = chunk_index or {}
        if party_sources is None:
            party_sources = []

        # Check if data is nested
        data = extract_result
        if "data" in extract_result:
            data = extract_result["data"]
        elif "extraction" in extract_result:
            data = extract_result["extraction"]

        logger.info(f"Processing parties data from cedant/reinsurer fields")

        def party_source(schema_field: str) -> Dict[str, Any]:
            """Build the per-party source map (only the name is grounded)."""
            source = self._resolve_source(schema_field, field_refs, chunk_index)
            return {"name": source} if source else {}

        # Extract cedant
        if "cedant_name" in data and data["cedant_name"]:
            cedant = {
                "name": data["cedant_name"],
                "role": "cedant",  # Role on *this* contract; not a property of the party
                "is_active": True,
            }
            parties_data.append(cedant)
            party_sources.append(party_source("cedant_name"))
            logger.info(f"Processed cedant: {cedant['name']}")

        # Extract reinsurer
        if "reinsurer_name" in data and data["reinsurer_name"]:
            reinsurer = {
                "name": data["reinsurer_name"],
                "role": "reinsurer",  # Role on *this* contract
                "is_active": True,
            }
            parties_data.append(reinsurer)
            party_sources.append(party_source("reinsurer_name"))
            logger.info(f"Processed reinsurer: {reinsurer['name']}")

        logger.info(f"Total parties processed: {len(parties_data)}")
        return parties_data

    # ------------------------------------------------------------------ #
    # Source grounding helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize_chunks(chunks: Any) -> list:
        """
        Normalise the parse response `chunks` into a list of plain dicts.

        Each chunk carries `id`, `markdown`, `type`, and a `grounding`
        ({page, box}). The SDK returns pydantic models; we model_dump them so
        they survive JSONB persistence and re-parsing from stored raw_results.
        """
        result = []
        for chunk in chunks or []:
            if hasattr(chunk, "model_dump"):
                result.append(chunk.model_dump())
            elif isinstance(chunk, dict):
                result.append(chunk)
        return result

    @staticmethod
    def _clean_source_text(markdown: Optional[str]) -> Optional[str]:
        """
        Turn chunk markdown into reviewer-facing evidence text.

        DPT chunk markdown embeds HTML artifacts — anchor tags like
        ``<a id='...'></a>``, comments, table markup — that mean nothing to a
        reviewer. Strip tags/comments, unescape entities, and collapse the
        blank lines left behind.
        """
        if not markdown:
            return markdown
        text = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or None

    @staticmethod
    def _build_chunk_index(chunks: Any) -> Dict[str, Dict[str, Any]]:
        """
        Index parse chunks by id for O(1) reference resolution.

        Returns ``{chunk_id: {page_number, bbox, source_text}}``. Page numbers
        from LandingAI are 0-indexed; we normalise to 1-indexed for display.
        """
        index: Dict[str, Dict[str, Any]] = {}
        for chunk in chunks or []:
            chunk_id = chunk.get("id")
            if not chunk_id:
                continue
            grounding = chunk.get("grounding") or {}
            page = grounding.get("page")
            index[chunk_id] = {
                "page_number": (page + 1) if isinstance(page, int) else None,
                "bbox": grounding.get("box"),
                "source_text": LandingAIService._clean_source_text(chunk.get("markdown")),
            }
        return index

    @staticmethod
    def _resolve_source(
        schema_field: str,
        field_refs: Dict[str, Any],
        chunk_index: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve source evidence for one extracted field.

        Looks up the field in LandingAI's per-field reference map and walks its
        `references` (chunk ids, table-cell ids like ``"0-u"``, or element ids)
        against the parse chunk index. Resolution is defensive:

        - a reference that matches a chunk id  -> full evidence (text/page/box)
        - an unresolved ``"{page}-{seq}"`` ref -> salvage the page number only
        - no usable references                  -> ``None`` ("no source found")
        """
        meta = field_refs.get(schema_field) if isinstance(field_refs, dict) else None
        if not isinstance(meta, dict):
            return None

        references = meta.get("references") or meta.get("chunk_references") or []
        if isinstance(references, str):
            references = [references]
        value = meta.get("value")

        salvaged_page: Optional[int] = None
        for ref in references:
            if ref in chunk_index:
                resolved = chunk_index[ref]
                return {
                    "value": value,
                    "source_text": resolved.get("source_text"),
                    "page_number": resolved.get("page_number"),
                    "chunk_id": ref,
                    "bbox": resolved.get("bbox"),
                    "confidence": meta.get("confidence"),
                }
            # Table-cell / element ids look like "{page}-{seq}" (0-indexed page).
            if salvaged_page is None and isinstance(ref, str) and "-" in ref:
                head = ref.split("-", 1)[0]
                if head.isdigit():
                    salvaged_page = int(head) + 1

        if references:
            # We have references but couldn't resolve full grounding — return a
            # partial source so the reviewer still gets a page hint.
            return {
                "value": value,
                "source_text": None,
                "page_number": salvaged_page,
                "chunk_id": references[0] if isinstance(references[0], str) else None,
                "bbox": None,
                "confidence": meta.get("confidence"),
            }
        return None

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
