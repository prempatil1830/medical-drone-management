import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { Button } from './ui/Button';
import { Plane, LogOut } from 'lucide-react';

export default function Navbar() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  if (!user) return null;

  return (
    <nav className="navbar">
      <div className="navbar-container">
        <NavLink to="/" className="navbar-brand" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Plane size={24} color="var(--accent-color)" strokeWidth={2} />
          <span>AeroMedical</span>
        </NavLink>
        
        <div className="navbar-links">
          <NavLink 
            to="/" 
            end
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            Dashboard
          </NavLink>
          <NavLink 
            to="/requests" 
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            Submit Request
          </NavLink>
          <NavLink 
            to="/request-queue" 
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            Request Queue
          </NavLink>
          <NavLink 
            to="/fleet" 
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            Fleet Dashboard
          </NavLink>

          <div className="flex items-center gap-4" style={{ marginLeft: '1rem' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {user.email}
            </span>
            <Button variant="secondary" onClick={handleLogout} style={{ padding: '4px 12px', minHeight: '32px', minWidth: '32px' }}>
              <LogOut size={16} />
              Logout
            </Button>
          </div>
        </div>
      </div>
    </nav>
  );
}
