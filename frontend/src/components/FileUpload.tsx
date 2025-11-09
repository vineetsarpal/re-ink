/**
 * FileUpload component for uploading reinsurance contract documents.
 * Supports PDF and DOCX formats with drag-and-drop functionality.
 */
import React, { useState, useCallback } from 'react';
import { Upload, FileText, AlertCircle } from 'lucide-react';
import { documentApi } from '@/services/api';
import type { DocumentUploadResponse } from '@/types';

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

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setError(null);

    try {
      const response = await documentApi.upload(selectedFile);
      onUploadSuccess?.(response);
      setSelectedFile(null);
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
    </div>
  );
};
