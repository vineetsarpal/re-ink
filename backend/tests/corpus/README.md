# Synthetic extraction corpus

These six originals and the expected-results manifest are independent synthetic fixtures drafted before any provider execution. No real customer data or live provider output is included. A human must review and sign off the source facts and expected-results manifest before treating it as human-confirmed ground truth. That review has **not been performed**.

| Case | Original | Expected behavior |
| --- | --- | --- |
| ordinary | `ordinary.pdf` | Explicit contract identity, dates, USD terms, cedant/reinsurer; useful draft |
| scanned | `scanned.pdf` | Same bounded facts as image-only PDF, no selectable text; OCR/vision outcome recorded |
| docx | `docx.docx` | Explicit facts split across paragraphs and table; original download, no PDF overlays |
| ambiguous | `ambiguous.pdf` | Currency absent, effective date and dollar premium ambiguous; no invented defaults |
| multiple | `multiple.pdf` | Four named parties: cedant, two reinsurers, broker; aligned roles/evidence |
| unreadable | `unreadable.pdf` | Valid one-page blank PDF; safe failed outcome, no invented facts/empty success |

`expected.json` contains present canonical scalar values, missing/ambiguous fields, party names/roles, verbatim available source lines and page numbers. It intentionally contains no guessed ADE boxes. Verify provider-supplied quote support and rectangles against the rendered originals manually. DOCX has no reviewable PDF rendition; conversion coordinates must be omitted. The DOCX QA PDF is an intermediate artifact outside this corpus, not an authorized evidence rendition.

`generate.py` deterministically creates originals using reportlab, Pillow and python-docx; PDF metadata and DOCX ZIP timestamps are fixed. Repeated generation should preserve hashes. It requires these packages and an Arial font at the documented macOS path; originals are checked in so the backend suite needs none of those authoring dependencies. The backend verifies the PDFs with pypdf. Fixture structure tests prove the scanned original has an image and no extracted text; they do not prove a provider OCR outcome.

All six originals were rendered for visual fixture QA; the blank case is intentionally blank. No provider quality denominator exists until recorded provider runs are evaluated. Run both providers on the same frozen originals and release, retaining all failures/reruns/configuration changes.

From the repository root, score recorded normalized runs offline:

```sh
python3 scripts/evaluate_corpus.py /secure/path/recorded-runs.jsonl --output /secure/path/report.json
```

Each JSONL line needs `case_id`, `provider` (`landingai` or `openai`), `mode` (`fixture` or `live`), unique `run_id`, `release`, `model`, `job_id`, `attempt_id`, `workflow_execution_id`, terminal `status`, and normalized `result` for completed outcomes. Record failed/timed-out outcomes with `error_code`. All fixture metadata should say `fixture`; an operator's `mode=live` declaration is not verified by this offline script. Preserve actual provider/API/workflow versions and configuration changes in the accompanying execution record. Never write secrets into these artifacts.

The scorer reports each execution separately; it does not select best reruns. Present scalar denominators exclude failed cases rather than counting unobserved predictions as successes; case failures remain explicit. Dates require ISO values, currency is compared case-insensitively and numbers compare as decimal values. Long descriptions and unexpected fields need manual source review. Party names and roles have separate denominators. Literal quote matching is a mechanical aid and cannot establish semantic support, ADE rectangle fidelity or citation truth. Manual correction, citation checks and signoff must be recorded separately. Six synthetic documents do not support a production accuracy claim or comparison of provider confidence scales.
