/**
 * Layout component with navigation and header.
 *
 * Sidebar is a fixed column on desktop and an off-canvas drawer on mobile.
 * The drawer is toggled by a hamburger button in the mobile top bar, and
 * auto-closes whenever the route changes so navigation doesn't leave it open.
 *
 * On desktop the sidebar also collapses to an icon-only rail (persisted in
 * localStorage). A secondary sidebar slot sits between the nav and the main
 * content; pages project contextual panels into it (see SecondarySidebar).
 */
import React, { useEffect, useState } from 'react';
import { Link, useLocation, Outlet } from 'react-router-dom';
import {
  FileText,
  Upload,
  Users,
  LayoutDashboard,
  Menu,
  PanelLeft,
  LogOut,
  X,
  Settings,
} from 'lucide-react';
import { useAuth } from '@workos-inc/authkit-react';
import { SecondarySidebarProvider } from '@/components/SecondarySidebar';
import { organizationApi, type OrganizationLifecycle } from '@/services/api';
import { AccountPanel } from '@/components/AccountPanel';
import logoMark from '@/assets/logo-mark-small.png';
import logoWordmark from '@/assets/logo-wordmark-small.png';

const NAV_COLLAPSED_KEY = 'reink-nav-collapsed';

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { to: '/upload', label: 'Upload Document', Icon: Upload },
  { to: '/contracts', label: 'Contracts', Icon: FileText },
  { to: '/parties', label: 'Parties', Icon: Users },
] as const;

const displayVersion = __APP_VERSION__.split('.').slice(0, 2).join('.');

export const Layout: React.FC = () => {
  const location = useLocation();
  const { user, signOut, permissions, organizationId } = useAuth();
  const [lifecycle, setLifecycle] = useState<OrganizationLifecycle | null>(null);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    let active = true;
    let version = 0;
    setLifecycle(null);
    setLifecycleError(null);
    const refresh = () => {
      const requestVersion = ++version;
      return organizationApi.lifecycle().then((value) => {
        if (active && version === requestVersion) { setLifecycle(value); setLifecycleError(null); }
      }).catch(() => { if (active && version === requestVersion) setLifecycleError('Unable to check organization status. Please refresh and try again.'); });
    };
    const changed = (event: Event) => {
      version += 1;
      if (active) setLifecycle((event as CustomEvent<OrganizationLifecycle>).detail);
    };
    window.addEventListener('organization-lifecycle', changed);
    window.addEventListener('focus', refresh);
    void refresh();
    const interval = window.setInterval(refresh, 30000);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener('organization-lifecycle', changed);
      window.removeEventListener('focus', refresh);
    };
  }, [organizationId]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [signOutConfirmOpen, setSignOutConfirmOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(
    () => localStorage.getItem(NAV_COLLAPSED_KEY) === '1',
  );

  // Secondary sidebar slot: host element + how many panels project into it.
  const [slotHost, setSlotHost] = useState<HTMLElement | null>(null);
  const [slotOccupants, setSlotOccupants] = useState(0);

  const isActive = (path: string) => location.pathname === path;

  const toggleNav = () => {
    setNavCollapsed((collapsed) => {
      const next = !collapsed;
      localStorage.setItem(NAV_COLLAPSED_KEY, next ? '1' : '0');
      return next;
    });
  };

  const handleSignOut = () => {
    setSignOutConfirmOpen(true);
  };

  const confirmSignOut = () => {
    setSignOutConfirmOpen(false);
    // WorkOS redirects to the configured App homepage. Avoid a custom
    // `returnTo`, which would require a separate Sign-out redirect allowlist.
    signOut();
  };

  // Close the drawer whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  // Prevent background scroll while the drawer is open on mobile.
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileOpen]);

  useEffect(() => {
    if (!signOutConfirmOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSignOutConfirmOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [signOutConfirmOpen]);

  if (!lifecycle) return <main className="page-container"><p role={lifecycleError ? 'alert' : 'status'}>{lifecycleError ?? 'Checking organization status…'}</p></main>;
  if (lifecycle.status !== 'active') return <main className="page-container">
    <section className="members-card">
      <h1>{lifecycle.status === 'closing' ? 'This organization is closing' : 'This organization has been closed'}</h1>
      {lifecycle.purge_after && <p>Scheduled deletion: {new Date(lifecycle.purge_after).toLocaleString()}.</p>}
      <p>Provider-side copies are governed by LandingAI’s terms.</p>
      {lifecycleError && <p role="alert">{lifecycleError}</p>}
      {permissions.includes('organization:close') && lifecycle.status === 'closing' && <button
        className="btn btn-primary" disabled={cancelling || (!!lifecycle.purge_after && Date.now() >= Date.parse(lifecycle.purge_after))}
        onClick={async () => {
          setCancelling(true); setLifecycleError(null);
          try { setLifecycle(await organizationApi.cancelClosure()); }
          catch (error: any) { setLifecycleError(error.response?.data?.detail ?? 'Unable to cancel closure. Please try again.'); }
          finally { setCancelling(false); }
        }}>{cancelling ? 'Cancelling…' : 'Cancel closure'}</button>}
      <button className="btn btn-secondary" onClick={() => signOut()}>Sign out</button>
    </section>
  </main>;

  return (
    <div className={`app-layout ${mobileOpen ? 'app-layout--drawer-open' : ''}`}>
      {/* Mobile top bar — visible only on narrow screens via CSS. */}
      <header className="mobile-topbar">
        <button
          type="button"
          className="mobile-topbar__menu-btn"
          aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
          aria-expanded={mobileOpen}
          aria-controls="primary-sidebar"
          onClick={() => setMobileOpen((o) => !o)}
        >
          {mobileOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
        <Link to="/" className="mobile-topbar__brand">
          <img className="mobile-topbar__logo" src={logoMark} alt="" />
          <span>re-ink</span>
        </Link>
      </header>

      {/* Scrim — only rendered while drawer is open so it captures taps. */}
      {mobileOpen && (
        <div
          className="sidebar-scrim"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Navigation */}
      <nav
        id="primary-sidebar"
        className={`sidebar ${mobileOpen ? 'sidebar--open' : ''} ${
          navCollapsed ? 'sidebar--collapsed' : ''
        }`}
        aria-hidden={mobileOpen ? false : undefined}
      >
        <div className="sidebar-header">
          {navCollapsed ? (
            <div className="collapsed-logo-control">
              <img className="logo-mark" src={logoMark} alt="re-ink" />
              <button
                type="button"
                className="sidebar-toggle sidebar-toggle--collapsed"
                onClick={toggleNav}
                aria-label="Expand sidebar"
                aria-expanded={false}
                title="Expand sidebar"
              >
                <PanelLeft size={18} />
              </button>
            </div>
          ) : (
            <>
              <Link to="/" className="logo-link">
                <div className="logo-text">
                  <img className="logo-lockup" src={logoWordmark} alt="re-ink" />
                </div>
              </Link>
              <button
                type="button"
                className="sidebar-toggle"
                onClick={toggleNav}
                aria-label="Collapse sidebar"
                aria-expanded={true}
                title="Collapse sidebar"
              >
                <PanelLeft size={18} />
              </button>
            </>
          )}
        </div>

        <ul className="nav-menu">
          {NAV_ITEMS.map(({ to, label, Icon }) => (
            <li key={to}>
              <Link
                to={to}
                className={`nav-link ${isActive(to) ? 'active' : ''}`}
                title={navCollapsed ? label : undefined}
              >
                <Icon size={20} />
                <span>{label}</span>
              </Link>
            </li>
          ))}
          {permissions.includes('member:manage') && (
            <li><Link to="/members" className={`nav-link ${isActive('/members') ? 'active' : ''}`} title={navCollapsed ? 'Members' : undefined}><Users size={20} /><span>Members</span></Link></li>
          )}
          {['sso:manage', 'member:manage', 'organization:close'].some((permission) => permissions.includes(permission)) && (
            <li><Link to="/organization-settings" className={`nav-link ${isActive('/organization-settings') ? 'active' : ''}`} title={navCollapsed ? 'Organization settings' : undefined}><Settings size={20} /><span>Organization settings</span></Link></li>
          )}
        </ul>

        <div className="sidebar-footer">
          {user && (
            <>
              <button
                type="button"
                className="sidebar-user sidebar-user--button"
                title={user.email ?? undefined}
                aria-label="Open account"
                aria-haspopup="dialog"
                onClick={() => setAccountOpen(true)}
              >
                {user.profilePictureUrl ? (
                  <img
                    src={user.profilePictureUrl}
                    alt=""
                    className="sidebar-user__avatar"
                  />
                ) : (
                  <span className="sidebar-user__avatar sidebar-user__avatar--fallback">
                    {(user.firstName?.[0] ?? user.email?.[0] ?? '?').toUpperCase()}
                  </span>
                )}
                {!navCollapsed && (
                  <span className="sidebar-user__name">
                    {user.firstName
                      ? `${user.firstName} ${user.lastName ?? ''}`.trim()
                      : user.email}
                  </span>
                )}
              </button>
              <button
                type="button"
                className="nav-link sign-out-btn"
                onClick={handleSignOut}
                title={navCollapsed ? 'Sign out' : undefined}
              >
                <LogOut size={20} />
                <span>Sign out</span>
              </button>
            </>
          )}
          <p className="version-info">
            {navCollapsed ? `v${displayVersion}` : `Version ${displayVersion}`}
          </p>
        </div>
      </nav>

      {/* Secondary sidebar slot — flush against the nav; pages project
          contextual panels (e.g. source grounding) into it via a portal. */}
      <aside
        ref={setSlotHost}
        className={`secondary-sidebar ${
          slotOccupants > 0 ? '' : 'secondary-sidebar--empty'
        }`}
        aria-label="Contextual panel"
      />

      {/* Main Content Area */}
      <main className="main-content">
        <div className="content-wrapper">
          <SecondarySidebarProvider
            value={{ host: slotHost, setOccupants: setSlotOccupants }}
          >
            <Outlet />
          </SecondarySidebarProvider>
        </div>
      </main>

      <AccountPanel
        open={accountOpen}
        onClose={() => setAccountOpen(false)}
        onLeaveSuccess={() => signOut()}
      />

      {signOutConfirmOpen && (
        <div
          className="confirm-modal"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="sign-out-confirm-title"
          aria-describedby="sign-out-confirm-description"
          onClick={() => setSignOutConfirmOpen(false)}
        >
          <div className="confirm-modal__panel" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-modal__icon" aria-hidden="true">
              <LogOut size={22} />
            </div>
            <div className="confirm-modal__content">
              <h2 id="sign-out-confirm-title" className="confirm-modal__title">
                Sign out?
              </h2>
              <p id="sign-out-confirm-description" className="confirm-modal__description">
                You'll need to sign in again to access your contracts, parties, and
                document review workspace.
              </p>
            </div>
            <div className="confirm-modal__actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setSignOutConfirmOpen(false)}
              >
                Cancel
              </button>
              <button type="button" className="btn btn-danger" onClick={confirmSignOut}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
