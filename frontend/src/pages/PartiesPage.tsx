/**
 * PartiesPage - List and manage all parties.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter } from 'lucide-react';
import { partyApi } from '@/services/api';
import type { Party } from '@/types';

export const PartiesPage: React.FC = () => {
  const navigate = useNavigate();
  const [parties, setParties] = useState<Party[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');

  useEffect(() => {
    loadParties();
  }, [typeFilter]);

  const loadParties = async () => {
    setIsLoading(true);
    try {
      const data = await partyApi.getAll({
        party_type: typeFilter || undefined,
      });
      setParties(data);
    } catch (err) {
      console.error('Error loading parties:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const filteredParties = parties.filter((party) => {
    const matchesSearch = party.name
      .toLowerCase()
      .includes(searchTerm.toLowerCase());
    return matchesSearch;
  });

  return (
    <div className="parties-page">
      <div className="page-header">
        <h1>Parties</h1>
      </div>

      {/* Filters */}
      <div className="filters-bar">
        <div className="search-box">
          <Search size={20} />
          <input
            type="text"
            placeholder="Search parties..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <Filter size={20} />
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="">All Types</option>
            <option value="cedent">Cedent</option>
            <option value="reinsurer">Reinsurer</option>
            <option value="broker">Broker</option>
            <option value="other">Other</option>
          </select>
        </div>
      </div>

      {/* Parties Grid */}
      {isLoading ? (
        <p>Loading parties...</p>
      ) : filteredParties.length === 0 ? (
        <div className="empty-state">
          <p>No parties found</p>
        </div>
      ) : (
        <div className="parties-grid">
          {filteredParties.map((party) => (
            <div
              key={party.id}
              className="party-card clickable"
              onClick={() => navigate(`/parties/${party.id}`)}
            >
              <h3>{party.name}</h3>
              <p className="party-type">
                <span className={`type-badge type-${party.party_type}`}>
                  {party.party_type}
                </span>
              </p>

              <div className="party-details">
                {party.email && (
                  <p className="detail-row">
                    <strong>Email:</strong> {party.email}
                  </p>
                )}
                {party.phone && (
                  <p className="detail-row">
                    <strong>Phone:</strong> {party.phone}
                  </p>
                )}
                {party.country && (
                  <p className="detail-row">
                    <strong>Country:</strong> {party.country}
                  </p>
                )}
                {party.registration_number && (
                  <p className="detail-row">
                    <strong>Reg #:</strong> {party.registration_number}
                  </p>
                )}
              </div>

              <p className="party-status">
                {party.is_active ? (
                  <span className="status-active">Active</span>
                ) : (
                  <span className="status-inactive">Inactive</span>
                )}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
