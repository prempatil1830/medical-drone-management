import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Plane, AlertCircle } from 'lucide-react';
import { useAuthStore } from '../store/auth';
import api from '../services/api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const setAuth = useAuthStore((state) => state.setAuth);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await api.post('/auth/login', { email, password });
      const { access_token, user } = response.data;
      setAuth(access_token, user);
      if (user?.role === 'operator' || user?.role === 'admin' || user?.role === 'system_admin') {
        navigate('/operator');
      } else {
        navigate('/');
      }
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Unable to connect. Check credentials and try again.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-wrapper" id="login-page">
      <div className="auth-card-box">
        <div className="auth-header">
          <div style={{ display: 'inline-flex', padding: '12px', borderRadius: '12px', background: 'rgba(217, 58, 31, 0.1)', color: 'var(--accent-color)' }}>
            <Plane size={32} strokeWidth={2.5} />
          </div>
          <h1>AeroMedical</h1>
          <p>Medical Drone Delivery Management</p>
        </div>

        {error && (
          <div
            className="flash-banner flash-banner--error"
            role="alert"
            style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)' }}
            id="login-error-alert"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate id="login-form">
          <div className="form-group">
            <label htmlFor="login-email" className="form-label">Email Address</label>
            <input
              id="login-email"
              className={`form-input ${error ? 'form-input--error' : ''}`}
              type="email"
              placeholder="operator@hospital.in"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="form-group" style={{ marginBottom: 'var(--space-6)' }}>
            <label htmlFor="login-password" className="form-label">Password</label>
            <input
              id="login-password"
              className={`form-input ${error ? 'form-input--error' : ''}`}
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          <button
            className="app-btn app-btn--primary"
            type="submit"
            disabled={loading}
            style={{ width: '100%', padding: '12px' }}
            id="login-submit-btn"
          >
            {loading ? 'Authenticating…' : 'Sign In'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 'var(--space-6)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
          Hospital sign-up?{' '}
          <Link to="/register" style={{ color: 'var(--accent-color)', fontWeight: 700 }} id="link-to-register">
            Register Hospital Account
          </Link>
        </div>
      </div>
    </div>
  );
}
