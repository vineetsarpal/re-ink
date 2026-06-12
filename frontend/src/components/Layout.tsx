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
  X,
} from 'lucide-react';
import { SecondarySidebarProvider } from '@/components/SecondarySidebar';

const NAV_COLLAPSED_KEY = 'reink-nav-collapsed';

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { to: '/upload', label: 'Upload Document', Icon: Upload },
  { to: '/contracts', label: 'Contracts', Icon: FileText },
  { to: '/parties', label: 'Parties', Icon: Users },
] as const;

export const Layout: React.FC = () => {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
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
          <div className="mobile-topbar__logo">
            <FileText size={18} strokeWidth={2.5} />
          </div>
          <span>Re-ink</span>
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
          <Link to="/" className="logo-link" title={navCollapsed ? 'Re-ink' : undefined}>
            <div className="logo-icon">
              <FileText size={28} strokeWidth={2.5} />
            </div>
            <div className="logo-text">
              <h1 className="app-title">Re-ink</h1>
              <p className="app-subtitle">AI-Powered Reinsurance</p>
            </div>
          </Link>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={toggleNav}
            aria-label={navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!navCollapsed}
            title={navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <PanelLeft size={18} />
          </button>
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
        </ul>

        <div className="sidebar-footer">
          <p className="version-info">Version {__APP_VERSION__}</p>
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
    </div>
  );
};
