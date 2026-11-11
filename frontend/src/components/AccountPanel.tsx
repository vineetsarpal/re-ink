/**
 * AccountPanel — modal opened from the sidebar avatar, hosting the WorkOS
 * self-service widgets (Profile / Security / Sessions). All three are scoped to
 * the signed-in user, so one server-minted widget token drives every tab.
 */
import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { isAxiosError } from 'axios';
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
import { X, User, Shield, MonitorSmartphone, LogOut } from 'lucide-react';
import { membersApi, widgetApi } from '@/services/api';

interface AccountPanelProps {
  open: boolean;
  onClose: () => void;
  onLeaveSuccess: () => void;
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

const apiHostname = import.meta.env.VITE_WORKOS_API_HOSTNAME as string | undefined;

export const AccountPanel: React.FC<AccountPanelProps> = ({
  open,
  onClose,
  onLeaveSuccess,
}) => {
  const [tab, setTab] = useState<Tab>('profile');
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [leaveError, setLeaveError] = useState<string | null>(null);

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

  const closeAccount = () => {
    if (!leaveConfirmOpen && !leaving) onClose();
  };

  const closeLeaveConfirmation = () => {
    if (leaving) return;
    setLeaveConfirmOpen(false);
    setLeaveError(null);
  };

  const confirmLeave = async () => {
    setLeaving(true);
    setLeaveError(null);
    try {
      await membersApi.leave();
    } catch (error) {
      const detail = isAxiosError<{ detail?: unknown }>(error)
        ? error.response?.data?.detail
        : null;
      setLeaveError(
        typeof detail === 'string'
          ? detail
          : 'Unable to leave the organization. Please try again.',
      );
      setLeaving(false);
      return;
    }
    onLeaveSuccess();
  };

  // Close on Escape while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (leaveConfirmOpen) {
        if (!leaving) {
          setLeaveConfirmOpen(false);
          setLeaveError(null);
        }
      } else if (!leaving) {
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose, leaveConfirmOpen, leaving]);

  if (!open) return null;

  return createPortal(
    <>
      <div
        className="account-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Account"
        onClick={closeAccount}
      >
        <div className="account-modal__panel" onClick={(e) => e.stopPropagation()}>
          <header className="account-modal__header">
            <h2 className="account-modal__title">Account</h2>
            <button
              type="button"
              className="account-modal__close"
              onClick={closeAccount}
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
              <WorkOsWidgets theme={WIDGET_THEME} apiHostname={apiHostname}>
                {tab === 'profile' && <UserProfile authToken={authToken} />}
                {tab === 'security' && <UserSecurity authToken={authToken} />}
                {/* Fetcher form avoids needing the current session id. */}
                {tab === 'sessions' && (
                  <UserSessions authToken={() => Promise.resolve(authToken)} />
                )}
              </WorkOsWidgets>
            )}

            {tab === 'profile' && (
              <section className="account-leave" aria-labelledby="account-leave-title">
                <h3 id="account-leave-title">Leave organization</h3>
                <p>Remove your access to this organization and sign out of re-ink.</p>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => {
                    setLeaveError(null);
                    setLeaveConfirmOpen(true);
                  }}
                >
                  Leave organization
                </button>
              </section>
            )}
          </div>
        </div>
      </div>

      {leaveConfirmOpen && (
        <div
          className="confirm-modal confirm-modal--account-leave"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="leave-confirm-title"
          aria-describedby="leave-confirm-description"
          onClick={closeLeaveConfirmation}
        >
          <div className="confirm-modal__panel" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-modal__icon" aria-hidden="true">
              <LogOut size={22} />
            </div>
            <div className="confirm-modal__content">
              <h2 id="leave-confirm-title" className="confirm-modal__title">
                Leave organization?
              </h2>
              <p id="leave-confirm-description" className="confirm-modal__description">
                You will immediately lose access to this organization. If this is your
                only organization, your re-ink account will also be deleted. This cannot
                be undone.
              </p>
            </div>
            {leaveError && (
              <p className="confirm-modal__error" role="alert">
                {leaveError}
              </p>
            )}
            <div className="confirm-modal__actions">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={leaving}
                onClick={closeLeaveConfirmation}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={leaving}
                onClick={() => void confirmLeave()}
              >
                {leaving ? 'Leaving…' : 'Leave organization'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>,
    document.body,
  );
};
