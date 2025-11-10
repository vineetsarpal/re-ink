/**
 * Dashboard page - main landing page showing contracts and parties overview.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Users, Plus, TrendingUp } from 'lucide-react';
import { contractApi, partyApi } from '@/services/api';
import type { Contract, Party } from '@/types';

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [stats, setStats] = useState({
    totalContracts: 0,
    activeContracts: 0,
    pendingReview: 0,
    totalParties: 0,
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [contractsData, partiesData] = await Promise.all([
        contractApi.getAll({ limit: 10 }),
        partyApi.getAll({ limit: 10 }),
      ]);

      setContracts(contractsData);
      setParties(partiesData);

      // Calculate stats
      setStats({
        totalContracts: contractsData.length,
        activeContracts: contractsData.filter((c) => c.status === 'active').length,
        pendingReview: contractsData.filter((c) => c.review_status === 'pending')
          .length,
        totalParties: partiesData.length,
      });
    } catch (err) {
      console.error('Error loading dashboard data:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>Dashboard</h1>
        <button
          onClick={() => navigate('/upload')}
          className="btn btn-primary"
        >
          <Plus size={20} />
          Upload Document
        </button>
      </div>

      {/* Stats Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon">
            <FileText size={32} />
          </div>
          <div className="stat-content">
            <h3>{stats.totalContracts}</h3>
            <p>Total Contracts</p>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon success">
            <TrendingUp size={32} />
          </div>
          <div className="stat-content">
            <h3>{stats.activeContracts}</h3>
            <p>Active Contracts</p>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon warning">
            <FileText size={32} />
          </div>
          <div className="stat-content">
            <h3>{stats.pendingReview}</h3>
            <p>Pending Review</p>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">
            <Users size={32} />
          </div>
          <div className="stat-content">
            <h3>{stats.totalParties}</h3>
            <p>Total Parties</p>
          </div>
        </div>
      </div>

      {/* Recent Contracts */}
      <section className="dashboard-section">
        <div className="section-header">
          <h2>Recent Contracts</h2>
          <button
            onClick={() => navigate('/contracts')}
            className="btn btn-secondary"
          >
            View All
          </button>
        </div>

        {isLoading ? (
          <p>Loading...</p>
        ) : contracts.length === 0 ? (
          <div className="empty-state">
            <FileText size={48} />
            <p>No contracts yet. Upload a document to get started.</p>
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
                  <th>Premium</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map((contract) => (
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
                    <td>
                      {contract.premium_amount
                        ? `${contract.currency} ${contract.premium_amount.toLocaleString()}`
                        : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Recent Parties */}
      <section className="dashboard-section">
        <div className="section-header">
          <h2>Recent Parties</h2>
          <button
            onClick={() => navigate('/parties')}
            className="btn btn-secondary"
          >
            View All
          </button>
        </div>

        {isLoading ? (
          <p>Loading...</p>
        ) : parties.length === 0 ? (
          <div className="empty-state">
            <Users size={48} />
            <p>No parties yet.</p>
          </div>
        ) : (
          <div className="parties-grid">
            {parties.map((party) => (
              <div
                key={party.id}
                className="party-card clickable"
                onClick={() => navigate(`/parties/${party.id}`)}
              >
                <h3>{party.name}</h3>
                <p className="party-type">{party.party_type}</p>
                {party.email && <p className="party-email">{party.email}</p>}
                {party.country && <p className="party-location">{party.country}</p>}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
