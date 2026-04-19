/**
 * Layout component with navigation and header.
 *
 * Sidebar is a fixed column on desktop and an off-canvas drawer on mobile.
 * The drawer is toggled by a hamburger button in the mobile top bar, and
 * auto-closes whenever the route changes so navigation doesn't leave it open.
 */
import React, { useEffect, useState } from 'react';
import { Link, useLocation, Outlet } from 'react-router-dom';
import { FileText, Upload, Users, LayoutDashboard, Menu, X } from 'lucide-react';

export const Layout: React.FC = () => {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const isActive = (path: string) => location.pathname === path;

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
        className={`sidebar ${mobileOpen ? 'sidebar--open' : ''}`}
        aria-hidden={mobileOpen ? false : undefined}
      >
        <div className="sidebar-header">
          <Link to="/" className="logo-link">
            <div className="logo-icon">
              <FileText size={28} strokeWidth={2.5} />
            </div>
            <div className="logo-text">
              <h1 className="app-title">Re-ink</h1>
              <p className="app-subtitle">AI-Powered Reinsurance</p>
            </div>
          </Link>
        </div>

        <ul className="nav-menu">
          <li>
            <Link
              to="/dashboard"
              className={`nav-link ${isActive('/dashboard') ? 'active' : ''}`}
            >
              <LayoutDashboard size={20} />
              <span>Dashboard</span>
            </Link>
          </li>

          <li>
            <Link
              to="/upload"
              className={`nav-link ${isActive('/upload') ? 'active' : ''}`}
            >
              <Upload size={20} />
              <span>Upload Document</span>
            </Link>
          </li>

          <li>
            <Link
              to="/contracts"
              className={`nav-link ${isActive('/contracts') ? 'active' : ''}`}
            >
              <FileText size={20} />
              <span>Contracts</span>
            </Link>
          </li>

          <li>
            <Link
              to="/parties"
              className={`nav-link ${isActive('/parties') ? 'active' : ''}`}
            >
              <Users size={20} />
              <span>Parties</span>
            </Link>
          </li>
        </ul>

        <div className="sidebar-footer">
          <p className="version-info">Version {__APP_VERSION__}</p>
        </div>
      </nav>

      {/* Main Content Area */}
      <main className="main-content">
        <div className="content-wrapper">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
