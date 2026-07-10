import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { UserPlus, Trash2, Users } from 'lucide-react';
import { membersApi } from '@/services/api';
import type { OrganizationRole } from '@/types';

const ROLES: OrganizationRole[] = ['admin', 'member', 'viewer'];

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
      {members.data && <div className="members-table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th aria-label="Actions" /></tr></thead><tbody>
        {members.data.map((member) => <tr key={member.id}>
          <td>{[member.first_name, member.last_name].filter(Boolean).join(' ') || '—'}</td>
          <td>{member.email ?? '—'}</td>
          <td><select aria-label={`Role for ${member.email ?? member.user_id}`} value={member.role} disabled={updateRole.isPending} onChange={(event) => updateRole.mutate({ id: member.id, nextRole: event.target.value as OrganizationRole })}>{ROLES.map((item) => <option key={item} value={item}>{item}</option>)}</select></td>
          <td><button className="btn btn-secondary members-remove" aria-label={`Remove ${member.email ?? member.user_id}`} disabled={remove.isPending} onClick={() => { if (window.confirm(`Remove ${member.email ?? 'this member'} from the workspace?`)) remove.mutate(member.id); }}><Trash2 size={16} /> Remove</button></td>
        </tr>)}
      </tbody></table></div>}
    </section>
  </div>;
};
