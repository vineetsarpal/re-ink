import React, { useEffect, useState } from 'react';
import { Building2, KeyRound, Network, ShieldCheck } from 'lucide-react';
import { useAuth } from '@workos-inc/authkit-react';
import { organizationApi, adminApi, providerCredentialApi, systemApi, type AdminPortalIntent } from '@/services/api';

const ACTIONS: { intent: AdminPortalIntent; title: string; description: string; Icon: typeof KeyRound }[] = [
  { intent: 'sso', title: 'Connect identity provider', description: 'Set up SAML or OpenID Connect single sign-on.', Icon: KeyRound },
  { intent: 'dsync', title: 'Connect directory', description: 'Sync members and group-based roles with SCIM.', Icon: Network },
  { intent: 'domain_verification', title: 'Verify domain', description: 'Verify your company domain for secure onboarding and sign-in routing.', Icon: ShieldCheck },
];

export const OrganizationSettingsPage: React.FC = () => {
  const { permissions } = useAuth();
  const canManageKeys = permissions.includes('member:manage');
  const [closeConfirmation, setCloseConfirmation] = useState('');
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [loading, setLoading] = useState<AdminPortalIntent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [credentialConfigured, setCredentialConfigured] = useState<boolean | null>(null);
  const [credentialEnabled, setCredentialEnabled] = useState(false);
  const [credentialKey, setCredentialKey] = useState('');
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [credentialMessage, setCredentialMessage] = useState<string | null>(null);
  const [credentialError, setCredentialError] = useState<string | null>(null);
  useEffect(() => {
    systemApi.getConfig().then(async (config) => {
      setCredentialEnabled(config.provider_credentials_enabled);
      if (config.provider_credentials_enabled && canManageKeys) setCredentialConfigured((await providerCredentialApi.get()).configured);
    })
      .catch(() => setCredentialError('Unable to load LandingAI key settings.'));
  }, [canManageKeys]);
  const saveCredential = async (event: React.FormEvent) => {
    event.preventDefault(); setCredentialBusy(true); setCredentialError(null); setCredentialMessage(null);
    try {
      const status = await providerCredentialApi.save(credentialKey);
      setCredentialConfigured(status.configured); setCredentialKey(''); setCredentialMessage('LandingAI key saved.');
    } catch (err: any) {
      setCredentialError(err?.response?.status === 422 ? 'LandingAI could not authenticate this key.' : 'Unable to validate or save the key. Please try again.');
    } finally { setCredentialBusy(false); }
  };
  const removeCredential = async () => {
    setCredentialBusy(true); setCredentialError(null); setCredentialMessage(null);
    try { await providerCredentialApi.remove(); setCredentialConfigured(false); setCredentialKey(''); setCredentialMessage('LandingAI key removed.'); }
    catch { setCredentialError('Unable to remove the key. Please try again.'); }
    finally { setCredentialBusy(false); }
  };
  const openPortal = async (intent: AdminPortalIntent) => {
    setLoading(intent); setError(null);
    try { window.location.assign(await adminApi.getPortalLink(intent)); }
    catch (err: any) { setError(err?.response?.data?.detail ?? 'Unable to open the WorkOS Admin Portal. Please try again.'); setLoading(null); }
  };
  return <div className="organization-settings-page">
    <header className="page-header"><div><h1>Organization settings</h1><p>Manage extraction and secure access for your workspace.</p></div></header>
    {credentialEnabled && permissions.includes('member:manage') && <section className="members-card"><h2><KeyRound size={20} /> LandingAI key</h2>
      <p>{credentialConfigured === null ? 'Checking key settings…' : credentialConfigured ? 'A key is saved for your organization.' : 'No organization key is saved.'}</p>
      <p>Get an API key from your <a href="https://landing.ai/" target="_blank" rel="noreferrer">LandingAI account</a>. Usage with your key is charged to your LandingAI account.</p>
      {credentialError && <p className="members-error" role="alert">{credentialError}</p>}
      {credentialMessage && <p role="status">{credentialMessage}</p>}
      <form className="provider-key-form" onSubmit={(event) => void saveCredential(event)}>
        <label htmlFor="landingai-key">{credentialConfigured ? 'Replace API key' : 'API key'}</label>
        <input id="landingai-key" type="password" autoComplete="off" value={credentialKey} onChange={(event) => setCredentialKey(event.target.value)} />
        <button className="btn btn-primary" type="submit" disabled={credentialBusy || !credentialKey.trim()}>Save key</button>
        {credentialConfigured && <button className="btn btn-secondary" type="button" disabled={credentialBusy} onClick={() => void removeCredential()}>Remove key</button>}
      </form>
    </section>}
    {error && <div className="members-error" role="alert">{error}</div>}
    {permissions.includes('sso:manage') && <section className="members-card"><h2><Building2 size={20} /> Enterprise identity</h2><div className="settings-actions">
      {ACTIONS.map(({ intent, title, description, Icon }) => <article key={intent} className="settings-action"><Icon size={22} /><div><h3>{title}</h3><p>{description}</p></div><button className="btn btn-primary" disabled={loading !== null} onClick={() => void openPortal(intent)}>{loading === intent ? 'Opening…' : 'Configure'}</button></article>)}
    </div></section>}
    {permissions.includes('organization:close') && <section className="members-card" aria-labelledby="close-organization-heading">
      <h2 id="close-organization-heading">Close organization</h2>
      <p>Access stops immediately. Organization data is scheduled for deletion after 30 days. You can cancel closure before that date. Cancelled extractions will not restart.</p>
      <p>Provider-side copies are governed by LandingAI’s terms.</p>
      <form onSubmit={async (event) => {
        event.preventDefault(); setClosing(true); setCloseError(null);
        try { await organizationApi.close(closeConfirmation); }
        catch (error: any) { setCloseError(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'Unable to close organization. Please try again.'); }
        finally { setClosing(false); }
      }}>
        <label htmlFor="close-confirmation">Type CLOSE to confirm organization closure</label>
        <input id="close-confirmation" autoComplete="off" value={closeConfirmation} onChange={(event) => setCloseConfirmation(event.target.value)} />
        <button className="btn btn-danger" type="submit" disabled={closing || closeConfirmation !== 'CLOSE'}>{closing ? 'Closing…' : 'Close organization'}</button>
        {closeError && <p role="alert">{closeError}</p>}
      </form>
    </section>}
  </div>;
};
