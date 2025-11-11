/**
 * ReviewForm component for reviewing and editing extracted contract data.
 * Allows users to verify AI-extracted information before creating records.
 */
import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Save, X, Edit, RefreshCw } from 'lucide-react';
import type {
  ExtractionResult,
  ReviewData,
  GuidedIntakeResponse,
} from '@/types';
import { reviewApi } from '@/services/api';

interface ReviewFormProps {
  extractionResult: ExtractionResult;
  agentAnalysis?: GuidedIntakeResponse | null;
  agentLoading?: boolean;
  agentError?: string | null;
  onRefreshAgent?: () => void;
  onApprove?: (contractId: number, partyIds: number[], approvalMessage: string) => Promise<void> | void;
  onReject?: () => void;
  onCancel?: () => void;
}

export const ReviewForm: React.FC<ReviewFormProps> = ({
  extractionResult,
  agentAnalysis,
  agentLoading = false,
  agentError = null,
  onRefreshAgent,
  onApprove,
  onReject,
  onCancel,
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const { register, handleSubmit, formState: { errors }, getValues } = useForm({
    defaultValues: {
      contract: extractionResult.contract_data,
      parties: extractionResult.parties_data,
    },
  });

  const onSubmit = async (data: any) => {
    setIsSubmitting(true);

    try {
      // Handle empty or undefined parties array
      const parties = data.parties || [];

      // Warn user if no parties were extracted
      if (parties.length === 0) {
        const proceed = confirm(
          'Warning: No parties were extracted from the document.\n\n' +
          'The contract will be created without any associated parties.\n' +
          'You can add parties later from the Parties page.\n\n' +
          'Do you want to continue?'
        );
        if (!proceed) {
          setIsSubmitting(false);
          return;
        }
      }

      // Clean data: convert empty strings to null for optional fields
      const cleanObject = (obj: any): any => {
        const cleaned: any = {};
        for (const key in obj) {
          const value = obj[key];
          // Convert empty strings to null, keep other falsy values as-is
          if (value === '') {
            cleaned[key] = null;
          } else if (value !== undefined) {
            cleaned[key] = value;
          }
        }
        return cleaned;
      };

      const cleanedContract = cleanObject(data.contract);
      const cleanedParties = parties.map((party: any) => cleanObject(party));

      const reviewData: ReviewData = {
        contract: cleanedContract,
        parties: cleanedParties,
        create_new_parties: true,
      };

      const response = await reviewApi.approve(reviewData);
      let approvalHandled = false;
      if (onApprove) {
        await onApprove(response.contract_id, response.party_ids, response.message);
        approvalHandled = true;
      }

      if (!approvalHandled) {
        alert(
          `✅ Success!\n\n${response.message}\n\n` +
          `Contract ID: ${response.contract_id}\n` +
          `Parties: ${
            response.party_ids.length > 0 ? response.party_ids.join(', ') : 'None'
          }`
        );
      }
    } catch (err: any) {
      console.error('Error approving data:', err);
      console.error('Error response data:', err.response?.data);
      console.error('Error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status
      });

      // Handle duplicate contract error (409)
      if (err.response?.status === 409) {
        const detail = err.response.data.detail;
        if (detail?.error === 'duplicate_contract') {
          const message =
            `⚠️ Duplicate Contract Detected\n\n` +
            `Contract Number: ${detail.contract_number}\n\n` +
            `This contract already exists in the system (ID: ${detail.existing_contract_id}).\n\n` +
            `You can view it on the Contracts page.`;

          alert(message);

          // Optionally navigate to contracts page
          if (confirm('Would you like to view the Contracts page?')) {
            onCancel?.();
            // Note: Navigation will happen via the cancel callback
          }
          setIsSubmitting(false);
          return;
        }
      }

      // Better error message display for other errors
      let errorMessage = 'Failed to approve data';
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
          // Pydantic validation errors
          errorMessage = 'Validation errors:\n' + err.response.data.detail.map((e: any) =>
            `- ${e.loc?.join('.')} : ${e.msg}`
          ).join('\n');
        } else if (typeof err.response.data.detail === 'string') {
          errorMessage = err.response.data.detail;
        } else if (err.response.data.detail.message) {
          errorMessage = err.response.data.detail.message;
        }
      }

      alert(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = () => {
    if (confirm('Are you sure you want to reject this extraction?')) {
      onReject?.();
    }
  };

  return (
    <div className="review-form">
      <div className="form-header">
        <h2>Review Extracted Data</h2>
        <div className="header-actions">
          <button
            onClick={() => setIsEditing(!isEditing)}
            className="btn btn-secondary header-actions__toggle"
          >
            <Edit size={16} />
            {isEditing ? 'View Mode' : 'Edit Mode'}
          </button>
        </div>
      </div>

      <form onSubmit={(e) => {
        handleSubmit(
          onSubmit,
          (validationErrors) => {
            const errorMessages: string[] = [];

            if (validationErrors.contract) {
              Object.keys(validationErrors.contract).forEach(field => {
                errorMessages.push(`Contract ${field}: ${validationErrors.contract[field]?.message || 'Required'}`);
              });
            }

            if (validationErrors.parties) {
              Object.keys(validationErrors.parties).forEach(index => {
                const partyErrors = validationErrors.parties[index];
                Object.keys(partyErrors).forEach(field => {
                  errorMessages.push(`Party ${parseInt(index, 10) + 1} ${field}: ${partyErrors[field]?.message || 'Required'}`);
                });
              });
            }

            alert('Please fix form validation errors:\n\n' + errorMessages.join('\n'));
          }
        )(e);
      }}>
        {/* Contract Information Section */}
        <section className="form-section">
          <h3>Contract Information</h3>

          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="contract_number">Contract Number *</label>
              <input
                id="contract_number"
                {...register('contract.contract_number', { required: true })}
                disabled={!isEditing}
                className={errors.contract?.contract_number ? 'error' : ''}
              />
              {errors.contract?.contract_number && (
                <span className="field-error">Required field</span>
              )}
            </div>

            <div className="form-field">
              <label htmlFor="contract_name">Contract Name *</label>
              <input
                id="contract_name"
                {...register('contract.contract_name', { required: true })}
                disabled={!isEditing}
                className={errors.contract?.contract_name ? 'error' : ''}
              />
            </div>

            <div className="form-field">
              <label htmlFor="contract_type">Contract Type</label>
              <input
                id="contract_type"
                {...register('contract.contract_type')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="contract_sub_type">Contract Sub-Type</label>
              <input
                id="contract_sub_type"
                {...register('contract.contract_sub_type')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="contract_nature">Contract Nature</label>
              <input
                id="contract_nature"
                {...register('contract.contract_nature')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="effective_date">Effective Date *</label>
              <input
                type="date"
                id="effective_date"
                {...register('contract.effective_date', { required: true })}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="expiration_date">Expiration Date *</label>
              <input
                type="date"
                id="expiration_date"
                {...register('contract.expiration_date', { required: true })}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="premium_amount">Premium</label>
              <input
                id="premium_amount"
                {...register('contract.premium_amount')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="currency">Currency</label>
              <input
                id="currency"
                {...register('contract.currency')}
                disabled={!isEditing}
                defaultValue="USD"
              />
            </div>

            <div className="form-field">
              <label htmlFor="limit_amount">Limit</label>
              <input
                id="limit_amount"
                {...register('contract.limit_amount')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="retention_amount">Retention/Deductible Amount</label>
              <input
                id="retention_amount"
                {...register('contract.retention_amount')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="commission_rate">Commission Rate (%)</label>
              <input
                id="commission_rate"
                {...register('contract.commission_rate')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field">
              <label htmlFor="line_of_business">Line of Business</label>
              <input
                id="line_of_business"
                {...register('contract.line_of_business')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field full-width">
              <label htmlFor="coverage_territory">Coverage Territory</label>
              <input
                id="coverage_territory"
                {...register('contract.coverage_territory')}
                disabled={!isEditing}
              />
            </div>

            <div className="form-field full-width">
              <label htmlFor="coverage_description">Coverage Description</label>
              <textarea
                id="coverage_description"
                rows={3}
                {...register('contract.coverage_description')}
                disabled={!isEditing}
              />
            </div>
          </div>
        </section>

        {/* Parties Section */}
        <section className="form-section">
          <h3>Parties ({extractionResult.parties_data?.length || 0})</h3>

          {(!extractionResult.parties_data || extractionResult.parties_data.length === 0) && (
            <div className="no-parties-message" style={{
              padding: '20px',
              backgroundColor: '#fff3cd',
              border: '1px solid #ffc107',
              borderRadius: '4px',
              marginBottom: '20px'
            }}>
              <p style={{ margin: 0, color: '#856404' }}>
                ⚠️ No parties were extracted from the document.
                The contract will be created without associated parties.
                You can add parties later.
              </p>
            </div>
          )}

          {extractionResult.parties_data?.map((party, index) => (
            <div key={index} className="party-card">
              <h4>
                {party.name || `Party ${index + 1}`} {party.party_type && `(${party.party_type})`}
              </h4>

              <div className="form-grid">
                <div className="form-field">
                  <label>Name *</label>
                  <input
                    {...register(`parties.${index}.name`, { required: true })}
                    disabled={!isEditing}
                  />
                </div>

                <div className="form-field">
                  <label>Party Type *</label>
                  <select
                    {...register(`parties.${index}.party_type`, { required: true })}
                    disabled={!isEditing}
                  >
                    <option value="cedant">Cedant</option>
                    <option value="reinsurer">Reinsurer</option>
                    <option value="broker">Broker</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                <div className="form-field">
                  <label>Email</label>
                  <input
                    type="email"
                    {...register(`parties.${index}.email`)}
                    disabled={!isEditing}
                  />
                </div>

                <div className="form-field">
                  <label>Phone</label>
                  <input
                    {...register(`parties.${index}.phone`)}
                    disabled={!isEditing}
                  />
                </div>

                <div className="form-field">
                  <label>Registration Number</label>
                  <input
                    {...register(`parties.${index}.registration_number`)}
                    disabled={!isEditing}
                  />
                </div>
              </div>
            </div>
          ))}
        </section>

        {/* Confidence Score Display */}
        {extractionResult.confidence_score && (
          <div className="confidence-indicator">
            <label>AI Confidence Score:</label>
            <div className="confidence-bar">
              <div
                className="confidence-fill"
                style={{ width: `${extractionResult.confidence_score * 100}%` }}
              />
            </div>
            <span>{(extractionResult.confidence_score * 100).toFixed(1)}%</span>
          </div>
        )}

        <aside className="agent-panel">
          <div className="agent-panel__header">
            <div>
              <h3>AI Intake Guidance</h3>
              <p className="agent-panel__subtitle">
                Insights generated by the guided intake agent to assist your review.
              </p>
            </div>
            <div className="agent-panel__actions">
              {agentAnalysis?.analysis?.confidence !== undefined && (
                <span className="agent-panel__confidence">
                  Confidence: {(agentAnalysis.analysis.confidence * 100).toFixed(0)}%
                </span>
              )}
              {onRefreshAgent && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={onRefreshAgent}
                  disabled={agentLoading}
                >
                  <RefreshCw size={16} />
                  {agentLoading ? 'Refreshing...' : 'Refresh Insights'}
                </button>
              )}
            </div>
          </div>
          <div className="agent-panel__body">
            {agentLoading && <p>Generating AI insights for this extraction…</p>}
            {!agentLoading && agentError && (
              <p className="agent-panel__error">{agentError}</p>
            )}
            {!agentLoading && !agentError && agentAnalysis?.analysis && (
              <div className="agent-panel__insights">
                <p className="agent-panel__summary">{agentAnalysis.analysis.assistant_message}</p>
                {agentAnalysis.analysis.missing_fields.length > 0 && (
                  <div className="agent-panel__section">
                    <h4>Missing or Low-Confidence Fields</h4>
                    <ul className="agent-panel__list">
                      {agentAnalysis.analysis.missing_fields.map((field) => (
                        <li key={field} className="agent-panel__badge">
                          {field.replace(/_/g, ' ')}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {agentAnalysis.analysis.clarifying_questions.length > 0 && (
                  <div className="agent-panel__section">
                    <h4>Clarifying Questions</h4>
                    <ul className="agent-panel__bullet-list">
                      {agentAnalysis.analysis.clarifying_questions.map((question, index) => (
                        <li key={index}>{question}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {agentAnalysis.analysis.recommended_next_steps.length > 0 && (
                  <div className="agent-panel__section">
                    <h4>Recommended Next Steps</h4>
                    <ul className="agent-panel__bullet-list">
                      {agentAnalysis.analysis.recommended_next_steps.map((step, index) => (
                        <li key={index}>{step}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {!agentLoading && !agentError && !agentAnalysis?.analysis && (
              <p>No AI insights available yet. Refresh once the extraction is complete.</p>
            )}
          </div>
        </aside>

        {/* Action Buttons */}
        <div className="form-actions">
          <button
            type="button"
            onClick={onCancel}
            className="btn btn-secondary"
            disabled={isSubmitting}
          >
            <X size={16} />
            Cancel
          </button>

          <button
            type="button"
            onClick={handleReject}
            className="btn btn-danger"
            disabled={isSubmitting}
          >
            Reject
          </button>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
            onClick={() => {
              console.log('Approve button clicked', { isSubmitting });
              console.log('Current form values:', getValues());
            }}
          >
            <Save size={16} />
            {isSubmitting ? 'Saving...' : 'Approve & Create'}
          </button>
        </div>
      </form>
    </div>
  );
};
