/**
 * PartiesPage - List and manage all parties.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Mail, Phone, MapPin, Hash } from 'lucide-react';
import { partyApi } from '@/services/api';
import type { Party } from '@/types';

export const PartiesPage: React.FC = () => {
  const navigate = useNavigate();
  const [parties, setParties] = useState<Party[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    loadParties();
  }, []);

  const loadParties = async () => {
    setIsLoading(true);
    try {
      const data = await partyApi.getAll();
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
    // Show all parties including inactive ones (is_active field determines badge)
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
              <div className="party-card__top">
                <h3 className="party-card__name">{party.name}</h3>
                <span
                  className={`party-card__status ${
                    party.is_active ? 'is-active' : 'is-inactive'
                  }`}
                  title={party.is_active ? 'Active' : 'Inactive'}
                >
                  <span className="party-card__status-dot" />
                  {party.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>

              <ul className="party-card__meta">
                {party.email && (
                  <li>
                    <Mail size={14} />
                    <span>{party.email}</span>
                  </li>
                )}
                {party.phone && (
                  <li>
                    <Phone size={14} />
                    <span>{party.phone}</span>
                  </li>
                )}
                {party.country && (
                  <li>
                    <MapPin size={14} />
                    <span>{party.country}</span>
                  </li>
                )}
                {party.registration_number && (
                  <li>
                    <Hash size={14} />
                    <span>{party.registration_number}</span>
                  </li>
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
