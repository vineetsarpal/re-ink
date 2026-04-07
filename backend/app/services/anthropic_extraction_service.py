"""
Anthropic (Claude) document extraction service.

Uses Claude's native PDF vision to parse and extract contract fields in a
single API call — no separate OCR or parse step needed.
"""

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Reuse the JSON-parsing helper and field list from the free extraction service
from app.services.free_extraction_service import _parse_llm_json

_EXTRACTION_PROMPT_VISION = """\
You are an expert reinsurance contract analyst. Extract the following fields from the
attached document. Return ONLY a valid JSON object — no markdown fences, no extra text.
If a field cannot be found, use null.

Fields to extract:
- cedant_name: full legal name of the ceding insurer
- reinsurer_name: full legal name of the reinsurer
- contract_name: formal title of the agreement
- contract_type: Treaty or Facultative
- contract_sub_type: Quota Share, Surplus, XOL, etc.
- contract_nature: Proportional or Non-Proportional
- premium_amount: premium amount or share (string)
- commission_rate: commission percentage (string)
- deductible_amount: retention / deductible (string)
- limit_covered: coverage limit or percentage (string)
- upper_limit: maximum monetary limit (string)
- attachment_criteria: conditions under which claims attach
- effective_date: contract start date (YYYY-MM-DD preferred)
- expiration_date: contract end date (YYYY-MM-DD preferred)
- contract_number: unique contract/agreement number
- currency: 3-letter ISO currency code (e.g. USD)
- line_of_business: property, casualty, marine, etc.
- coverage_territory: geographic area of coverage
- coverage_description: brief coverage summary
- terms_and_conditions: key terms summary
- special_provisions: special clauses or exclusions

Return JSON only:"""


class AnthropicExtractionService:
    """Extraction via Claude's native PDF vision — one API call for parse + extract."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic as _anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic is required for the Anthropic extraction backend. "
                "Install it: pip install anthropic"
            ) from exc
        self.client = _anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def submit_document_for_extraction(
        self,
        file_path: str,
        progress_callback: Optional[Any] = None,
        **_kwargs,
    ) -> Dict[str, Any]:
        """
        Send the document to Claude for extraction.

        Returns the same shape as LandingAIService.submit_document_for_extraction().
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = path.suffix.lower()
        if ext == ".pdf":
            media_type = "application/pdf"
        elif ext in (".docx", ".doc"):
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            raise ValueError(f"Unsupported file type for Anthropic extraction: {ext}")

        pdf_b64 = base64.standard_b64encode(path.read_bytes()).decode()

        if progress_callback:
            progress_callback("Sending document to Claude for extraction...")

        logger.info("Anthropic extraction: sending %s to Claude (%s)", path.name, self.model)

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": pdf_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": _EXTRACTION_PROMPT_VISION,
                        },
                    ],
                }],
            ),
        )

        raw_text = response.content[0].text
        logger.info("Anthropic extraction: received %d chars", len(raw_text))

        try:
            extract_result = _parse_llm_json(raw_text)
        except json.JSONDecodeError as exc:
            logger.error("Claude returned non-JSON response: %s", raw_text[:500])
            raise ValueError(f"Anthropic extraction returned invalid JSON: {exc}") from exc

        return {
            "parse_result": {"markdown": "(parsed by Claude vision)"},
            "extract_result": extract_result,
            "metadata": {
                "filename": path.name,
                "markdown_length": 0,
                "parse_model": f"anthropic-{self.model}",
                "extract_model": f"anthropic-{self.model}",
            },
        }

    def parse_extraction_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw extraction output into the application's standard shape.

        Output mirrors LandingAIService.parse_extraction_results().
        """
        from app.services.landingai_service import LandingAIService

        _helper = LandingAIService.__new__(LandingAIService)
        return _helper.parse_extraction_results(raw_results)
