/**
 * PartyDetailPage - Displays detailed information about a single party.
 */
import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Building2, Mail, Phone, MapPin, FileText, Calendar, Edit2, Save, X, Trash2 } from 'lucide-react';
import { partyApi } from '@/services/api';
import type { Party } from '@/types';

export const PartyDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [editedData, setEditedData] = useState<Partial<Party>>({});

  const { data: party, isLoading, error } = useQuery<Party>({
    queryKey: ['party', id],
    queryFn: () => partyApi.getById(Number(id)),
    enabled: !!id,
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: Partial<Party>) => partyApi.update(Number(id), data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['party', id] });
      setIsEditing(false);
      setEditedData({});
      alert('Party updated successfully!');
    },
    onError: (error: any) => {
      alert(`Failed to update party: ${error.response?.data?.detail || error.message}`);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => partyApi.delete(Number(id)),
    onSuccess: () => {
      alert('Party deleted successfully!');
      navigate('/parties');
    },
    onError: (error: any) => {
      alert(`Failed to delete party: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleEdit = () => {
    if (party) {
      setEditedData(party);
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
    if (
      confirm(
        `Are you sure you want to delete party "${party?.name}"?\n\n` +
          'This action cannot be undone.'
      )
    ) {
      deleteMutation.mutate();
    }
  };

  const handleFieldChange = (field: keyof Party, value: any) => {
    setEditedData((prev) => ({ ...prev, [field]: value }));
  };

  // Helper to get current value
  const getValue = (field: keyof Party) => {
    if (isEditing && editedData[field] !== undefined) {
      return editedData[field];
    }
    return party![field];
  };

  // Helper to render editable field
  const renderField = (
    field: keyof Party,
    type: string = 'text',
    options?: Array<{ value: string; label: string }>
  ) => {
    const value = getValue(field);

    if (!isEditing) {
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
        onChange={(e) => handleFieldChange(field, e.target.value)}
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
        <p>Loading party details...</p>
      </div>
    );
  }

  if (error || !party) {
    return (
      <div className="error-container">
        <h2>Party Not Found</h2>
        <p>The party you're looking for doesn't exist or couldn't be loaded.</p>
        <button onClick={() => navigate('/parties')} className="btn btn-primary">
          <ArrowLeft size={16} />
          Back to Parties
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

  return (
    <div className="party-detail-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <button onClick={() => navigate('/parties')} className="btn-back">
            <ArrowLeft size={20} />
            Back to Parties
          </button>
          <div className="header-content">
            <h1>{party.name}</h1>
            <div className="badges">
              <span className={`badge badge-${party.party_type}`}>
                {party.party_type}
              </span>
              {party.is_active ? (
                <span className="badge badge-active">Active</span>
              ) : (
                <span className="badge badge-inactive">Inactive</span>
              )}
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

      {/* Party Information Grid */}
      <div className="detail-grid">
        {/* Basic Information */}
        <section className="detail-section">
          <h2><Building2 size={20} /> Basic Information</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Name</label>
              <span className="value">{renderField('name')}</span>
            </div>
            <div className="info-item">
              <label>Party Type</label>
              <span className="value capitalize">
                {renderField('party_type', 'select', [
                  { value: 'cedant', label: 'Cedant' },
                  { value: 'reinsurer', label: 'Reinsurer' },
                  { value: 'broker', label: 'Broker' },
                  { value: 'other', label: 'Other' },
                ])}
              </span>
            </div>
            <div className="info-item">
              <label>Registration Number</label>
              <span className="value">{renderField('registration_number')}</span>
            </div>
            <div className="info-item">
              <label>License Number</label>
              <span className="value">{renderField('license_number')}</span>
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
                    <option value="true">Active</option>
                    <option value="false">Inactive (Deleted)</option>
                  </select>
                ) : (
                  getValue('is_active') ? 'Active' : 'Inactive (Deleted)'
                )}
              </span>
            </div>
          </div>
        </section>

        {/* Contact Information */}
        <section className="detail-section">
          <h2><Mail size={20} /> Contact Information</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Email</label>
              {isEditing ? (
                <span className="value">{renderField('email', 'email')}</span>
              ) : party.email ? (
                <a href={`mailto:${party.email}`} className="value link">
                  {party.email}
                </a>
              ) : (
                <span className="value">N/A</span>
              )}
            </div>
            <div className="info-item">
              <label>Phone</label>
              {isEditing ? (
                <span className="value">{renderField('phone')}</span>
              ) : party.phone ? (
                <a href={`tel:${party.phone}`} className="value link">
                  {party.phone}
                </a>
              ) : (
                <span className="value">N/A</span>
              )}
            </div>
          </div>
        </section>

        {/* Address */}
        <section className="detail-section full-width">
          <h2><MapPin size={20} /> Address</h2>
          {isEditing ? (
            <div className="info-grid">
              <div className="info-item">
                <label>Address Line 1</label>
                <span className="value">{renderField('address_line1')}</span>
              </div>
              <div className="info-item">
                <label>Address Line 2</label>
                <span className="value">{renderField('address_line2')}</span>
              </div>
              <div className="info-item">
                <label>City</label>
                <span className="value">{renderField('city')}</span>
              </div>
              <div className="info-item">
                <label>State</label>
                <span className="value">{renderField('state')}</span>
              </div>
              <div className="info-item">
                <label>Postal Code</label>
                <span className="value">{renderField('postal_code')}</span>
              </div>
              <div className="info-item">
                <label>Country</label>
                <span className="value">{renderField('country')}</span>
              </div>
            </div>
          ) : party.address_line1 || party.city || party.country ? (
            <div className="address-block">
              {party.address_line1 && <p>{party.address_line1}</p>}
              {party.address_line2 && <p>{party.address_line2}</p>}
              <p>
                {[party.city, party.state, party.postal_code].filter(Boolean).join(', ')}
              </p>
              {party.country && <p>{party.country}</p>}
            </div>
          ) : (
            <p className="no-data">No address information available</p>
          )}
        </section>

        {/* Metadata */}
        <section className="detail-section">
          <h2><Calendar size={20} /> Record Information</h2>
          <div className="info-grid">
            <div className="info-item">
              <label>Party ID</label>
              <span className="value">{party.id}</span>
            </div>
            <div className="info-item">
              <label>Created</label>
              <span className="value">{formatDate(party.created_at)}</span>
            </div>
            {party.updated_at && (
              <div className="info-item">
                <label>Last Updated</label>
                <span className="value">{formatDate(party.updated_at)}</span>
              </div>
            )}
          </div>
        </section>

        {/* Notes */}
        <section className="detail-section full-width">
          <h2><FileText size={20} /> Notes</h2>
          <div className="info-item full-width">
            <label>Additional Notes</label>
            {isEditing ? (
              <span className="value">{renderField('notes', 'textarea')}</span>
            ) : (
              <p className="value text-block">
                {party.notes || 'No notes available'}
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
