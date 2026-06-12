/**
 * ReviewForm component for reviewing and editing extracted contract data.
 * Allows users to verify AI-extracted information before creating records.
 * Includes fuzzy-matching against existing parties to prevent duplicates.
 */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Save, X, Edit, RefreshCw, Search, UserCheck, UserPlus, FileText, FileSearch, Maximize2 } from 'lucide-react';
import type {
  ExtractionResult,
  FieldSource,
  ReviewData,
  Party,
  PartyAction,
  PartyMatchCandidate,
  PartyMatchResult,
  GuidedIntakeResponse,
} from '@/types';
import { reviewApi, partyApi } from '@/services/api';
import { DocumentPreview, type GroundedBox } from '@/components/DocumentPreview';
import { SecondarySidebar } from '@/components/SecondarySidebar';

/**
 * Declarative description of the contract form fields. Driving the render from
 * a config (rather than ~20 hand-written inputs) lets every field share the
 * same source-evidence wiring: focus a field -> reveal where its value came
 * from in the document. `name` matches the DB column / source-evidence key.
 */
interface ContractFieldConfig {
  name: string;
  label: string;
  type?: 'text' | 'date' | 'textarea';
  required?: boolean;
  placeholder?: string;
  defaultValue?: string;
  fullWidth?: boolean;
}

const CONTRACT_FIELDS: ContractFieldConfig[] = [
  { name: 'contract_number', label: 'Contract Number *', required: true },
  { name: 'contract_name', label: 'Contract Name *', required: true },
  { name: 'contract_type', label: 'Contract Type' },
  { name: 'contract_sub_type', label: 'Contract Sub-Type' },
  { name: 'contract_nature', label: 'Contract Nature' },
  { name: 'effective_date', label: 'Effective Date *', type: 'date', required: true },
  { name: 'expiration_date', label: 'Expiration Date *', type: 'date', required: true },
  { name: 'premium_amount', label: 'Premium Amount' },
  { name: 'premium_description', label: 'Premium Description', placeholder: 'e.g. 100% of gross premium' },
  { name: 'currency', label: 'Currency', defaultValue: 'USD' },
  { name: 'limit_amount', label: 'Limit Amount' },
  { name: 'limit_description', label: 'Limit Description', placeholder: 'e.g. 100% quota share' },
  { name: 'retention_amount', label: 'Retention/Deductible Amount' },
  { name: 'retention_description', label: 'Retention/Deductible Description', placeholder: 'e.g. $150,000,000 net of recoveries' },
  { name: 'commission_description', label: 'Commission', placeholder: 'e.g. all expenses + 0.5% of net written premium' },
  { name: 'commission_rate', label: 'Commission Rate (%)' },
  { name: 'line_of_business', label: 'Line of Business' },
  { name: 'coverage_territory', label: 'Coverage Territory', fullWidth: true },
  { name: 'coverage_description', label: 'Coverage Description', type: 'textarea', fullWidth: true },
  { name: 'terms_and_conditions', label: 'Terms and Conditions', type: 'textarea', fullWidth: true },
  { name: 'special_provisions', label: 'Special Provisions', type: 'textarea', fullWidth: true },
];

const CONTRACT_LABELS: Record<string, string> = Object.fromEntries(
  CONTRACT_FIELDS.map((f) => [f.name, f.label.replace(/\s*\*$/, '')]),
);

interface ReviewFormProps {
  extractionResult: ExtractionResult;
  /** URL streaming the original document for preview. Null for mock jobs. */
  documentUrl?: string | null;
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
  documentUrl = null,
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

  // Source grounding: which field's evidence is shown in the side panel, and
  // whether the document preview is expanded. `activeKey` is "contract:<name>"
  // or "party:<index>".
  const contractSources = extractionResult.field_sources?.contract ?? {};
  const partySources = extractionResult.field_sources?.parties ?? [];
  const [activeKey, setActiveKey] = useState<string | null>(null);
  // Whether the document-with-boxes preview is opened in the enlarge modal.
  const [isPreviewExpanded, setIsPreviewExpanded] = useState(false);
  // Tracks the source-grounding sidebar; per-field source links only render
  // while the panel is open, since that's where they reveal their evidence.
  const [isSourcePanelCollapsed, setIsSourcePanelCollapsed] = useState(false);
  // Bumped on every Source-link click so the preview re-jumps to the field's
  // page even when the same field is clicked twice (after manual paging).
  const [jumpSignal, setJumpSignal] = useState(0);

  const focusSource = (fieldKey: string) => {
    setActiveKey(fieldKey);
    setJumpSignal((n) => n + 1);
  };

  const groundedCount = useMemo(() => {
    const contract = Object.keys(contractSources).length;
    const parties = partySources.filter((p) => p && p.name).length;
    return contract + parties;
  }, [contractSources, partySources]);

  // All grounded passages with a page + bounding box, flattened into the shape
  // DocumentPreview draws. The `key` mirrors `activeKey` so focusing a field and
  // clicking its box stay in sync. Party labels track the live edited name.
  const groundedBoxes = useMemo<GroundedBox[]>(() => {
    const result: GroundedBox[] = [];
    Object.entries(contractSources).forEach(([name, source]) => {
      if (source?.bbox && source.page_number != null) {
        result.push({
          key: `contract:${name}`,
          label: CONTRACT_LABELS[name] ?? name,
          page: source.page_number,
          bbox: source.bbox,
        });
      }
    });
    partySources.forEach((p, idx) => {
      const source = p?.name;
      if (source?.bbox && source.page_number != null) {
        const name = extractionResult.parties_data?.[idx]?.name || `Party ${idx + 1}`;
        result.push({
          key: `party:${idx}`,
          label: `${name} — Name`,
          page: source.page_number,
          bbox: source.bbox,
        });
      }
    });
    return result;
  }, [contractSources, partySources, extractionResult.parties_data]);

  // Close the enlarge modal on Escape.
  useEffect(() => {
    if (!isPreviewExpanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsPreviewExpanded(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isPreviewExpanded]);

  // Party matching state
  const [matchResults, setMatchResults] = useState<Record<number, PartyMatchResult>>({});
  // null = create new, number = use existing party with that ID
  const [partyDecisions, setPartyDecisions] = useState<Record<number, number | null>>({});
  const [matchLoading, setMatchLoading] = useState(false);

  // Role of each extracted party *on this specific contract*. Lives here and not
  // on the Party record because the same party can play different roles on
  // different contracts. Initialized from the extractor's suggestion.
  const [partyRoles, setPartyRoles] = useState<Record<number, string>>(() => {
    const init: Record<number, string> = {};
    extractionResult.parties_data?.forEach((p, i) => {
      init[i] = (p as any).role || 'cedant';
    });
    return init;
  });

  // Manual party search state (per extracted party)
  const [partySearchOpen, setPartySearchOpen] = useState<Record<number, boolean>>({});
  const [partySearchQuery, setPartySearchQuery] = useState<Record<number, string>>({});
  const [partySearchResults, setPartySearchResults] = useState<Record<number, Party[]>>({});
  const [partySearchLoading, setPartySearchLoading] = useState<Record<number, boolean>>({});
  // Parties the user manually picked via search — kept so we can display their
  // name/type in the candidates list even though the fuzzy match didn't surface them.
  const [manualSelections, setManualSelections] = useState<Record<number, PartyMatchCandidate>>({});
  const searchTimeouts = useRef<Record<number, number>>({});

  const { register, handleSubmit, watch, formState: { errors } } = useForm({
    defaultValues: {
      contract: extractionResult.contract_data,
      parties: extractionResult.parties_data,
    },
  });

  // Fetch party matches on mount
  useEffect(() => {
    const names = extractionResult.parties_data?.map(p => p.name).filter(Boolean) || [];
    if (names.length === 0) return;

    setMatchLoading(true);
    partyApi.matchByName(names)
      .then(results => {
        const map: Record<number, PartyMatchResult> = {};
        const decisions: Record<number, number | null> = {};
        results.forEach((r, i) => {
          map[i] = r;
          // Auto-select matches with score >= 90
          if (r.candidates.length > 0 && r.candidates[0].score >= 90) {
            decisions[i] = r.candidates[0].party_id;
          } else {
            decisions[i] = null;
          }
        });
        setMatchResults(map);
        setPartyDecisions(decisions);
      })
      .catch(err => console.error('Party match fetch failed:', err))
      .finally(() => setMatchLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearchQueryChange = (index: number, query: string) => {
    setPartySearchQuery(prev => ({ ...prev, [index]: query }));

    const existing = searchTimeouts.current[index];
    if (existing) window.clearTimeout(existing);

    if (query.trim().length < 2) {
      setPartySearchResults(prev => ({ ...prev, [index]: [] }));
      setPartySearchLoading(prev => ({ ...prev, [index]: false }));
      return;
    }

    setPartySearchLoading(prev => ({ ...prev, [index]: true }));
    searchTimeouts.current[index] = window.setTimeout(() => {
      partyApi.searchByName(query.trim())
        .then(results => setPartySearchResults(prev => ({ ...prev, [index]: results })))
        .catch(err => console.error('Party search failed:', err))
        .finally(() => setPartySearchLoading(prev => ({ ...prev, [index]: false })));
    }, 300);
  };

  const handleSelectSearchResult = (index: number, party: Party) => {
    setManualSelections(prev => ({
      ...prev,
      [index]: {
        party_id: party.id,
        party_name: party.name,
        score: 100,
      },
    }));
    setPartyDecisions(prev => ({ ...prev, [index]: party.id }));
    setPartySearchOpen(prev => ({ ...prev, [index]: false }));
  };

  const onSubmit = async (data: any) => {
    setIsSubmitting(true);

    try {
      const parties = data.parties || [];

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

      const cleanObject = (obj: any): any => {
        const cleaned: any = {};
        for (const key in obj) {
          const value = obj[key];
          if (value === '') {
            cleaned[key] = null;
          } else if (value !== undefined) {
            cleaned[key] = value;
          }
        }
        return cleaned;
      };

      const cleanedContract = cleanObject(data.contract);

      // Build PartyAction[] from user decisions. ``role`` is stored per action
      // (not on the Party itself) so it can differ across contracts.
      const partyActions: PartyAction[] = parties.map((partyFormData: any, index: number) => {
        const decision = partyDecisions[index];
        const role = partyRoles[index];
        if (decision != null) {
          return {
            action: 'use_existing' as const,
            role,
            existing_party_id: decision,
          };
        } else {
          // Strip any stray ``role`` / legacy ``party_type`` keys from the
          // party form payload — role lives on the action, not the party.
          const { role: _r, party_type: _pt, ...partyOnly } = partyFormData || {};
          return {
            action: 'create_new' as const,
            role,
            party_data: cleanObject(partyOnly),
          };
        }
      });

      const reviewData: ReviewData = {
        contract: cleanedContract,
        parties: partyActions,
      };

      const response = await reviewApi.approve(reviewData);
      let approvalHandled = false;
      if (onApprove) {
        await onApprove(response.contract_id, response.party_ids, response.message);
        approvalHandled = true;
      }

      if (!approvalHandled) {
        alert(
          `Success!\n\n${response.message}\n\n` +
          `Contract ID: ${response.contract_id}\n` +
          `Parties: ${
            response.party_ids.length > 0 ? response.party_ids.join(', ') : 'None'
          }`
        );
      }
    } catch (err: any) {
      console.error('Error approving data:', err);
      console.error('Error response data:', err.response?.data);

      if (err.response?.status === 409) {
        const detail = err.response.data.detail;
        if (detail?.error === 'duplicate_contract') {
          const message =
            `Duplicate Contract Detected\n\n` +
            `Contract Number: ${detail.contract_number}\n\n` +
            `This contract already exists in the system (ID: ${detail.existing_contract_id}).\n\n` +
            `You can view it on the Contracts page.`;

          alert(message);
          if (confirm('Would you like to view the Contracts page?')) {
            onCancel?.();
          }
          setIsSubmitting(false);
          return;
        }
      }

      let errorMessage = 'Failed to approve data';
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
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

  const getScoreClass = (score: number) => {
    if (score >= 85) return 'high';
    if (score >= 70) return 'medium';
    return 'low';
  };

  // Resolve the currently-focused field into a label + its source evidence for
  // the side panel. Party labels use the live name so the panel stays in sync.
  const activeSource = useMemo<{ label: string; source: FieldSource | null } | null>(() => {
    if (!activeKey) return null;
    const [scope, key] = activeKey.split(':');
    if (scope === 'contract') {
      return { label: CONTRACT_LABELS[key] ?? key, source: contractSources[key] ?? null };
    }
    const idx = Number(key);
    const name =
      watch(`parties.${idx}.name`) ||
      extractionResult.parties_data?.[idx]?.name ||
      `Party ${idx + 1}`;
    return { label: `${name} — Name`, source: partySources[idx]?.name ?? null };
  }, [activeKey, contractSources, partySources, watch, extractionResult.parties_data]);

  // Small inline affordance shown under each field. Clicking it (or focusing the
  // field) reveals the evidence in the side panel.
  const renderSourceHint = (fieldKey: string, source: FieldSource | null | undefined) => {
    if (isSourcePanelCollapsed) return null;
    const isActive = activeKey === fieldKey;
    if (!source) {
      return (
        <span className="source-hint source-hint--none" title="The AI did not link this value to a passage in the document.">
          No source found · verify manually
        </span>
      );
    }
    return (
      <button
        type="button"
        className={`source-hint source-hint--found ${isActive ? 'source-hint--active' : ''}`}
        onClick={() => focusSource(fieldKey)}
      >
        <FileText size={12} />
        {source.page_number != null ? `Source · p.${source.page_number}` : 'Source available'}
      </button>
    );
  };

  return (
    <div className="review-form">
      <div className="form-header">
        <div>
          <h2>Review Extracted Data</h2>
          <p className="review-form__grounding-note">
            <FileSearch size={14} />
            {groundedCount > 0
              ? `${groundedCount} field${groundedCount === 1 ? '' : 's'} linked to the source document — focus any field to verify.`
              : 'No source evidence available for this extraction — verify fields manually.'}
          </p>
        </div>
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

      <div className="review-layout">
      <form onSubmit={(e) => {
        handleSubmit(
          onSubmit,
          (validationErrors) => {
            const errorMessages: string[] = [];

            if (validationErrors.contract) {
              const contractErrors = validationErrors.contract as Record<string, { message?: string } | undefined>;
              Object.keys(contractErrors).forEach(field => {
                errorMessages.push(`Contract ${field}: ${contractErrors[field]?.message || 'Required'}`);
              });
            }

            if (validationErrors.parties) {
              const partiesErrors = validationErrors.parties as Array<Record<string, { message?: string }> | undefined>;
              partiesErrors.forEach((partyErrors, i) => {
                if (!partyErrors) return;
                Object.keys(partyErrors).forEach(field => {
                  errorMessages.push(`Party ${i + 1} ${field}: ${partyErrors[field]?.message || 'Required'}`);
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
            {CONTRACT_FIELDS.map((field) => {
              const fieldKey = `contract:${field.name}`;
              const source = contractSources[field.name];
              const hasError = field.required && (errors.contract as any)?.[field.name];
              const registration = register(
                `contract.${field.name}` as const,
                field.required ? { required: true } : undefined,
              );
              return (
                <div
                  key={field.name}
                  className={`form-field ${field.fullWidth ? 'full-width' : ''} ${activeKey === fieldKey ? 'form-field--active-source' : ''}`}
                >
                  <label htmlFor={field.name}>{field.label}</label>
                  {field.type === 'textarea' ? (
                    <textarea
                      id={field.name}
                      rows={3}
                      {...registration}
                      disabled={!isEditing}
                      placeholder={field.placeholder}
                      onFocus={() => setActiveKey(fieldKey)}
                    />
                  ) : (
                    <input
                      id={field.name}
                      type={field.type ?? 'text'}
                      {...registration}
                      disabled={!isEditing}
                      placeholder={field.placeholder}
                      defaultValue={field.defaultValue}
                      className={hasError ? 'error' : ''}
                      onFocus={() => setActiveKey(fieldKey)}
                    />
                  )}
                  {hasError && <span className="field-error">Required field</span>}
                  {renderSourceHint(fieldKey, source)}
                </div>
              );
            })}
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
                No parties were extracted from the document.
                The contract will be created without associated parties.
                You can add parties later.
              </p>
            </div>
          )}

          {extractionResult.parties_data?.map((party, index) => {
            const isLinked = partyDecisions[index] != null;
            const matchResult = matchResults[index];

            // Derive the display name for the card header:
            // - linked to existing → name of the selected party
            // - create new → live value from the Name input (falls back to extraction)
            const linkedName = (() => {
              const id = partyDecisions[index];
              if (id == null) return null;
              const fromCandidates = matchResults[index]?.candidates.find(c => c.party_id === id)?.party_name;
              return fromCandidates || manualSelections[index]?.party_name || null;
            })();
            const cardName = linkedName
              ?? watch(`parties.${index}.name`)
              ?? party.name
              ?? `Party ${index + 1}`;

            return (
              <div key={index} className={`party-card ${isLinked ? 'party-card--linked' : ''}`}>
                <div className="party-card__header">
                  <h4>
                    {cardName} {partyRoles[index] && `(${partyRoles[index]})`}
                  </h4>
                  {isLinked && (
                    <span className="party-card__linked-badge">
                      <UserCheck size={14} />
                      Linked to existing
                    </span>
                  )}
                </div>

                {/* Role is per-contract — lives outside form-grid (which is
                    dimmed/locked when a party is linked) and sits at the top
                    of the card so it is clearly a contract-level field. */}
                <div className="party-contract-role-box">
                  <label className="party-contract-role-label">Role on this contract *</label>
                  <select
                    className="party-contract-role-select"
                    value={partyRoles[index] || 'cedant'}
                    onChange={(e) =>
                      setPartyRoles(prev => ({ ...prev, [index]: e.target.value }))
                    }
                    disabled={!isEditing}
                  >
                    <option value="cedant">Cedant</option>
                    <option value="reinsurer">Reinsurer</option>
                    <option value="broker">Broker</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                <div className="form-grid">
                  <div className={`form-field full-width ${activeKey === `party:${index}` ? 'form-field--active-source' : ''}`}>
                    <label>Name *</label>
                    <input
                      {...register(`parties.${index}.name`, { required: true })}
                      disabled={!isEditing || isLinked}
                      onFocus={() => setActiveKey(`party:${index}`)}
                    />
                    {renderSourceHint(`party:${index}`, partySources[index]?.name)}
                  </div>

                  <div className="form-field">
                    <label>Email</label>
                    <input
                      type="email"
                      {...register(`parties.${index}.email`)}
                      disabled={!isEditing || isLinked}
                    />
                  </div>

                  <div className="form-field">
                    <label>Phone</label>
                    <input
                      {...register(`parties.${index}.phone`)}
                      disabled={!isEditing || isLinked}
                    />
                  </div>

                  <div className="form-field">
                    <label>Registration Number</label>
                    <input
                      {...register(`parties.${index}.registration_number`)}
                      disabled={!isEditing || isLinked}
                    />
                  </div>
                </div>

                {/* Party match suggestions */}
                <div className="party-match-suggestions">
                  {matchLoading && (
                    <p className="party-match-loading">Searching for existing matches...</p>
                  )}

                  {!matchLoading && matchResult && (() => {
                    const manualPick = manualSelections[index];
                    const hasManualExtra = manualPick && !matchResult.candidates.some(c => c.party_id === manualPick.party_id);
                    const hasAnyCandidate = matchResult.candidates.length > 0 || !!manualPick;

                    return (
                      <>
                        <div
                          className={`party-match-option create-new ${partyDecisions[index] === null ? 'selected' : ''}`}
                          onClick={() => setPartyDecisions(prev => ({ ...prev, [index]: null }))}
                        >
                          <UserPlus size={16} className="party-match-icon" />
                          <span className="party-match-name">Create as new party</span>
                        </div>

                        <div className="party-match-divider">
                          <span>or</span>
                        </div>

                        <p className="party-match-section-heading">Link to an existing party</p>

                        {hasAnyCandidate && (
                          <p className="party-match-label">Possible existing matches:</p>
                        )}

                        {matchResult.candidates.map(candidate => (
                          <div
                            key={candidate.party_id}
                            className={`party-match-option ${partyDecisions[index] === candidate.party_id ? 'selected' : ''}`}
                            onClick={() => setPartyDecisions(prev => ({ ...prev, [index]: candidate.party_id }))}
                          >
                            <UserCheck size={16} className="party-match-icon" />
                            <span className="party-match-name">{candidate.party_name}</span>
                            <span className={`party-match-score ${getScoreClass(candidate.score)}`}>
                              {candidate.score.toFixed(0)}% match
                            </span>
                          </div>
                        ))}

                        {hasManualExtra && (
                          <div
                            className={`party-match-option ${partyDecisions[index] === manualPick!.party_id ? 'selected' : ''}`}
                            onClick={() => setPartyDecisions(prev => ({ ...prev, [index]: manualPick!.party_id }))}
                          >
                            <UserCheck size={16} className="party-match-icon" />
                            <span className="party-match-name">{manualPick!.party_name}</span>
                            <span className="party-match-score high">Manually selected</span>
                          </div>
                        )}

                        {!hasAnyCandidate && (
                          <p className="party-match-no-results">No existing matches found.</p>
                        )}

                        <button
                          type="button"
                          className="party-search-toggle"
                          onClick={() => setPartySearchOpen(prev => ({ ...prev, [index]: !prev[index] }))}
                        >
                          <Search size={14} />
                          {partySearchOpen[index] ? 'Hide party search' : 'Search existing parties'}
                        </button>

                        {partySearchOpen[index] && (
                          <div className="party-search-box">
                            <input
                              type="text"
                              className="party-search-input"
                              placeholder="Type at least 2 characters to search…"
                              value={partySearchQuery[index] || ''}
                              onChange={(e) => handleSearchQueryChange(index, e.target.value)}
                            />
                            {partySearchLoading[index] && (
                              <p className="party-match-loading">Searching…</p>
                            )}
                            {!partySearchLoading[index]
                              && (partySearchQuery[index]?.trim().length ?? 0) >= 2
                              && (partySearchResults[index]?.length ?? 0) === 0 && (
                                <p className="party-match-no-results">No parties found.</p>
                            )}
                            {partySearchResults[index]?.map(p => (
                              <div
                                key={p.id}
                                className={`party-match-option ${partyDecisions[index] === p.id ? 'selected' : ''}`}
                                onClick={() => handleSelectSearchResult(index, p)}
                              >
                                <UserCheck size={16} className="party-match-icon" />
                                <span className="party-match-name">{p.name}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
              </div>
            );
          })}
        </section>

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
            {agentLoading && <p>Generating AI insights for this extraction...</p>}
            {!agentLoading && agentError && (
              <p className="agent-panel__error">{agentError}</p>
            )}
            {!agentLoading && !agentError && !agentAnalysis?.analysis && agentAnalysis?.errors && agentAnalysis.errors.length > 0 && (
              <div className="agent-panel__error">
                {agentAnalysis.errors
                  .filter((err) => !err.includes('validation failed'))
                  .map((err, i) => (
                    <p key={i}>{err}</p>
                  ))}
              </div>
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
          >
            <Save size={16} />
            {isSubmitting ? 'Saving...' : 'Approve & Create'}
          </button>
        </div>
      </form>

      {/* Source grounding panel — projected into the layout's secondary
          sidebar (flush against the nav) while the review step is mounted.
          Reveals where a focused field's value came from in the document, and
          (for real jobs) jumps the document preview to the matching page. */}
      <SecondarySidebar
        title="Source Grounding"
        icon={<FileSearch size={15} />}
        collapsed={isSourcePanelCollapsed}
        onCollapsedChange={setIsSourcePanelCollapsed}
      >
        {!activeSource && (
          <p className="source-panel__hint">
            Select or focus any field to see where its value was found in the
            uploaded document.
          </p>
        )}

        {activeSource && (
          <div className="source-panel__body">
            <p className="source-panel__field-label">{activeSource.label}</p>

            {activeSource.source ? (
              <>
                {activeSource.source.page_number != null && (
                  <span className="source-panel__page">
                    Page {activeSource.source.page_number}
                  </span>
                )}
                {activeSource.source.source_text ? (
                  <blockquote className="source-panel__quote">
                    {activeSource.source.source_text}
                  </blockquote>
                ) : (
                  <p className="source-panel__partial">
                    Referenced in the document
                    {activeSource.source.page_number != null
                      ? ` on page ${activeSource.source.page_number}`
                      : ''}
                    , but the exact passage could not be located. Please verify
                    manually.
                  </p>
                )}
                {activeSource.source.confidence != null && (
                  <p className="source-panel__confidence">
                    Confidence: {(activeSource.source.confidence * 100).toFixed(0)}%
                  </p>
                )}
              </>
            ) : (
              <p className="source-panel__none">
                No source found for this field. <strong>Needs manual
                verification.</strong>
              </p>
            )}
          </div>
        )}

        {documentUrl && (
          <div className="source-panel__preview">
            <div className="source-panel__preview-head">
              <span className="source-panel__preview-title">
                <FileText size={14} /> Original document
              </span>
              <button
                type="button"
                className="source-panel__enlarge"
                onClick={() => setIsPreviewExpanded(true)}
              >
                <Maximize2 size={13} /> Enlarge
              </button>
            </div>
            <p className="source-panel__preview-help">
              {groundedBoxes.length > 0
                ? 'Highlighted boxes mark where each field was found. Click a box or a field’s Source link to jump to it.'
                : 'Focus a field with a Source link to locate it in the document.'}
            </p>
            <DocumentPreview
              documentUrl={documentUrl}
              boxes={groundedBoxes}
              activeKey={activeKey}
              jumpSignal={jumpSignal}
              onSelectBox={setActiveKey}
              onToggleFullscreen={() => setIsPreviewExpanded(true)}
            />
          </div>
        )}
      </SecondarySidebar>
      </div>

      {/* Enlarged document-with-boxes view. */}
      {documentUrl && isPreviewExpanded && (
        <div
          className="doc-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Document preview"
          onClick={() => setIsPreviewExpanded(false)}
        >
          <div className="doc-modal__panel" onClick={(e) => e.stopPropagation()}>
            <DocumentPreview
              documentUrl={documentUrl}
              boxes={groundedBoxes}
              activeKey={activeKey}
              jumpSignal={jumpSignal}
              onSelectBox={setActiveKey}
              fullscreen
              onToggleFullscreen={() => setIsPreviewExpanded(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
};
