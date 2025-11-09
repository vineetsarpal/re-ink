/**
 * ReviewForm component for reviewing and editing extracted contract data.
 * Allows users to verify AI-extracted information before creating records.
 */
import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Save, X, Edit } from 'lucide-react';
import type { ExtractionResult, ReviewData } from '@/types';
import { reviewApi } from '@/services/api';

interface ReviewFormProps {
  extractionResult: ExtractionResult;
  onApprove?: (contractId: number, partyIds: number[]) => void;
  onReject?: () => void;
  onCancel?: () => void;
}

export const ReviewForm: React.FC<ReviewFormProps> = ({
  extractionResult,
  onApprove,
  onReject,
  onCancel,
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const { register, handleSubmit, formState: { errors } } = useForm({
    defaultValues: {
      contract: extractionResult.contract_data,
      parties: extractionResult.parties_data,
    },
  });

  const onSubmit = async (data: any) => {
    setIsSubmitting(true);

    try {
      const reviewData: ReviewData = {
        contract: data.contract,
        parties: data.parties,
        create_new_parties: true,
      };

      const response = await reviewApi.approve(reviewData);
      onApprove?.(response.contract_id, response.party_ids);
    } catch (err: any) {
      console.error('Error approving data:', err);
      alert(err.response?.data?.detail || 'Failed to approve data');
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
            className="btn btn-secondary"
          >
            <Edit size={16} />
            {isEditing ? 'View Mode' : 'Edit Mode'}
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
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
              <select
                id="contract_type"
                {...register('contract.contract_type')}
                disabled={!isEditing}
              >
                <option value="">Select type</option>
                <option value="treaty">Treaty</option>
                <option value="facultative">Facultative</option>
                <option value="proportional">Proportional</option>
                <option value="non-proportional">Non-Proportional</option>
              </select>
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
              <label htmlFor="premium_amount">Premium Amount</label>
              <input
                type="number"
                step="0.01"
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
          <h3>Parties ({extractionResult.parties_data.length})</h3>

          {extractionResult.parties_data.map((party, index) => (
            <div key={index} className="party-card">
              <h4>
                {party.name || `Party ${index + 1}`} ({party.party_type})
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
                    <option value="cedent">Cedent</option>
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
          >
            <Save size={16} />
            {isSubmitting ? 'Saving...' : 'Approve & Create'}
          </button>
        </div>
      </form>
    </div>
  );
};
