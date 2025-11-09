/**
 * ContractsPage - List and manage all contracts.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter, Plus } from 'lucide-react';
import { contractApi } from '@/services/api';
import type { Contract } from '@/types';

export const ContractsPage: React.FC = () => {
  const navigate = useNavigate();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  useEffect(() => {
    loadContracts();
  }, [statusFilter]);

  const loadContracts = async () => {
    setIsLoading(true);
    try {
      const data = await contractApi.getAll({
        status: statusFilter || undefined,
      });
      setContracts(data);
    } catch (err) {
      console.error('Error loading contracts:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const filteredContracts = contracts.filter((contract) => {
    const matchesSearch =
      contract.contract_number.toLowerCase().includes(searchTerm.toLowerCase()) ||
      contract.contract_name.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSearch;
  });

  return (
    <div className="contracts-page">
      <div className="page-header">
        <h1>Contracts</h1>
        <button
          onClick={() => navigate('/upload')}
          className="btn btn-primary"
        >
          <Plus size={20} />
          Upload New
        </button>
      </div>

      {/* Filters */}
      <div className="filters-bar">
        <div className="search-box">
          <Search size={20} />
          <input
            type="text"
            placeholder="Search contracts..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <Filter size={20} />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All Statuses</option>
            <option value="draft">Draft</option>
            <option value="pending_review">Pending Review</option>
            <option value="active">Active</option>
            <option value="expired">Expired</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      {/* Contracts Table */}
      {isLoading ? (
        <p>Loading contracts...</p>
      ) : filteredContracts.length === 0 ? (
        <div className="empty-state">
          <p>No contracts found</p>
        </div>
      ) : (
        <div className="contracts-table">
          <table>
            <thead>
              <tr>
                <th>Contract Number</th>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Effective Date</th>
                <th>Expiration Date</th>
                <th>Premium Amount</th>
                <th>Review Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredContracts.map((contract) => (
                <tr
                  key={contract.id}
                  onClick={() => navigate(`/contracts/${contract.id}`)}
                  className="clickable"
                >
                  <td>{contract.contract_number}</td>
                  <td>{contract.contract_name}</td>
                  <td>{contract.contract_type || 'N/A'}</td>
                  <td>
                    <span className={`status-badge status-${contract.status}`}>
                      {contract.status}
                    </span>
                  </td>
                  <td>{new Date(contract.effective_date).toLocaleDateString()}</td>
                  <td>{new Date(contract.expiration_date).toLocaleDateString()}</td>
                  <td>
                    {contract.premium_amount
                      ? `${contract.currency} ${contract.premium_amount.toLocaleString()}`
                      : 'N/A'}
                  </td>
                  <td>
                    <span
                      className={`status-badge review-${contract.review_status}`}
                    >
                      {contract.review_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
