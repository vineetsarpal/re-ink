/**
 * UploadPage - Full workflow for uploading and processing documents.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { FileUpload } from '@/components/FileUpload';
import { ExtractionStatus } from '@/components/ExtractionStatus';
import { ReviewForm } from '@/components/ReviewForm';
import { agentApi, documentApi } from '@/services/api';
import type {
  DocumentUploadResponse,
  DocumentExtractionStatus,
  GuidedIntakeResponse,
} from '@/types';

type WorkflowStep = 'upload' | 'processing' | 'review';

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState<WorkflowStep>('upload');
  const [uploadResponse, setUploadResponse] = useState<DocumentUploadResponse | null>(
    null
  );
  const [extractionStatus, setExtractionStatus] =
    useState<DocumentExtractionStatus | null>(null);
  const [isSeedingMock, setIsSeedingMock] = useState(false);
  const [intakeAgent, setIntakeAgent] = useState<GuidedIntakeResponse | null>(null);
  const [isIntakeLoading, setIsIntakeLoading] = useState(false);
  const [intakeError, setIntakeError] = useState<string | null>(null);
  const lastAgentJobId = useRef<string | null>(null);

  const handleUploadSuccess = (response: DocumentUploadResponse) => {
    setUploadResponse(response);
    setCurrentStep('processing');
    setIntakeAgent(null);
    setIntakeError(null);
  };

  const handleExtractionComplete = (status: DocumentExtractionStatus) => {
    setExtractionStatus(status);
    if (status.result) {
      setCurrentStep('review');
    }
  };

  const handleReject = async () => {
    if (uploadResponse) {
      try {
        await documentApi.delete(uploadResponse.job_id);
        alert('Extraction rejected and document deleted');
        setCurrentStep('upload');
        setUploadResponse(null);
        setExtractionStatus(null);
        setIntakeAgent(null);
        setIntakeError(null);
        lastAgentJobId.current = null;
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
      setIntakeAgent(null);
      setIntakeError(null);
      lastAgentJobId.current = null;
    }
  };

  const handleSeedMock = async () => {
    try {
      setIsSeedingMock(true);
      const status = await documentApi.seedMockJob();
      const filename =
        status.result?.extraction_metadata?.filename ?? 'mock_contract.pdf';
      const mockUpload: DocumentUploadResponse = {
        job_id: status.job_id,
        filename,
        file_path: `/mock/${status.job_id}.pdf`,
        message: status.message ?? 'Mock extraction job created.',
        status: status.status,
      };
      setUploadResponse(mockUpload);
      setExtractionStatus(status);
      setCurrentStep(status.result ? 'review' : 'processing');
      setIntakeAgent(null);
      setIntakeError(null);
      lastAgentJobId.current = null;
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ?? 'Failed to create mock extraction job.';
      alert(message);
    } finally {
      setIsSeedingMock(false);
    }
  };

  const fetchIntakeAgent = async () => {
    const jobId = uploadResponse?.job_id;
    if (!jobId) return;
    setIsIntakeLoading(true);
    setIntakeError(null);
    try {
      const response = await agentApi.runIntake(jobId);
      setIntakeAgent(response);
      lastAgentJobId.current = jobId;
    } catch (error: any) {
      console.error('Failed to fetch guided intake agent response', error);
      const message =
        error?.response?.data?.detail ??
        error?.message ??
        'Unable to retrieve AI intake guidance.';
      setIntakeError(message);
    } finally {
      setIsIntakeLoading(false);
    }
  };

  useEffect(() => {
    if (
      currentStep === 'review' &&
      uploadResponse?.job_id &&
      extractionStatus?.result &&
      lastAgentJobId.current !== uploadResponse.job_id
    ) {
      fetchIntakeAgent();
    }
  }, [currentStep, uploadResponse?.job_id, extractionStatus?.result]);

  const handleApprove = (
    contractId: number,
    partyIds: number[],
    approvalMessage: string
  ) => {
    alert(
      `✅ Success!\n\n${approvalMessage}\n\n` +
        `Contract ID: ${contractId}\n` +
        `Parties: ${partyIds.length > 0 ? partyIds.join(', ') : 'None'}`
    );
    navigate(`/contracts/${contractId}`);
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
          <>
            <FileUpload
              onUploadSuccess={handleUploadSuccess}
              onUploadError={(error) => alert(error)}
            />
            <div className="mock-upload">
              <p className="mock-upload__description">
                Seed a fully-populated mock extraction to exercise
                the AI agent flows while still using your OpenAI API key.
              </p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleSeedMock}
                disabled={isSeedingMock}
              >
                {isSeedingMock ? 'Seeding Mock Extraction...' : 'Use Sample Extraction'}
              </button>
            </div>
          </>
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
            agentAnalysis={intakeAgent}
            agentLoading={isIntakeLoading}
            agentError={intakeError}
            onRefreshAgent={fetchIntakeAgent}
          />
        )}
      </div>
    </div>
  );
};
