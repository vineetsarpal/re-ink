/**
 * Layout component with navigation and header.
 */
import React from 'react';
import { Link, useLocation, Outlet } from 'react-router-dom';
import { FileText, Upload, Users, LayoutDashboard } from 'lucide-react';

export const Layout: React.FC = () => {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="app-layout">
      {/* Sidebar Navigation */}
      <nav className="sidebar">
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
          <p className="version-info">Version 1.0.0</p>
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
