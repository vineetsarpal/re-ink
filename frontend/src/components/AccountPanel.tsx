/**
 * AccountPanel — modal opened from the sidebar avatar, hosting the WorkOS
 * self-service widgets (Profile / Security / Sessions). All three are scoped to
 * the signed-in user, so one server-minted widget token drives every tab.
 */
import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import {
  WorkOsWidgets,
  UserProfile,
  UserSecurity,
  UserSessions,
  type WorkOsWidgetsProps,
} from '@workos-inc/widgets';
// Radix Themes CSS (widgets' peer dep) must load before the widget styles.
import '@radix-ui/themes/styles.css';
import '@workos-inc/widgets/styles.css';
import { X, User, Shield, MonitorSmartphone } from 'lucide-react';
import { widgetApi } from '@/services/api';

interface AccountPanelProps {
  open: boolean;
  onClose: () => void;
}

type Tab = 'profile' | 'security' | 'sessions';

const TABS: { id: Tab; label: string; Icon: typeof User }[] = [
  { id: 'profile', label: 'Profile', Icon: User },
  { id: 'security', label: 'Security', Icon: Shield },
  { id: 'sessions', label: 'Sessions', Icon: MonitorSmartphone },
];

// Match the widgets' Radix theme to re-ink's tokens.
const WIDGET_THEME: WorkOsWidgetsProps['theme'] = {
  appearance: 'light',
  accentColor: 'blue',
  grayColor: 'slate',
  radius: 'medium',
  fontFamily: 'inherit',
};

export const AccountPanel: React.FC<AccountPanelProps> = ({ open, onClose }) => {
  const [tab, setTab] = useState<Tab>('profile');

  // Widget tokens live ~1 hour; only fetch while the panel is open.
  const {
    data: authToken,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['userProfileWidgetToken'],
    queryFn: widgetApi.getUserProfileToken,
    enabled: open,
    staleTime: 50 * 60 * 1000,
  });

  // Close on Escape while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="account-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Account"
      onClick={onClose}
    >
      <div className="account-modal__panel" onClick={(e) => e.stopPropagation()}>
        <header className="account-modal__header">
          <h2 className="account-modal__title">Account</h2>
          <button
            type="button"
            className="account-modal__close"
            onClick={onClose}
            aria-label="Close account panel"
          >
            <X size={20} />
          </button>
        </header>

        <nav className="account-modal__tabs" aria-label="Account sections">
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              className={`account-modal__tab ${tab === id ? 'is-active' : ''}`}
              aria-current={tab === id ? 'page' : undefined}
              onClick={() => setTab(id)}
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="account-modal__body">
          {isLoading && <p className="account-modal__status">Loading your account…</p>}

          {isError && (
            <div className="account-modal__status account-modal__status--error">
              <p>We couldn’t load your account.</p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void refetch()}
              >
                Try again
              </button>
            </div>
          )}

          {authToken && (
            <WorkOsWidgets theme={WIDGET_THEME}>
              {tab === 'profile' && <UserProfile authToken={authToken} />}
              {tab === 'security' && <UserSecurity authToken={authToken} />}
              {/* Fetcher form avoids needing the current session id. */}
              {tab === 'sessions' && (
                <UserSessions authToken={() => Promise.resolve(authToken)} />
              )}
            </WorkOsWidgets>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
};
