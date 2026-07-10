import React, { useState } from 'react';
import { Building2, KeyRound, Network, ShieldCheck } from 'lucide-react';
import { adminApi, type AdminPortalIntent } from '@/services/api';

const ACTIONS: { intent: AdminPortalIntent; title: string; description: string; Icon: typeof KeyRound }[] = [
  { intent: 'sso', title: 'Connect identity provider', description: 'Set up SAML or OpenID Connect single sign-on.', Icon: KeyRound },
  { intent: 'dsync', title: 'Connect directory', description: 'Sync members and group-based roles with SCIM.', Icon: Network },
  { intent: 'domain_verification', title: 'Verify domain', description: 'Verify your company domain for secure onboarding and sign-in routing.', Icon: ShieldCheck },
];

export const OrganizationSettingsPage: React.FC = () => {
  const [loading, setLoading] = useState<AdminPortalIntent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const openPortal = async (intent: AdminPortalIntent) => {
    setLoading(intent); setError(null);
    try { window.location.assign(await adminApi.getPortalLink(intent)); }
    catch (err: any) { setError(err?.response?.data?.detail ?? 'Unable to open the WorkOS Admin Portal. Please try again.'); setLoading(null); }
  };
  return <div className="organization-settings-page">
    <header className="page-header"><div><h1>Organization settings</h1><p>Configure enterprise identity and secure access for your workspace.</p></div></header>
    {error && <div className="members-error" role="alert">{error}</div>}
    <section className="members-card"><h2><Building2 size={20} /> Enterprise identity</h2><div className="settings-actions">
      {ACTIONS.map(({ intent, title, description, Icon }) => <article key={intent} className="settings-action"><Icon size={22} /><div><h3>{title}</h3><p>{description}</p></div><button className="btn btn-primary" disabled={loading !== null} onClick={() => void openPortal(intent)}>{loading === intent ? 'Opening…' : 'Configure'}</button></article>)}
    </div></section>
  </div>;
};
