/** Upload, durable workflow status, and human review. */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@workos-inc/authkit-react';
import { FileUpload } from '@/components/FileUpload';
import { ExtractionStatus } from '@/components/ExtractionStatus';
import { ReviewForm } from '@/components/ReviewForm';
import { documentApi, systemApi } from '@/services/api';
import type { DocumentUploadResponse, DocumentExtractionStatus, SystemConfig } from '@/types';

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const { permissions } = useAuth();
  const [upload, setUpload] = useState<DocumentUploadResponse | null>(null);
  const [result, setResult] = useState<DocumentExtractionStatus | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  useEffect(() => { systemApi.getConfig().then(setConfig).catch(() => setConfigError(true)); }, []);
  const reset = () => { setUpload(null); setResult(null); };
  const reject = async () => {
    if (!upload) return;
    try { await documentApi.delete(upload.job_id); reset(); }
    catch { alert('Unable to delete extraction. Please try again.'); }
  };
  const downloadOriginal = async () => {
    if (!upload) return;
    try {
      const data = await documentApi.getFileData(upload.job_id);
      const url = URL.createObjectURL(new Blob([data as BlobPart]));
      const link = document.createElement('a'); link.href = url; link.download = upload.filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { alert('Unable to download the original document.'); }
  };
  const isDocx = upload?.filename.toLowerCase().endsWith('.docx');
  return <div className="upload-page">
    <div className="page-header"><h1>Upload Contract Document</h1></div>
    <p>Simulated customer demo: use synthetic documents only. Extraction runs in a separately hosted workflow and sends documents to an external AI provider. Human approval creates local records.</p>
    {!upload && (config?.workflow_extraction_enabled && permissions.includes('document:upload')
      ? <FileUpload onUploadSuccess={(response) => { setUpload(response); setResult(null); }} />
      : <p>{configError ? 'Unable to check extraction availability.' : !config ? 'Checking extraction availability…' : 'Document uploads are currently unavailable.'}</p>)}
    {upload && !result?.result && <>
      <ExtractionStatus jobId={upload.job_id} onComplete={setResult}
        retryAvailable={!!config?.workflow_retry_available && permissions.includes('document:upload')}
        onRetry={(response) => { setUpload(response); setResult(null); }} />
      <button className="btn btn-secondary" onClick={reset}>Back to upload</button>
    </>}
    {upload && result?.result && <>
      {isDocx && <p>DOCX inline preview and page highlights are unavailable. Verify text evidence against the downloaded original. <button type="button" className="btn btn-secondary" onClick={downloadOriginal}>Download original DOCX</button></p>}
      <ReviewForm extractionResult={result.result}
        documentSource={isDocx ? null : documentApi.getFileSource(upload.job_id)}
        onApprove={(id, _partyIds, message) => { alert(message); navigate(`/contracts/${id}`); }}
        onReject={reject} onCancel={reset} />
    </>}
  </div>;
};
