/**
 * API service for making HTTP requests to the backend.
 */
import axios from 'axios';
import type {
  Contract,
  ContractWithParties,
  Party,
  DocumentUploadResponse,
  DocumentExtractionStatus,
  ExtractionResult,
  ReviewData,
  ReviewApprovalResponse,
} from '@/types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Document APIs
export const documentApi = {
  /**
   * Upload a document for extraction.
   */
  upload: async (file: File): Promise<DocumentUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await api.post<DocumentUploadResponse>(
      '/documents/upload',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  },

  /**
   * Get the status of an extraction job.
   */
  getStatus: async (jobId: string): Promise<DocumentExtractionStatus> => {
    const response = await api.get<DocumentExtractionStatus>(`/documents/status/${jobId}`);
    return response.data;
  },

  /**
   * Get the extraction results for a completed job.
   */
  getResults: async (jobId: string): Promise<ExtractionResult> => {
    const response = await api.get<ExtractionResult>(`/documents/results/${jobId}`);
    return response.data;
  },

  /**
   * Delete a document and its extraction data.
   */
  delete: async (jobId: string): Promise<void> => {
    await api.delete(`/documents/${jobId}`);
  },
};

// Contract APIs
export const contractApi = {
  /**
   * Get all contracts with optional filters.
   */
  getAll: async (params?: {
    skip?: number;
    limit?: number;
    status?: string;
    contract_type?: string;
  }): Promise<Contract[]> => {
    const response = await api.get<Contract[]>('/contracts/', { params });
    return response.data;
  },

  /**
   * Get a single contract by ID with parties.
   */
  getById: async (id: number): Promise<ContractWithParties> => {
    const response = await api.get<ContractWithParties>(`/contracts/${id}`);
    return response.data;
  },

  /**
   * Create a new contract.
   */
  create: async (data: Partial<Contract>): Promise<Contract> => {
    const response = await api.post<Contract>('/contracts/', data);
    return response.data;
  },

  /**
   * Update an existing contract.
   */
  update: async (id: number, data: Partial<Contract>): Promise<Contract> => {
    const response = await api.put<Contract>(`/contracts/${id}`, data);
    return response.data;
  },

  /**
   * Delete a contract (soft delete).
   */
  delete: async (id: number): Promise<void> => {
    await api.delete(`/contracts/${id}`);
  },

  /**
   * Add a party to a contract.
   */
  addParty: async (contractId: number, partyId: number, role: string): Promise<void> => {
    await api.post(`/contracts/${contractId}/parties/${partyId}?role=${role}`);
  },

  /**
   * Remove a party from a contract.
   */
  removeParty: async (contractId: number, partyId: number): Promise<void> => {
    await api.delete(`/contracts/${contractId}/parties/${partyId}`);
  },
};

// Party APIs
export const partyApi = {
  /**
   * Get all parties with optional filters.
   */
  getAll: async (params?: {
    skip?: number;
    limit?: number;
    party_type?: string;
    is_active?: boolean;
  }): Promise<Party[]> => {
    const response = await api.get<Party[]>('/parties/', { params });
    return response.data;
  },

  /**
   * Get a single party by ID.
   */
  getById: async (id: number): Promise<Party> => {
    const response = await api.get<Party>(`/parties/${id}`);
    return response.data;
  },

  /**
   * Search parties by name.
   */
  searchByName: async (name: string): Promise<Party[]> => {
    const response = await api.get<Party[]>('/parties/search/by-name', {
      params: { name },
    });
    return response.data;
  },

  /**
   * Create a new party.
   */
  create: async (data: Partial<Party>): Promise<Party> => {
    const response = await api.post<Party>('/parties/', data);
    return response.data;
  },

  /**
   * Update an existing party.
   */
  update: async (id: number, data: Partial<Party>): Promise<Party> => {
    const response = await api.put<Party>(`/parties/${id}`, data);
    return response.data;
  },

  /**
   * Delete a party (soft delete).
   */
  delete: async (id: number): Promise<void> => {
    await api.delete(`/parties/${id}`);
  },
};

// Review APIs
export const reviewApi = {
  /**
   * Approve and create contract and parties from extracted data.
   */
  approve: async (data: ReviewData): Promise<ReviewApprovalResponse> => {
    const response = await api.post<ReviewApprovalResponse>('/review/approve', data);
    return response.data;
  },

  /**
   * Reject extracted data.
   */
  reject: async (jobId: string, reason: string): Promise<void> => {
    await api.post(`/review/reject/${jobId}`, { reason });
  },
};

export default api;
