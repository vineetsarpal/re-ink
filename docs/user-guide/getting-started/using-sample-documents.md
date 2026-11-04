# Using Synthetic Documents

Use synthetic files to demonstrate the workflow without exposing customer contracts. The six evaluation originals are in [`backend/tests/corpus`](../../../backend/tests/corpus/README.md), with ordinary PDF, scanned PDF, DOCX, ambiguous fields, multiple parties and unreadable cases.

1. Obtain the intended synthetic original from your demo operator.
2. Go to **Upload**, select the file and choose **Upload & Process**.
3. Wait for the configured workflow, then review the actual result and correct it against the original.

These files use the real extraction path and can incur provider charges. There is no sample-extraction switch or automatic mock fallback in the application. Deterministic integration/UI fixtures are separately labeled developer checks; they do not demonstrate live provider quality.

Missing evidence is expected for the minimal OpenAI implementation. Verify fields against the original and disclose this difference when presenting the demo. Approve synthetic records only when you intentionally want them in the demo environment.
