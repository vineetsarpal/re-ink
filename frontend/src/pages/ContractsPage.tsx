/**
 * ContractsPage - List and manage all contracts.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Search, Filter, Plus } from 'lucide-react';
import { contractApi } from '@/services/api';
import type { Contract } from '@/types';

const contractColumnHelper = createColumnHelper<Contract>();

const formatContractSubType = (subType?: string) => subType
  ? subType.split('_').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
  : 'N/A';

export const ContractsPage: React.FC = () => {
  const navigate = useNavigate();
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  const loadContracts = useCallback(async () => {
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
  }, [statusFilter]);

  useEffect(() => {
    void loadContracts();
  }, [loadContracts]);

  const filteredContracts = contracts.filter((contract) => {
    const matchesSearch =
      contract.contract_number.toLowerCase().includes(searchTerm.toLowerCase()) ||
      contract.contract_name.toLowerCase().includes(searchTerm.toLowerCase());
    // Show all contracts including inactive ones (is_active field will be indicated by badge)
    return matchesSearch;
  });


  const contractColumns = useMemo(() => [
    contractColumnHelper.accessor('contract_number', { header: 'Contract Number' }),
    contractColumnHelper.accessor('contract_name', { header: 'Name' }),
    contractColumnHelper.accessor('contract_type', {
      header: 'Type',
      cell: ({ getValue }) => getValue() || 'N/A',
    }),
    contractColumnHelper.accessor('contract_sub_type', {
      header: 'Sub-Type',
      cell: ({ getValue }) => formatContractSubType(getValue()),
    }),
    contractColumnHelper.display({
      id: 'status',
      header: 'Status',
      cell: ({ row }) => !row.original.is_active ? (
        <span className="badge badge-inactive">Inactive</span>
      ) : (
        <span className={`status-badge status-${row.original.status}`}>{row.original.status}</span>
      ),
    }),
    contractColumnHelper.accessor('effective_date', {
      header: 'Effective Date',
      cell: ({ getValue }) => new Date(getValue()).toLocaleDateString(),
    }),
    contractColumnHelper.accessor('expiration_date', {
      header: 'Expiration Date',
      cell: ({ getValue }) => new Date(getValue()).toLocaleDateString(),
    }),
    contractColumnHelper.display({
      id: 'premium_amount',
      header: 'Premium Amount',
      cell: ({ row }) => row.original.premium_amount
        ? `${row.original.currency} ${row.original.premium_amount.toLocaleString()}`
        : 'N/A',
    }),
    contractColumnHelper.accessor('review_status', {
      header: 'Review Status',
      cell: ({ getValue }) => <span className={`status-badge review-${getValue()}`}>{getValue()}</span>,
    }),
  ], []);

  const contractsTable = useReactTable({
    data: filteredContracts,
    columns: contractColumns,
    getCoreRowModel: getCoreRowModel(),
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
              {contractsTable.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {contractsTable.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => navigate(`/contracts/${row.original.id}`)}
                  className="clickable"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
