# Uploading a Contract

Use the Upload page to submit a PDF or DOCX reinsurance contract. This simulated customer demo accepts synthetic documents only. Its separately hosted workflow sends documents to an external AI provider. Your administrator configures extraction; the upload form needs no provider key.

## Upload a document

1. Go to **Upload** with document-upload permission.
2. Drag a file into the upload area, or select it from your computer. The maximum upload is 50 MiB; a provider may impose a smaller limit.
3. Select **Upload & Process**.
4. Wait through queued and processing states. The review form opens when extraction completes.

If extraction fails or times out, review the displayed safe error and select **Retry extraction** when available. Retry starts a new attempt and may incur another provider charge. It does not approve a contract. Uploads and Retry are unavailable while your administrator pauses the workflow.

## What happens after upload

re-ink stores the immutable original privately and durably queues extraction. The workflow returns contract fields, parties and available source evidence. Missing values and evidence remain visible for manual review; they are not automatically supplied. PDF supports source highlighting when genuine page/box evidence is available. DOCX uses the original download and text evidence, with no inline page preview.

Check the original, correct missing or incorrect values, and explicitly select currency and party roles before approval. Approval requires the existing review permission and creates local records.
