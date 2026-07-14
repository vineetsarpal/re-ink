import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { UserPlus, Trash2, Users } from 'lucide-react';
import { membersApi } from '@/services/api';
import type { OrganizationMember, OrganizationRole } from '@/types';

const ROLES: OrganizationRole[] = ['admin', 'member', 'viewer'];
const memberColumnHelper = createColumnHelper<OrganizationMember>();

const errorMessage = (error: any): string =>
  error?.response?.data?.detail ?? error?.message ?? 'Something went wrong. Please try again.';

export const MembersPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<OrganizationRole>('member');
  const [error, setError] = useState<string | null>(null);
  const members = useQuery({ queryKey: ['members'], queryFn: membersApi.list });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['members'] });

  const invite = useMutation({
    mutationFn: () => membersApi.invite(email, role),
    onSuccess: () => { setEmail(''); setRole('member'); setError(null); },
    onError: (err) => setError(errorMessage(err)),
  });
  const updateRole = useMutation({
    mutationFn: ({ id, nextRole }: { id: string; nextRole: OrganizationRole }) =>
      membersApi.updateRole(id, nextRole),
    onSuccess: refresh,
    onError: (err) => setError(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: membersApi.remove,
    onSuccess: refresh,
    onError: (err) => setError(errorMessage(err)),
  });

  const submitInvite = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    invite.mutate();
  };

  const memberColumns = useMemo(() => [
    memberColumnHelper.display({
      id: 'name',
      header: 'Name',
      cell: ({ row }) => [row.original.first_name, row.original.last_name].filter(Boolean).join(' ') || '—',
    }),
    memberColumnHelper.accessor('email', {
      header: 'Email',
      cell: ({ getValue }) => getValue() ?? '—',
    }),
    memberColumnHelper.accessor('role', {
      header: 'Role',
      cell: ({ row, getValue }) => (
        <select
          aria-label={`Role for ${row.original.email ?? row.original.user_id}`}
          value={getValue()}
          disabled={updateRole.isPending}
          onChange={(event) => updateRole.mutate({ id: row.original.id, nextRole: event.target.value as OrganizationRole })}
        >
          {ROLES.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      ),
    }),
    memberColumnHelper.display({
      id: 'actions',
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <button
          className="btn btn-secondary members-remove"
          aria-label={`Remove ${row.original.email ?? row.original.user_id}`}
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Remove ${row.original.email ?? 'this member'} from the workspace?`)) {
              remove.mutate(row.original.id);
            }
          }}
        >
          <Trash2 size={16} /> Remove
        </button>
      ),
    }),
  ], [remove, updateRole]);

  const membersTable = useReactTable({
    data: members.data ?? [],
    columns: memberColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return <div className="members-page">
    <header className="page-header">
      <div><h1>Members</h1><p>Invite teammates and manage their access to this workspace.</p></div>
    </header>
    <section className="members-card">
      <h2><UserPlus size={20} /> Invite a teammate</h2>
      <form className="member-invite" onSubmit={submitInvite}>
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required placeholder="teammate@company.com" /></label>
        <label>Role<select value={role} onChange={(event) => setRole(event.target.value as OrganizationRole)}>{ROLES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <button className="btn btn-primary" disabled={invite.isPending}>{invite.isPending ? 'Sending…' : 'Send invitation'}</button>
      </form>
    </section>
    {error && <div className="members-error" role="alert">{error}</div>}
    <section className="members-card">
      <h2><Users size={20} /> Workspace members</h2>
      {members.isLoading && <p>Loading members…</p>}
      {members.isError && <div className="members-error" role="alert">Unable to load members. <button className="btn btn-secondary" onClick={() => void members.refetch()}>Try again</button></div>}
      {members.data && <div className="members-table-wrap"><table><thead>
        {membersTable.getHeaderGroups().map((headerGroup) => <tr key={headerGroup.id}>
          {headerGroup.headers.map((header) => <th key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</th>)}
        </tr>)}
      </thead><tbody>
        {membersTable.getRowModel().rows.map((row) => <tr key={row.id}>
          {row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
        </tr>)}
      </tbody></table></div>}
    </section>
  </div>;
};
