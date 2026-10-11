import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { Plane, LogOut } from 'lucide-react';

export default function Navbar() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  if (!user) return null;

  const role = user.role || 'hospital';
  const isHospital = role === 'hospital' || role === 'hospital_admin';
  const isOperator = role === 'operator';
  const isAdmin = role === 'admin' || role === 'system_admin';

  const roleHome = isHospital ? '/' : '/operator';

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header className="top-navbar">
      <div className="navbar-inner">
        {/* Brand */}
        <NavLink to={roleHome} className="brand-link" id="brand-link">
          <div className="brand-icon">
            <Plane size={20} strokeWidth={2.5} />
          </div>
          <span>AeroMedical</span>
        </NavLink>

        {/* Navigation Links for Role Only */}
        <nav className="nav-links-group" id="nav-links-group">
          {isHospital && (
            <>
              <NavLink
                to="/"
                end
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-dashboard"
              >
                Dashboard
              </NavLink>
              <NavLink
                to="/requests/new"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-new-request"
              >
                New Request
              </NavLink>
              <NavLink
                to="/requests"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-my-requests"
              >
                My Requests
              </NavLink>
              <NavLink
                to="/fleet"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-fleet"
              >
                Fleet
              </NavLink>
            </>
          )}

          {isOperator && (
            <>
              <NavLink
                to="/operator"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-operator"
              >
                Dispatch Console
              </NavLink>
              <NavLink
                to="/fleet"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-fleet"
              >
                Fleet
              </NavLink>
            </>
          )}

          {isAdmin && (
            <>
              <NavLink
                to="/operator"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-operator"
              >
                Dispatch Console
              </NavLink>
              <NavLink
                to="/fleet"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-fleet"
              >
                Fleet
              </NavLink>
              <NavLink
                to="/admin"
                className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
                id="nav-admin"
              >
                Analytics
              </NavLink>
            </>
          )}
        </nav>

        {/* User Info & Logout */}
        <div className="nav-user-controls">
          <div className="user-badge" id="user-badge">
            <span className="user-email" title={user.email}>{user.email}</span>
            <span className="user-role-pill">{user.role}</span>
          </div>
          <button
            className="btn-logout"
            onClick={handleLogout}
            id="logout-btn"
            title="Log out and clear session"
          >
            <LogOut size={14} />
            <span>Logout</span>
          </button>
        </div>
      </div>
    </header>
  );
}
