import React, { useEffect, useState } from 'react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { RefreshCw, AlertTriangle, Activity, PackageCheck, AlertOctagon, Clock, Cpu, Timer, Building2, CheckCircle2 } from 'lucide-react';

function formatResponseTime(totalSeconds) {
  if (totalSeconds == null || isNaN(totalSeconds)) return '—';
  const sec = Math.round(totalSeconds);
  const minutes = Math.floor(sec / 60);
  const remainingSeconds = sec % 60;
  return `${minutes} min ${remainingSeconds} sec`;
}

export default function AdminAnalytics() {
  const { user } = useAuthStore();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);

  // Admin center assignment state
  const [centers, setCenters] = useState([]);
  const [targetUserId, setTargetUserId] = useState('');
  const [selectedCenterId, setSelectedCenterId] = useState('');
  const [assignLoading, setAssignLoading] = useState(false);
  const [assignError, setAssignError] = useState(null);
  const [assignSuccess, setAssignSuccess] = useState(null);

  const fetchStats = async () => {
    setLoading(true);
    setErrorState(null);
    try {
      const response = await api.get('/dashboard/stats');
      setStats(response.data);
    } catch (err) {
      if (err.response?.status === 403) {
        setErrorState('Access denied: System administrator privileges required.');
      } else {
        setErrorState('Failed to fetch analytics statistics from backend.');
      }
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  const fetchCenters = async () => {
    try {
      const res = await api.get('/medical-centers/');
      setCenters(res.data || []);
      if (res.data && res.data.length > 0) {
        setSelectedCenterId(res.data[0].id);
      }
    } catch (err) {
      console.error('Failed to load centers:', err);
    }
  };

  useEffect(() => {
    fetchStats();
    fetchCenters();
  }, []);

  const handleAssignCenter = async (e) => {
    e.preventDefault();
    if (!targetUserId || !selectedCenterId) return;

    setAssignLoading(true);
    setAssignError(null);
    setAssignSuccess(null);

    try {
      const res = await api.patch(`/users/${targetUserId.trim()}/center`, {
        center_id: selectedCenterId,
      });
      setAssignSuccess(`Successfully assigned medical center to user: ${res.data.email || targetUserId}`);
      setTargetUserId('');
    } catch (err) {
      setAssignError(err.response?.data?.detail || 'Failed to assign medical center. Check the User ID.');
    } finally {
      setAssignLoading(false);
    }
  };

  return (
    <div className="page-container" id="admin-analytics-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-header-title">System Analytics</h1>
          <p className="page-header-subtitle">
            Executive operations summary, drone fleet utilization, and response SLA metrics
          </p>
        </div>
        <div>
          <button
            type="button"
            className="app-btn app-btn--secondary"
            onClick={fetchStats}
            title="Refresh analytics"
            id="btn-refresh-stats"
          >
            <RefreshCw size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Error state */}
      {errorState && (
        <div className="white-card" style={{ marginBottom: 'var(--space-6)', borderColor: '#F8B4B4' }} id="admin-error-state">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#9B1C1C' }}>
            <AlertTriangle size={20} />
            <span style={{ fontWeight: 600 }}>{errorState}</span>
          </div>
        </div>
      )}

      {loading ? (
        <div className="white-card" style={{ textAlign: 'center', padding: '48px' }} id="admin-loading-state">
          <p style={{ color: 'var(--text-secondary)' }}>Calculating system performance metrics…</p>
        </div>
      ) : !stats && !errorState ? (
        <div className="white-card" style={{ textAlign: 'center', padding: '48px' }} id="admin-empty-state">
          <p style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>No statistics available</p>
        </div>
      ) : stats ? (
        <>
          <div className="stats-grid-admin" id="admin-stats-grid" style={{ marginBottom: 'var(--space-8)' }}>
            {/* Delivered */}
            <div className="stat-card" id="stat-card-delivered">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Delivered Missions</span>
                  <PackageCheck size={18} color="#147A2E" />
                </div>
                <div className="stat-value" style={{ color: '#147A2E' }}>
                  {stats.delivered}
                </div>
              </div>
              <div className="stat-subtext">Completed dropoffs</div>
            </div>

            {/* Failed */}
            <div className="stat-card" id="stat-card-failed">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Failed Missions</span>
                  <AlertOctagon size={18} color="#C81E1E" />
                </div>
                <div className="stat-value" style={{ color: stats.failed > 0 ? '#C81E1E' : 'var(--ink)' }}>
                  {stats.failed}
                </div>
              </div>
              <div className="stat-subtext">Aborted or critical alerts</div>
            </div>

            {/* Active */}
            <div className="stat-card" id="stat-card-active">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Active Missions</span>
                  <Activity size={18} color="var(--teal)" />
                </div>
                <div className="stat-value" style={{ color: stats.active > 0 ? 'var(--teal)' : 'var(--ink)' }}>
                  {stats.active}
                </div>
              </div>
              <div className="stat-subtext">Currently navigating</div>
            </div>

            {/* Average ETA */}
            <div className="stat-card" id="stat-card-avg-eta">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Average ETA</span>
                  <Clock size={18} color="#8C5300" />
                </div>
                <div className="stat-value" style={{ color: 'var(--ink)' }}>
                  {stats.average_eta != null ? `${stats.average_eta} min` : '—'}
                </div>
              </div>
              <div className="stat-subtext">Estimated delivery flight duration</div>
            </div>

            {/* Drone Utilization % */}
            <div className="stat-card" id="stat-card-utilization">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Drone Utilization</span>
                  <Cpu size={18} color="var(--accent-color)" />
                </div>
                <div className="stat-value" style={{ color: 'var(--accent-color)' }}>
                  {stats.drone_utilization != null ? `${stats.drone_utilization}%` : '—'}
                </div>
              </div>
              <div className="stat-subtext">Fleet operational capacity active</div>
            </div>

            {/* Average Response Time (minutes and seconds) */}
            <div className="stat-card" id="stat-card-response-time">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Average Response Time</span>
                  <Timer size={18} color="var(--ink)" />
                </div>
                <div className="stat-value" style={{ fontSize: '1.6rem', color: 'var(--ink)' }}>
                  {formatResponseTime(stats.average_response_time)}
                </div>
              </div>
              <div className="stat-subtext">Creation to launch for Critical & High</div>
            </div>
          </div>

          {/* Admin User Medical Center Assignment Card */}
          <div className="white-card" id="admin-assign-center-card" style={{ maxWidth: '640px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: 'var(--space-2)' }}>
              <Building2 size={20} color="var(--accent-color)" />
              <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>Assign Medical Center to Hospital User</h2>
            </div>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginBottom: 'var(--space-4)' }}>
              New hospital accounts have no assigned center by default. Use this tool to assign a verified hospital center ID.
            </p>

            {assignError && (
              <div className="flash-banner flash-banner--error" style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)' }}>
                {assignError}
              </div>
            )}

            {assignSuccess && (
              <div className="flash-banner" style={{ backgroundColor: '#EDF7EE', color: '#155724', borderBottom: '1px solid #C3E6CB', borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <CheckCircle2 size={16} />
                  <span>{assignSuccess}</span>
                </div>
              </div>
            )}

            <form onSubmit={handleAssignCenter}>
              <div className="form-group">
                <label className="form-label" htmlFor="assign-user-id">User ID (MongoDB ObjectId or User ID)</label>
                <input
                  id="assign-user-id"
                  className="form-input"
                  type="text"
                  placeholder="e.g. 6acbdf11498e0527e8af1520"
                  value={targetUserId}
                  onChange={(e) => setTargetUserId(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="assign-center-select">Select Medical Center</label>
                <select
                  id="assign-center-select"
                  className="form-select"
                  value={selectedCenterId}
                  onChange={(e) => setSelectedCenterId(e.target.value)}
                  required
                >
                  {centers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.type}) — ID: {c.id}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                className="app-btn app-btn--primary"
                disabled={assignLoading}
                id="btn-submit-assign"
              >
                {assignLoading ? 'Assigning…' : 'Assign Medical Center'}
              </button>
            </form>
          </div>
        </>
      ) : null}
    </div>
  );
}
