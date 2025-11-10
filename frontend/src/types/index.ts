/**
 * TypeScript type definitions for re-ink application.
 */

export interface Party {
  id: number;
  name: string;
  party_type: string;
  email?: string;
  phone?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
  registration_number?: string;
  license_number?: string;
  notes?: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export interface Contract {
  id: number;
  contract_number: string;
  contract_name: string;
  contract_type?: string;
  contract_sub_type?: string;
  contract_nature?: string;
  effective_date: string;
  expiration_date: string;
  inception_date?: string;
  premium_amount?: number;
  currency: string;
  limit_amount?: number;
  retention_amount?: number;
  commission_rate?: number;
  line_of_business?: string;
  coverage_territory?: string;
  coverage_description?: string;
  terms_and_conditions?: string;
  special_provisions?: string;
  status: string;
  review_status: string;
  source_document_path?: string;
  source_document_name?: string;
  extraction_confidence?: number;
  extraction_job_id?: string;
  is_manually_created: boolean;
  notes?: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export interface ContractWithParties extends Contract {
  parties: Party[];
}

export interface DocumentUploadResponse {
  job_id: string;
  filename: string;
  file_path: string;
  message: string;
  status: string;
}

export interface ExtractionResult {
  contract_data: Record<string, any>;
  parties_data: Record<string, any>[];
  confidence_score?: number;
  extraction_metadata?: Record<string, any>;
}

export interface DocumentExtractionStatus {
  job_id: string;
  status: string;
  message?: string;
  result?: ExtractionResult;
  created_at: string;
}

export interface ReviewData {
  contract: Omit<Contract, 'id' | 'created_at' | 'updated_at'>;
  parties: Omit<Party, 'id' | 'created_at' | 'updated_at'>[];
  create_new_parties: boolean;
}

export interface ReviewApprovalResponse {
  contract_id: number;
  party_ids: number[];
  message: string;
}

export type AgentRole = 'system' | 'user' | 'assistant' | 'tool';

export interface AgentChatMessage {
  role: AgentRole;
  content: string;
}

export interface GuidedIntakeAnalysis {
  summary: string;
  assistant_message: string;
  missing_fields: string[];
  clarifying_questions: string[];
  recommended_next_steps: string[];
  confidence?: number;
}

export interface GuidedIntakeResponse {
  job_id: string;
  status: 'ready' | 'awaiting_input' | 'job_not_ready' | 'error';
  analysis?: GuidedIntakeAnalysis;
  contract_data?: Record<string, any>;
  parties_data: Record<string, any>[];
  suggested_review_payload?: ReviewData;
  messages: AgentChatMessage[];
  errors: string[];
}

export interface ContractReviewAnalysis {
  summary: string;
  assistant_message: string;
  risk_flags: string[];
  recommended_actions: string[];
  compliance_notes: string[];
  confidence?: number;
}

export interface AutomatedReviewResponse {
  contract_id: number;
  status: 'complete' | 'not_found' | 'error';
  analysis?: ContractReviewAnalysis;
  contract_snapshot?: ContractWithParties;
  messages: AgentChatMessage[];
  errors: string[];
}

export type ContractStatus = 'draft' | 'pending_review' | 'active' | 'expired' | 'cancelled';
export type ReviewStatus = 'pending' | 'approved' | 'rejected';
export type PartyType = 'cedant' | 'reinsurer' | 'broker' | 'other';
