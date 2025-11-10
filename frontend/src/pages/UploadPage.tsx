/**
 * UploadPage - Full workflow for uploading and processing documents.
 */
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { FileUpload } from '@/components/FileUpload';
import { ExtractionStatus } from '@/components/ExtractionStatus';
import { ReviewForm } from '@/components/ReviewForm';
import { documentApi } from '@/services/api';
import type { DocumentUploadResponse, DocumentExtractionStatus } from '@/types';

type WorkflowStep = 'upload' | 'processing' | 'review';

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState<WorkflowStep>('upload');
  const [uploadResponse, setUploadResponse] = useState<DocumentUploadResponse | null>(
    null
  );
  const [extractionStatus, setExtractionStatus] =
    useState<DocumentExtractionStatus | null>(null);

  const handleUploadSuccess = (response: DocumentUploadResponse) => {
    setUploadResponse(response);
    setCurrentStep('processing');
  };

  const handleExtractionComplete = (status: DocumentExtractionStatus) => {
    setExtractionStatus(status);
    if (status.result) {
      setCurrentStep('review');
    }
  };

  const handleApprove = (contractId: number, partyIds: number[]) => {
    // Success message is now shown in ReviewForm
    // Navigate to the newly created contract's detail page
    navigate(`/contracts/${contractId}`);
  };

  const handleReject = async () => {
    if (uploadResponse) {
      try {
        await documentApi.delete(uploadResponse.job_id);
        alert('Extraction rejected and document deleted');
        setCurrentStep('upload');
        setUploadResponse(null);
        setExtractionStatus(null);
      } catch (err) {
        console.error('Error rejecting:', err);
      }
    }
  };

  const handleCancel = () => {
    if (confirm('Are you sure you want to cancel? This will discard all progress.')) {
      setCurrentStep('upload');
      setUploadResponse(null);
      setExtractionStatus(null);
    }
  };

  return (
    <div className="upload-page">
      <div className="page-header">
        <button onClick={() => navigate('/dashboard')} className="btn-back">
          <ArrowLeft size={20} />
          Back to Dashboard
        </button>
        <h1>Upload Contract Document</h1>
      </div>

      {/* Progress Steps */}
      <div className="workflow-steps">
        <div className={`step ${currentStep === 'upload' ? 'active' : ''} ${
          currentStep !== 'upload' ? 'completed' : ''
        }`}>
          <div className="step-number">1</div>
          <div className="step-label">Upload</div>
        </div>
        <div className="step-divider"></div>
        <div className={`step ${currentStep === 'processing' ? 'active' : ''} ${
          currentStep === 'review' ? 'completed' : ''
        }`}>
          <div className="step-number">2</div>
          <div className="step-label">Processing</div>
        </div>
        <div className="step-divider"></div>
        <div className={`step ${currentStep === 'review' ? 'active' : ''}`}>
          <div className="step-number">3</div>
          <div className="step-label">Review</div>
        </div>
      </div>

      {/* Step Content */}
      <div className="step-content">
        {currentStep === 'upload' && (
          <FileUpload
            onUploadSuccess={handleUploadSuccess}
            onUploadError={(error) => alert(error)}
          />
        )}

        {currentStep === 'processing' && uploadResponse && (
          <ExtractionStatus
            jobId={uploadResponse.job_id}
            onComplete={handleExtractionComplete}
            onError={(error) => {
              alert(error);
              setCurrentStep('upload');
            }}
          />
        )}

        {currentStep === 'review' && extractionStatus?.result && (
          <ReviewForm
            extractionResult={extractionStatus.result}
            onApprove={handleApprove}
            onReject={handleReject}
            onCancel={handleCancel}
          />
        )}
      </div>
    </div>
  );
};
