"""
Free-tier document extraction service.

A free alternative to LandingAI ADE that uses:
  - Local document parsing — two backends selectable via FREE_PARSE_BACKEND:
      "pypdf"   → pypdf + python-docx (text-based PDFs only, no GPU needed)
      "glm-ocr" → GLM-OCR via Ollama (handles scanned + complex PDFs, 0.9B VLM)
  - LLM-based field extraction: configurable via FREE_LLM_PROVIDER
      "openai"  → uses OPENAI_API_KEY (pay-per-use, no LandingAI subscription needed)
      "ollama"  → uses a locally-running Ollama instance (fully free, offline-capable)

Public interface is identical to LandingAIService so the two can be swapped
by changing EXTRACTION_BACKEND in the environment.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document → Markdown helpers
# ---------------------------------------------------------------------------

def _pdf_to_markdown(file_path: Path) -> str:
    """Extract text from a PDF and return a plain-markdown representation."""
    from pypdf import PdfReader

    reader = PdfReader(str(file_path))
    sections: List[str] = []
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            sections.append(f"## Page {page_num}\n\n{text.strip()}")

    return "\n\n".join(sections)


def _docx_to_markdown(file_path: Path) -> str:
    """Extract text from a DOCX and return a plain-markdown representation."""
    from docx import Document

    doc = Document(str(file_path))
    lines: List[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style else ""
        if style.startswith("Heading 1"):
            lines.append(f"# {text}")
        elif style.startswith("Heading 2"):
            lines.append(f"## {text}")
        elif style.startswith("Heading"):
            lines.append(f"### {text}")
        else:
            lines.append(text)

    return "\n\n".join(lines)


_OLLAMA_PAGE_TIMEOUT = 180  # seconds per page — Ollama on CPU can be slow


def _glm_ocr_parse(
    file_path: Path,
    ollama_base_url: str,
    parse_model: str,
    progress_callback: Optional[Any] = None,
    max_pages: int = 10,
    dpi: int = 150,
) -> str:
    """
    Convert each PDF page to a 300-DPI JPEG with pymupdf and run it through
    GLM-OCR via Ollama.  Returns concatenated per-page markdown.

    Requires:
      - pymupdf installed  (pip install pymupdf)
      - Ollama running with glm-ocr pulled  (ollama pull glm-ocr)

    NOTE: num_ctx MUST be 16384+ — Ollama's default 4096 crashes on image input.
    """
    import base64
    import json as _json
    import urllib.request

    try:
        import pymupdf  # fitz
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required for FREE_PARSE_BACKEND=glm-ocr. "
            "Install it: pip install pymupdf"
        ) from exc

    doc = pymupdf.open(str(file_path))
    total_pages = len(doc)
    pages_to_process = min(total_pages, max_pages)
    if total_pages > max_pages:
        logger.warning("Document has %d pages; processing first %d (FREE_MAX_PAGES=%d)", total_pages, max_pages, max_pages)
    pages_markdown: List[str] = []

    for page_num, page in enumerate(doc):
        if page_num >= pages_to_process:
            break
        if progress_callback:
            progress_callback(f"Parsing page {page_num + 1} of {pages_to_process} with GLM-OCR...")

        scale = dpi / 72
        mat = pymupdf.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        image_b64 = base64.b64encode(pix.tobytes("jpeg")).decode()

        payload = {
            "model": parse_model,
            "messages": [{
                "role": "user",
                "content": (
                    "Convert this document page to clean markdown. "
                    "Preserve all text, tables, headings, and structure exactly."
                ),
                "images": [image_b64],  # Ollama expects raw base64, not a data URI
            }],
            "stream": False,
            "options": {"num_ctx": 16384},
        }

        req = urllib.request.Request(
            f"{ollama_base_url}/api/chat",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = _json.loads(urllib.request.urlopen(req, timeout=_OLLAMA_PAGE_TIMEOUT).read())
        page_text = resp["message"]["content"]
        pages_markdown.append(f"## Page {page_num + 1}\n\n{page_text}")
        logger.info("GLM-OCR parsed page %d/%d (%d chars)", page_num + 1, total_pages, len(page_text))

    return "\n\n".join(pages_markdown)


def _parse_document_to_markdown(
    file_path: Path,
    backend: str = "pypdf",
    progress_callback: Optional[Any] = None,
    **kwargs,
) -> str:
    """Dispatch to the correct parser based on backend setting and file extension."""
    ext = file_path.suffix.lower()

    if backend == "glm-ocr":
        if ext not in (".pdf",):
            # DOCX doesn't benefit from vision OCR — fall back to python-docx
            logger.info("GLM-OCR parse backend only supports PDF; falling back to python-docx for %s", ext)
            return _docx_to_markdown(file_path)
        return _glm_ocr_parse(file_path, progress_callback=progress_callback, **kwargs)

    # Default: pypdf / python-docx
    if progress_callback:
        progress_callback("Parsing document text...")
    if ext == ".pdf":
        return _pdf_to_markdown(file_path)
    if ext in (".docx", ".doc"):
        return _docx_to_markdown(file_path)
    raise ValueError(f"Unsupported file type for free extraction: {ext}")


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are an expert reinsurance contract analyst. Extract the following fields from the
document text below. Return ONLY a valid JSON object — no markdown fences, no extra text.
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

Document text:
\"\"\"
{document_text}
\"\"\"

Return JSON only:"""


def _build_llm(provider: str, model: str, ollama_base_url: str, openai_api_key: str = ""):
    """Instantiate a LangChain chat model for the requested provider."""
    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "langchain-ollama is required for free extraction with Ollama. "
                "Install it: pip install langchain-ollama"
            ) from exc
        return ChatOllama(model=model, base_url=ollama_base_url, temperature=0)

    # Default: OpenAI-compatible
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for free extraction with OpenAI. "
            "Install it: pip install langchain-openai"
        ) from exc

    from app.core.config import settings
    api_key = openai_api_key or settings.OPENAI_API_KEY
    return ChatOpenAI(
        model=model,
        temperature=0,
        openai_api_key=api_key,
    )


def _invoke_llm(llm, prompt: str) -> str:
    """Invoke the LLM synchronously and return the text content."""
    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content if hasattr(response, "content") else str(response)


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences if present and parse JSON."""
    text = raw.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class FreeExtractionService:
    """
    Drop-in free alternative to LandingAIService.

    Configuration (via environment / Settings):
      EXTRACTION_BACKEND=free
      FREE_LLM_PROVIDER=openai   # or "ollama"
      FREE_LLM_MODEL=gpt-4o-mini # or e.g. "llama3"
      FREE_OLLAMA_BASE_URL=http://localhost:11434
    """

    def __init__(self, openai_api_key: str = ""):
        from app.core.config import settings

        self.parse_backend = settings.FREE_PARSE_BACKEND
        self.parse_model = settings.FREE_PARSE_MODEL
        self.max_pages = settings.FREE_MAX_PAGES
        self.parse_dpi = settings.FREE_PARSE_DPI
        self.provider = settings.FREE_LLM_PROVIDER
        self.model = settings.FREE_LLM_MODEL
        self.ollama_base_url = settings.FREE_OLLAMA_BASE_URL
        self._openai_api_key = openai_api_key
        self._llm = None  # lazy-initialised

    def _get_llm(self):
        if self._llm is None:
            self._llm = _build_llm(self.provider, self.model, self.ollama_base_url, self._openai_api_key)
        return self._llm

    # ------------------------------------------------------------------
    # Public interface (mirrors LandingAIService)
    # ------------------------------------------------------------------

    async def submit_document_for_extraction(
        self,
        file_path: str,
        progress_callback: Optional[Any] = None,
        **_kwargs,
    ) -> Dict[str, Any]:
        """
        Parse the document locally and extract structured fields via LLM.

        Returns the same shape as LandingAIService.submit_document_for_extraction().
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Step 1 — local parse
        logger.info(
            "Free extraction: parsing document (%s backend) — %s",
            self.parse_backend, path.name
        )
        parse_kwargs: Dict[str, Any] = {}
        if self.parse_backend == "glm-ocr":
            parse_kwargs = {
                "ollama_base_url": self.ollama_base_url,
                "parse_model": self.parse_model,
                "max_pages": self.max_pages,
                "dpi": self.parse_dpi,
            }
        markdown = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _parse_document_to_markdown(
                path,
                backend=self.parse_backend,
                progress_callback=progress_callback,
                **parse_kwargs,
            ),
        )
        if not markdown.strip():
            raise ValueError("Document parsing produced no extractable text.")
        logger.info("Free extraction: parsed %d chars of markdown", len(markdown))

        # Step 2 — LLM extraction
        if progress_callback:
            progress_callback("Extracting contract fields with LLM...")
        logger.info("Free extraction: running LLM field extraction (%s / %s)", self.provider, self.model)
        extract_result = await asyncio.get_event_loop().run_in_executor(
            None, self._run_extraction, markdown
        )
        logger.info("Free extraction: completed")

        return {
            "parse_result": {"markdown": markdown},
            "extract_result": extract_result,
            "metadata": {
                "filename": path.name,
                "markdown_length": len(markdown),
                "parse_model": f"free-{self.parse_backend}" + (f"-{self.parse_model}" if self.parse_backend == "glm-ocr" else f"-{path.suffix.lstrip('.')}"),
                "extract_model": f"free-{self.provider}-{self.model}",
            },
        }

    def parse_extraction_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw extraction output into the application's standard shape.

        Output mirrors LandingAIService.parse_extraction_results().
        """
        from app.services.landingai_service import LandingAIService

        # Reuse the identical post-processing logic from LandingAIService
        _helper = LandingAIService.__new__(LandingAIService)
        return _helper.parse_extraction_results(raw_results)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_extraction(self, markdown: str) -> Dict[str, Any]:
        """Run the LLM synchronously (called from a thread executor)."""
        llm = self._get_llm()
        # Truncate very long documents to stay within context limits
        max_chars = 40_000
        if len(markdown) > max_chars:
            logger.warning(
                "Document markdown truncated from %d to %d chars for LLM context",
                len(markdown),
                max_chars,
            )
            markdown = markdown[:max_chars]

        prompt = _EXTRACTION_PROMPT.format(document_text=markdown)
        raw = _invoke_llm(llm, prompt)

        try:
            return _parse_llm_json(raw)
        except json.JSONDecodeError as exc:
            logger.error("LLM returned non-JSON response: %s", raw[:500])
            raise ValueError(f"LLM extraction returned invalid JSON: {exc}") from exc


# Singleton instance — only constructed when the module is imported
free_extraction_service = FreeExtractionService()
