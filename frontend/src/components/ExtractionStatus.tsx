/** Poll active workflow jobs; terminal states require explicit Retry. */
import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle, XCircle, Loader, Clock } from 'lucide-react';
import { documentApi } from '@/services/api';
import type { DocumentExtractionStatus, DocumentUploadResponse } from '@/types';
interface ExtractionStatusProps {
  jobId: string;
  onComplete?: (status: DocumentExtractionStatus) => void;
  retryAvailable?: boolean;
  onRetry?: (response: DocumentUploadResponse) => void;
}
export const ExtractionStatus: React.FC<ExtractionStatusProps> = ({ jobId, onComplete, retryAvailable, onRetry }) => {
  const [status, setStatus] = useState<DocumentExtractionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [generation, setGeneration] = useState(0);
  const complete = useRef(onComplete); complete.current = onComplete;
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setStatus(null); setError(null);
    const poll = async () => {
      try {
        const response = await documentApi.getStatus(jobId);
        if (cancelled) return;
        setStatus(response);
        if (response.status === 'completed') complete.current?.(response);
        else if (response.status === 'queued' || response.status === 'processing') timer = setTimeout(poll, 3000);
      } catch { if (!cancelled) setError('Unable to retrieve extraction status. Refresh the page to check again.'); }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId, generation]);
  const retry = async () => {
    setRetrying(true); setError(null);
    try { const response = await documentApi.retry(jobId); onRetry?.(response); setGeneration(n => n + 1); }
    catch { setError('Retry was not accepted. Check availability and permissions, then try again.'); }
    finally { setRetrying(false); }
  };
  const failed = status?.status === 'failed' || status?.status === 'timed_out';
  const active = !error && (!status || status.status === 'queued' || status.status === 'processing');
  return <div className="extraction-status">
    <div className="status-header">
      {failed ? <XCircle size={24} /> : status?.status === 'completed' ? <CheckCircle size={24} /> : active ? <Loader size={24} className="spinner" /> : <Clock size={24} />}
      <h3>{status?.status === 'queued' ? 'Queued for extraction' : status?.status === 'timed_out' ? 'Extraction timed out' : status?.status === 'failed' ? 'Extraction failed' : status?.status === 'completed' ? 'Extraction completed' : 'Processing document…'}</h3>
    </div>
    {status?.message && <p>{status.message}</p>}
    {error && <p role="alert">{error}</p>}
    {active && <p>Checking for updates…</p>}
    {failed && retryAvailable && <button className="btn btn-primary" disabled={retrying} onClick={retry}>{retrying ? 'Queuing…' : 'Retry extraction'}</button>}
    <p className="text-muted">Job ID: {jobId}</p>
  </div>;
};
