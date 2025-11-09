/**
 * Layout component with navigation and header.
 */
import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { FileText, Upload, Users, LayoutDashboard } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="app-layout">
      {/* Sidebar Navigation */}
      <nav className="sidebar">
        <div className="sidebar-header">
          <h1 className="app-title">re-ink</h1>
          <p className="app-subtitle">Contract Management</p>
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
        <div className="content-wrapper">{children}</div>
      </main>
    </div>
  );
};
