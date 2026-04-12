/**
 * FileUpload component for uploading reinsurance contract documents.
 * Supports PDF and DOCX formats with drag-and-drop functionality.
 */
import React, { useState, useCallback } from 'react';
import { Upload, FileText, AlertCircle, KeyRound, FileDown } from 'lucide-react';
import { documentApi } from '@/services/api';
import type { DocumentUploadResponse } from '@/types';

const SAMPLE_DOCUMENTS = [
  {
    name: '100% Quota Share Reinsurance Contract',
    filename: 'quota-share-reinsurance-contract.pdf',
    url: '/samples/quota-share-reinsurance-contract.pdf',
    description: 'Vesta Fire Insurance Corp & Affirmative Insurance — proportional treaty, 4 pages',
    pages: 4,
    type: 'Quota Share',
  },
  {
    name: 'Excess of Loss Reinsurance Agreement',
    filename: 'excess-of-loss-reinsurance-agreement.pdf',
    url: '/samples/excess-of-loss-reinsurance-agreement.pdf',
    description: 'Republic Insurance & Winterthur Swiss — non-proportional XOL, 6 pages',
    pages: 6,
    type: 'XOL',
  },
];

interface FileUploadProps {
  onUploadSuccess?: (response: DocumentUploadResponse) => void;
  onUploadError?: (error: string) => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({
  onUploadSuccess,
  onUploadError,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);

  const allowedTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ];

  const validateFile = (file: File): boolean => {
    if (!allowedTypes.includes(file.type)) {
      setError('Only PDF and DOCX files are supported');
      return false;
    }

    // 50MB limit
    if (file.size > 50 * 1024 * 1024) {
      setError('File size must be less than 50MB');
      return false;
    }

    return true;
  };

  const handleFileSelect = useCallback((file: File) => {
    setError(null);
    if (validateFile(file)) {
      setSelectedFile(file);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFileSelect(files[0]);
    }
  }, [handleFileSelect]);

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileSelect(files[0]);
    }
  };

  const handleSampleSelect = async (sample: typeof SAMPLE_DOCUMENTS[number]) => {
    setError(null);
    try {
      const response = await fetch(sample.url);
      if (!response.ok) throw new Error('Failed to fetch sample document');
      const blob = await response.blob();
      const file = new File([blob], sample.filename, { type: 'application/pdf' });
      setSelectedFile(file);
    } catch {
      setError('Failed to load sample document. Please try again.');
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setError(null);

    try {
      const response = await documentApi.upload(selectedFile, apiKey.trim() || undefined);
      onUploadSuccess?.(response);
      setSelectedFile(null);
      setApiKey('');
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to upload file';
      setError(errorMessage);
      onUploadError?.(errorMessage);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="file-upload-container">
      {/* API Key input */}
      <div className="api-key-section">
        <label className="api-key-label" htmlFor="landingai-api-key">
          <KeyRound size={16} />
          LandingAI API Key
        </label>
        <div className="api-key-input-wrapper">
          <input
            id="landingai-api-key"
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter your LandingAI API key"
            className="api-key-input"
            disabled={isUploading}
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
            data-form-type="other"
          />
          <button
            type="button"
            className="api-key-toggle"
            onClick={() => setShowKey((v) => !v)}
            aria-label={showKey ? 'Hide API key' : 'Show API key'}
          >
            {showKey ? 'Hide' : 'Show'}
          </button>
        </div>
        <p className="api-key-hint">
          Your key is sent directly to the server for this request only and is never stored.{' '}
          <a
            href="https://docs.landing.ai/ade/agentic-api-key"
            target="_blank"
            rel="noopener noreferrer"
          >
            Get your LandingAI API key →
          </a>
        </p>
      </div>

      <div
        className={`upload-dropzone ${isDragging ? 'dragging' : ''} ${
          selectedFile ? 'has-file' : ''
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {selectedFile ? (
          <div className="selected-file">
            <FileText size={48} />
            <p className="file-name">{selectedFile.name}</p>
            <p className="file-size">
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        ) : (
          <div className="upload-prompt">
            <Upload size={48} />
            <p className="prompt-text">
              Drag and drop your contract document here, or click to browse
            </p>
            <p className="file-types">Supported formats: PDF, DOCX (Max 50MB)</p>
          </div>
        )}

        <input
          type="file"
          accept=".pdf,.docx"
          onChange={handleFileInputChange}
          className="file-input"
          disabled={isUploading}
        />
      </div>

      {error && (
        <div className="error-message">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      <div className="upload-actions">
        {selectedFile && (
          <>
            <button
              onClick={() => setSelectedFile(null)}
              disabled={isUploading}
              className="btn btn-secondary"
            >
              Clear
            </button>
            <button
              onClick={handleUpload}
              disabled={isUploading}
              className="btn btn-primary"
            >
              {isUploading ? 'Uploading...' : 'Upload & Process'}
            </button>
          </>
        )}
      </div>

      {!selectedFile && (
        <div className="sample-documents">
          <p className="sample-documents__label">Or try a sample document</p>
          <div className="sample-documents__grid">
            {SAMPLE_DOCUMENTS.map((sample) => (
              <button
                key={sample.filename}
                className="sample-card"
                onClick={() => handleSampleSelect(sample)}
                disabled={isUploading}
              >
                <FileDown size={24} className="sample-card__icon" />
                <div className="sample-card__content">
                  <span className="sample-card__name">{sample.name}</span>
                  <span className="sample-card__meta">{sample.description}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
