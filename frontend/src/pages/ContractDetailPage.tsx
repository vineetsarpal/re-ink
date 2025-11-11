/**
 * ContractDetailPage - Displays detailed information about a single contract.
 */
import React, { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Calendar,
  DollarSign,
  MapPin,
  FileText,
  Users,
  Edit2,
  Save,
  X,
  Trash2,
  Sparkles,
} from 'lucide-react';
import { agentApi, contractApi } from '@/services/api';
import type { AutomatedReviewResponse, ContractWithParties } from '@/types';

export const ContractDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [editedData, setEditedData] = useState<Partial<ContractWithParties>>({});
  const [isGeneratingReview, setIsGeneratingReview] = useState(false);
  const [agentReview, setAgentReview] = useState<AutomatedReviewResponse | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const { data: contract, isLoading, error } = useQuery<ContractWithParties>({
    queryKey: ['contract', id],
    queryFn: () => contractApi.getById(Number(id)),
    enabled: !!id,
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: Partial<ContractWithParties>) =>
      contractApi.update(Number(id), data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contract', id] });
      setIsEditing(false);
      setEditedData({});
      alert('Contract updated successfully!');
    },
    onError: (error: any) => {
      alert(`Failed to update contract: ${error.response?.data?.detail || error.message}`);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => contractApi.delete(Number(id)),
    onSuccess: () => {
      alert('Contract deleted successfully!');
      navigate('/contracts');
    },
    onError: (error: any) => {
      alert(`Failed to delete contract: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleEdit = () => {
    if (contract) {
      setEditedData(contract);
      setIsEditing(true);
    }
  };

  const handleSave = () => {
    if (Object.keys(editedData).length > 0) {
      updateMutation.mutate(editedData);
    }
  };

  const handleCancel = () => {
    setIsEditing(false);
    setEditedData({});
  };

  const handleDelete = () => {
    if (confirm(
      `Are you sure you want to delete contract "${contract?.contract_name}"?\n\n` +
      'This action cannot be undone. The contract will be marked as deleted.'
    )) {
      deleteMutation.mutate();
    }
  };

  const handleGenerateReview = async () => {
    setIsGeneratingReview(true);
    setReviewError(null);
    try {
      const response = await agentApi.runContractReview(contract!.id);
      setAgentReview(response);
    } catch (error: any) {
      console.error('Failed to generate automated review', error);
      const detail =
        error?.response?.data?.detail ??
        error?.message ??
        'Unable to generate AI review. Please try again later.';
      setReviewError(detail);
    } finally {
      setIsGeneratingReview(false);
    }
  };

  const handleFieldChange = (field: keyof ContractWithParties, value: any) => {
    setEditedData(prev => ({ ...prev, [field]: value }));
  };

  // Helper to get current value (edited or original)
  const getValue = (field: keyof ContractWithParties) => {
    if (isEditing && editedData[field] !== undefined) {
      return editedData[field];
    }
    return contract![field];
  };

  // Helper to render editable field
  const renderField = (
    field: keyof ContractWithParties,
    type: string = 'text',
    options?: Array<{ value: string; label: string }>
  ) => {
    const value = getValue(field);

    if (!isEditing) {
      if (type === 'date' && value) {
        return formatDate(String(value));
      }
      if (type === 'number' && value) {
        return value.toString();
      }
      return value || 'N/A';
    }

    if (type === 'select' && options) {
      return (
        <select
          value={String(value || '')}
          onChange={(e) => handleFieldChange(field, e.target.value)}
          className="form-control"
          style={{
            padding: '0.5rem',
            border: '1px solid var(--border-color)',
            borderRadius: '0.375rem',
            width: '100%',
          }}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    }

    if (type === 'textarea') {
      return (
        <textarea
          value={String(value || '')}
          onChange={(e) => handleFieldChange(field, e.target.value)}
          className="form-control"
          rows={3}
          style={{
            padding: '0.5rem',
            border: '1px solid var(--border-color)',
            borderRadius: '0.375rem',
            width: '100%',
            fontFamily: 'inherit',
          }}
        />
      );
    }

    return (
      <input
        type={type}
        value={String(value || '')}
        onChange={(e) =>
          handleFieldChange(
            field,
            type === 'number' ? parseFloat(e.target.value) || null : e.target.value
          )
        }
        className="form-control"
        style={{
          padding: '0.5rem',
          border: '1px solid var(--border-color)',
          borderRadius: '0.375rem',
          width: '100%',
        }}
      />
    );
  };

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading contract details...</p>
      </div>
    );
  }

  if (error || !contract) {
    return (
      <div className="error-container">
        <h2>Contract Not Found</h2>
        <p>The contract you're looking for doesn't exist or couldn't be loaded.</p>
        <button onClick={() => navigate('/contracts')} className="btn btn-primary">
          <ArrowLeft size={16} />
          Back to Contracts
        </button>
      </div>
    );
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  };

  const formatCurrency = (amount?: number, currency = 'USD') => {
    if (!amount) return 'N/A';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency,
    }).format(amount);
  };

  const formatLimit = (value: ContractWithParties['limit_amount'], currency = 'USD') => {
    if (value === null || value === undefined) {
      return 'N/A';
    }

    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return 'N/A';
      }
      if (trimmed.endsWith('%')) {
        return trimmed;
      }
      const numeric = Number(trimmed);
      if (!Number.isNaN(numeric)) {
        return formatCurrency(numeric, currency);
      }
      return trimmed;
    }

    return formatCurrency(value, currency);
  };

  return (
      <div className="contract-detail-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <button onClick={() => navigate('/contracts')} className="btn-back">
            <ArrowLeft size={20} />
            Back to Contracts
          </button>
          <div className="header-content">
            <h1>{contract.contract_name}</h1>
            <div className="badges">
              {!contract.is_active ? (
                <span className="badge badge-inactive">Inactive (Deleted)</span>
              ) : (
                <span className={`badge badge-${contract.status}`}>{contract.status}</span>
              )}
              <span className={`badge badge-${contract.review_status}`}>
                {contract.review_status}
              </span>
            </div>
          </div>
        </div>
        <div className="header-actions" style={{ display: 'flex', gap: '0.75rem' }}>
          {isEditing ? (
            <>
              <button
                onClick={handleSave}
                className="btn btn-primary"
                disabled={updateMutation.isPending}
              >
                <Save size={16} />
                {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
              </button>
              <button
                onClick={handleCancel}
                className="btn btn-secondary"
                disabled={updateMutation.isPending}
              >
                <X size={16} />
                Cancel
              </button>
            </>
          ) : (
            <>
              <button onClick={handleEdit} className="btn btn-secondary">
                <Edit2 size={16} />
                Edit
              </button>
              <button
                onClick={handleDelete}
                className="btn btn-danger"
                disabled={deleteMutation.isPending}
              >
                <Trash2 size={16} />
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </>
          )}
        </div>
      </div>

      <section className="detail-section full-width ai-review-section">
        <div className="detail-section-header">
          <h2>
            <Sparkles size={18} />
            AI Contract Review
          </h2>
          <button
            className="btn btn-secondary"
            onClick={handleGenerateReview}
            disabled={isGeneratingReview}
          >
            <Sparkles size={16} />
            {isGeneratingReview ? 'Generating Review...' : 'Generate AI Review'}
          </button>
        </div>
        <p className="detail-subtitle">
          Generate an automated risk and compliance summary for this contract on demand.
        </p>

        {reviewError && (
          <div className="agent-panel__error" style={{ marginBottom: '1rem' }}>
            {reviewError}
          </div>
        )}

        {agentReview?.analysis ? (
          <div className="agent-panel__body">
            <p className="agent-panel__summary">{agentReview.analysis.assistant_message}</p>

            {agentReview.analysis.risk_flags.length > 0 && (
              <div className="agent-panel__section">
                <h4>Risk Flags</h4>
                <ul className="agent-panel__bullet-list">
                  {agentReview.analysis.risk_flags.map((flag, index) => (
                    <li key={index}>{flag}</li>
                  ))}
                </ul>
              </div>
            )}

            {agentReview.analysis.recommended_actions.length > 0 && (
              <div className="agent-panel__section">
                <h4>Recommended Actions</h4>
                <ul className="agent-panel__bullet-list">
                  {agentReview.analysis.recommended_actions.map((action, index) => (
                    <li key={index}>{action}</li>
                  ))}
                </ul>
              </div>
            )}

            {agentReview.analysis.compliance_notes.length > 0 && (
              <div className="agent-panel__section">
                <h4>Compliance Notes</h4>
                <ul className="agent-panel__bullet-list">
                  {agentReview.analysis.compliance_notes.map((note, index) => (
                    <li key={index}>{note}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="agent-panel__subtitle" style={{ marginTop: '1rem' }}>
            No AI review has been generated yet. Click the button above to request one.
          </p>
        )}
      </section>

      {/* Contract Information Grid */}
      <div className="detail-grid">
        {/* Basic Information */}
        <section className="detail-section">
          <h2><FileText size={20} /> Basic Information</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Contract Number</label>
              <span className="value">{renderField('contract_number')}</span>
            </div>
            <div className="info-item">
              <label>Contract Name</label>
              <span className="value">{renderField('contract_name')}</span>
            </div>
            <div className="info-item">
              <label>Contract Type</label>
              <span className="value">
                {renderField('contract_type', 'select', [
                  { value: '', label: 'Select type' },
                  { value: 'treaty', label: 'Treaty' },
                  { value: 'facultative', label: 'Facultative' },
                  { value: 'proportional', label: 'Proportional' },
                  { value: 'non-proportional', label: 'Non-Proportional' },
                ])}
              </span>
            </div>
            <div className="info-item">
              <label>Contract Sub-Type</label>
              <span className="value">
                {renderField('contract_sub_type', 'select', [
                  { value: '', label: 'Select sub-type' },
                  { value: 'quota_share', label: 'Quota Share' },
                  { value: 'surplus', label: 'Surplus' },
                  { value: 'xol', label: 'XOL (Excess of Loss)' },
                  { value: 'facultative_obligatory', label: 'Facultative Obligatory' },
                  { value: 'facultative_optional', label: 'Facultative Optional' },
                ])}
              </span>
            </div>
            <div className="info-item">
              <label>Contract Nature</label>
              <span className="value">
                {renderField('contract_nature', 'select', [
                  { value: '', label: 'Select nature' },
                  { value: 'proportional', label: 'Proportional' },
                  { value: 'non-proportional', label: 'Non-Proportional' },
                ])}
              </span>
            </div>
            <div className="info-item">
              <label>Line of Business</label>
              <span className="value">{renderField('line_of_business')}</span>
            </div>
            <div className="info-item">
              <label>Status</label>
              <span className="value">
                {renderField('status', 'select', [
                  { value: 'draft', label: 'Draft' },
                  { value: 'pending_review', label: 'Pending Review' },
                  { value: 'active', label: 'Active' },
                  { value: 'expired', label: 'Expired' },
                  { value: 'cancelled', label: 'Cancelled' },
                ])}
              </span>
            </div>
            <div className="info-item">
              <label>Active Status</label>
              <span className="value">
                {isEditing ? (
                  <select
                    value={getValue('is_active') ? 'true' : 'false'}
                    onChange={(e) => handleFieldChange('is_active', e.target.value === 'true')}
                    className="form-control"
                    style={{
                      padding: '0.5rem',
                      border: '1px solid var(--border-color)',
                      borderRadius: '0.375rem',
                      width: '100%',
                    }}
                  >
                    <option value="true">Active (Visible)</option>
                    <option value="false">Inactive (Deleted)</option>
                  </select>
                ) : (
                  getValue('is_active') ? 'Active (Visible)' : 'Inactive (Deleted)'
                )}
              </span>
            </div>
          </div>
        </section>

        {/* Dates */}
        <section className="detail-section">
          <h2><Calendar size={20} /> Important Dates</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Effective Date</label>
              <span className="value">{renderField('effective_date', 'date')}</span>
            </div>
            <div className="info-item">
              <label>Expiration Date</label>
              <span className="value">{renderField('expiration_date', 'date')}</span>
            </div>
            <div className="info-item">
              <label>Inception Date</label>
              <span className="value">{renderField('inception_date', 'date')}</span>
            </div>
            <div className="info-item">
              <label>Created</label>
              <span className="value">{formatDate(contract.created_at)}</span>
            </div>
          </div>
        </section>

        {/* Financial Details */}
        <section className="detail-section">
          <h2><DollarSign size={20} /> Financial Details</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Premium Amount</label>
              <span className="value">
                {isEditing ? renderField('premium_amount', 'number') : formatCurrency(contract.premium_amount, contract.currency)}
              </span>
            </div>
            <div className="info-item">
              <label>Currency</label>
              <span className="value">{renderField('currency')}</span>
            </div>
            <div className="info-item">
              <label>Limit</label>
              <span className="value">
                {isEditing
                  ? renderField('limit_amount')
                  : formatLimit(contract.limit_amount, contract.currency)}
              </span>
            </div>
            <div className="info-item">
              <label>Retention Amount</label>
              <span className="value">
                {isEditing ? renderField('retention_amount', 'number') : formatCurrency(contract.retention_amount, contract.currency)}
              </span>
            </div>
            <div className="info-item">
              <label>Commission Rate (%)</label>
              <span className="value">
                {isEditing ? renderField('commission_rate', 'number') : (contract.commission_rate ? `${contract.commission_rate}%` : 'N/A')}
              </span>
            </div>
          </div>
        </section>

        {/* Coverage Details */}
        <section className="detail-section">
          <h2><MapPin size={20} /> Coverage Details</h2>
          <div className="info-grid">
            <div className="info-item full-width">
              <label>Coverage Territory</label>
              <span className="value">{renderField('coverage_territory')}</span>
            </div>
            <div className="info-item full-width">
              <label>Coverage Description</label>
              {isEditing ? (
                <span className="value">{renderField('coverage_description', 'textarea')}</span>
              ) : (
                <p className="value text-block">
                  {contract.coverage_description || 'No description provided'}
                </p>
              )}
            </div>
          </div>
        </section>

        {/* Parties */}
        <section className="detail-section">
          <h2><Users size={20} /> Associated Parties ({contract.parties?.length || 0})</h2>
          {contract.parties && contract.parties.length > 0 ? (
            <div className="parties-list">
              {contract.parties.map((party) => (
                <Link
                  key={party.id}
                  to={`/parties/${party.id}`}
                  className="party-card-link"
                >
                  <div className="party-card">
                    <div className="party-header">
                      <h4>{party.name}</h4>
                      <span className={`badge badge-${party.party_type}`}>
                        {party.party_type}
                      </span>
                    </div>
                    <div className="party-info">
                      {party.email && (
                        <span className="info-line">📧 {party.email}</span>
                      )}
                      {party.phone && (
                        <span className="info-line">📞 {party.phone}</span>
                      )}
                      {party.city && party.country && (
                        <span className="info-line">
                          📍 {party.city}, {party.country}
                        </span>
                      )}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="no-data">No parties associated with this contract</p>
          )}
        </section>

        {/* Terms and Provisions */}
        {(contract.terms_and_conditions || contract.special_provisions) && (
          <section className="detail-section full-width">
            <h2><FileText size={20} /> Terms and Provisions</h2>
            {contract.terms_and_conditions && (
              <div className="info-item">
                <label>Terms and Conditions</label>
                <p className="value text-block">{contract.terms_and_conditions}</p>
              </div>
            )}
            {contract.special_provisions && (
              <div className="info-item">
                <label>Special Provisions</label>
                <p className="value text-block">{contract.special_provisions}</p>
              </div>
            )}
          </section>
        )}

        {/* Extraction Metadata */}
        {!contract.is_manually_created && (
          <section className="detail-section full-width">
            <h2>Extraction Metadata</h2>
            <div className="info-grid">
              <div className="info-item">
                <label>Source Document</label>
                <span className="value">
                  {contract.source_document_name || 'N/A'}
                </span>
              </div>
              <div className="info-item">
                <label>Extraction Confidence</label>
                <span className="value">
                  {contract.extraction_confidence
                    ? `${(contract.extraction_confidence * 100).toFixed(1)}%`
                    : 'N/A'}
                </span>
              </div>
              <div className="info-item">
                <label>Review Status</label>
                <span className="value">{contract.review_status}</span>
              </div>
            </div>
          </section>
        )}

        {/* Notes */}
        {contract.notes && (
          <section className="detail-section full-width">
            <h2>Notes</h2>
            <p className="value text-block">{contract.notes}</p>
          </section>
        )}
      </div>
    </div>
  );
};
