import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Plane } from 'lucide-react';
import { useAuthStore } from '../store/auth';
import api from '../services/api';
import WorldMap from '../components/WorldMap';

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
      navigate('/');
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
    <>
      <WorldMap />

      <div className="login-scene">
        <div className="login-panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginBottom: '8px' }}>
            <Plane color="var(--accent-color)" size={32} />
          </div>
          <h1 className="login-panel__title">AeroMedical</h1>
          <p className="login-panel__subtitle">Mission Control Login</p>

          {error && (
            <div className="glass-alert glass-alert--error" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <div style={{ marginBottom: '16px' }}>
              <label htmlFor="login-email" className="glass-input-label">Email</label>
              <input
                id="login-email"
                className="glass-input"
                type="email"
                placeholder="operator@hospital.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div style={{ marginBottom: '24px' }}>
              <label htmlFor="login-password" className="glass-input-label">Password</label>
              <input
                id="login-password"
                className="glass-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <button className="glass-btn" type="submit" disabled={loading}>
              {loading ? 'Authenticating…' : 'Sign In'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: '24px', fontSize: '14px', color: 'var(--text-secondary)' }}>
            No account?{' '}
            <Link to="/register" style={{ color: 'var(--accent-color)', fontWeight: 600 }}>
              Request access
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
