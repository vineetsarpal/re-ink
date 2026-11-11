import { extractionErrorMessage } from '@/types/extractionErrors';
import { PREPARATION_FAILED, TRIAL_CAPACITY_UNAVAILABLE } from '@/types/extractionErrors';
/**
 * ExtractionStatus component for displaying document extraction progress.
 * Polls the backend for status updates and displays results when complete.
 */
import React, { useEffect, useState } from 'react';
import { CheckCircle, XCircle, Loader, Clock } from 'lucide-react';
import { documentApi } from '@/services/api';
import type { DocumentExtractionStatus } from '@/types';

interface ExtractionStatusProps {
  jobId: string;
  onComplete?: (status: DocumentExtractionStatus) => void;
  onError?: (error: string) => void;
  allowRetry?: boolean;
  trialEligible?: boolean;
  hasCustomerKey?: boolean;
}

export const ExtractionStatus: React.FC<ExtractionStatusProps> = ({
  jobId,
  onComplete,
  onError,
  allowRetry = false,
  trialEligible = true,
  hasCustomerKey = false,
}) => {
  const [status, setStatus] = useState<DocumentExtractionStatus | null>(null);
  const [isPolling, setIsPolling] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval>;

    const pollStatus = async () => {
      try {
        const response = await documentApi.getStatus(jobId);
        setStatus(response);

        // Stop polling if job is complete or failed
        if (response.status === 'completed') {
          setIsPolling(false);
          onComplete?.(response);
        } else if (response.status === 'failed' || response.status === 'timed_out') {
          setIsPolling(false);
          if (!allowRetry) onError?.(response.message || 'Extraction failed');
        }
      } catch (err: any) {
        console.error('Error polling status:', err);
        onError?.(extractionErrorMessage(err.response?.data?.detail, 'Failed to get status'));
        setIsPolling(false);
      }
    };

    // Initial poll
    pollStatus();

    // Set up polling interval if still processing
    if (isPolling) {
      intervalId = setInterval(pollStatus, 3000); // Poll every 3 seconds
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [jobId, isPolling, onComplete, onError, allowRetry]);

  const getStatusIcon = () => {
    if (!status) return <Clock size={24} />;

    switch (status.status) {
      case 'completed':
        return <CheckCircle size={24} className="text-success" />;
      case 'failed':
      case 'timed_out':
        return <XCircle size={24} className="text-error" />;
      case 'processing':
      case 'submitted_to_ai':
        return <Loader size={24} className="spinner" />;
      default:
        return <Clock size={24} />;
    }
  };

  const getStatusMessage = () => {
    if (!status) return 'Checking status...';

    switch (status.status) {
      case 'completed':
        return 'Extraction completed successfully!';
      case 'failed':
      case 'timed_out':
        if (status.error_code === TRIAL_CAPACITY_UNAVAILABLE) {
          return 'Free extractions are temporarily unavailable. Add a LandingAI key or try again later.';
        }
        if (status.error_code === PREPARATION_FAILED) {
          return 'We could not prepare your document for extraction. Please try again later.';
        }
        return status.message || 'Extraction failed';
      case 'processing':
        return 'Processing document...';
      case 'submitted_to_ai':
        return 'Document submitted for AI extraction...';
      default:
        return status.message || 'Processing...';
    }
  };

  return (
    <div className="extraction-status">
      {!trialEligible && !hasCustomerKey && <p role="status">Free extractions are not available for this organization; add a LandingAI key.</p>}
      <div className="status-header">
        {getStatusIcon()}
        <h3>{getStatusMessage()}</h3>
      </div>

      {allowRetry && status?.can_retry === true && (
        <div>
          {retryError && <p role="alert">{retryError}</p>}
          <button type="button" className="btn btn-primary" disabled={retrying} onClick={async () => {
            setRetrying(true);
            setRetryError(null);
            try {
              await documentApi.retry(jobId);
              setStatus(null);
              setIsPolling(true);
            } catch (err: any) {
              setRetryError(extractionErrorMessage(err.response?.data?.detail, 'Unable to retry extraction'));
            } finally {
              setRetrying(false);
            }
          }}>{retrying ? 'Retrying...' : 'Retry extraction'}</button>
        </div>
      )}

      {status?.result && status.status === 'completed' && (
        <div className="status-details">
          <p className="text-muted">
            Confidence Score:{' '}
            {status.result.confidence_score
              ? `${(status.result.confidence_score * 100).toFixed(1)}%`
              : 'N/A'}
          </p>
          <p className="text-muted">Job ID: {jobId}</p>
        </div>
      )}

      {isPolling && (
        <div className="polling-indicator">
          <div className="progress-bar">
            <div className="progress-bar-fill"></div>
          </div>
          <p className="text-muted">Checking for updates...</p>
        </div>
      )}
    </div>
  );
};
