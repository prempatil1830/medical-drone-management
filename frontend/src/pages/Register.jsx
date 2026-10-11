import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Plane, AlertCircle, CheckCircle2, Info } from 'lucide-react';
import api from '../services/api';

export default function Register() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await api.post('/auth/register', { name, email, password });
      setSuccess(true);
      setTimeout(() => {
        navigate('/login');
      }, 2500);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        'Failed to register. Password must be at least 8 characters.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-wrapper" id="register-page">
      <div className="auth-card-box">
        <div className="auth-header">
          <div style={{ display: 'inline-flex', padding: '12px', borderRadius: '12px', background: 'rgba(217, 58, 31, 0.1)', color: 'var(--accent-color)' }}>
            <Plane size={32} strokeWidth={2.5} />
          </div>
          <h1>Hospital Registration</h1>
          <p>Create a hospital representative account</p>
        </div>

        {/* Prominent Center Notice required by specs */}
        <div
          className="flash-banner flash-banner--info"
          style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)', lineHeight: 1.4 }}
          id="center-notice-banner"
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
            <Info size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
            <span>
              <strong>Note:</strong> New accounts have no center until an admin assigns one.
            </span>
          </div>
        </div>

        {error && (
          <div
            className="flash-banner flash-banner--error"
            role="alert"
            style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)' }}
            id="register-error-alert"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          </div>
        )}

        {success && (
          <div
            className="flash-banner"
            style={{
              backgroundColor: '#EDF7EE',
              borderBottom: '1px solid #C3E6CB',
              color: '#155724',
              borderRadius: 'var(--radius-md)',
              marginBottom: 'var(--space-4)',
            }}
            id="register-success-alert"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <CheckCircle2 size={16} />
              <span>Registration successful! Redirecting to login…</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate id="register-form">
          <div className="form-group">
            <label htmlFor="reg-name" className="form-label">Hospital / Contact Name</label>
            <input
              id="reg-name"
              className="form-input"
              type="text"
              placeholder="Dr. Sarah Connor"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-email" className="form-label">Email Address</label>
            <input
              id="reg-email"
              className="form-input"
              type="email"
              placeholder="hospital@cityhealth.in"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group" style={{ marginBottom: 'var(--space-6)' }}>
            <label htmlFor="reg-password" className="form-label">Password (min 8 chars)</label>
            <input
              id="reg-password"
              className="form-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <button
            className="app-btn app-btn--primary"
            type="submit"
            disabled={loading || success}
            style={{ width: '100%', padding: '12px' }}
            id="register-submit-btn"
          >
            {loading ? 'Creating Account…' : 'Sign Up'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 'var(--space-6)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
          Already registered?{' '}
          <Link to="/login" style={{ color: 'var(--accent-color)', fontWeight: 700 }} id="link-to-login">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
