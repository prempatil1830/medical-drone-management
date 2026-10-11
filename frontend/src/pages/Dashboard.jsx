import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Navigation, AlertTriangle, Activity, PackageCheck, Clock, ShieldAlert } from 'lucide-react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { useDeliveryStore } from '../store/deliveryStore';

export default function Dashboard() {
  const { user } = useAuthStore();
  const applyOverrides = useDeliveryStore((state) => state.applyOverrides);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);
  const [isUnassignedCenter, setIsUnassignedCenter] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setErrorState(null);
    setIsUnassignedCenter(false);

    try {
      // Fetch up to 100 requests for accurate metrics
      const response = await api.get('/requests/', { params: { limit: 100 } });
      setRequests(response.data || []);
    } catch (err) {
      if (err.response?.status === 403) {
        setIsUnassignedCenter(true);
        setErrorState('No medical center assigned — ask an administrator to assign a center to your account.');
      } else if (err.response?.status === 401) {
        setErrorState('Authentication session expired. Please sign in again.');
      } else {
        setErrorState('Network error connecting to backend service.');
      }
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Apply real-time delivery state overrides
  const effectiveRequests = applyOverrides(requests);

  // Compute counts
  const pendingCount = effectiveRequests.filter((r) => r.status === 'PENDING').length;
  const activeRequests = effectiveRequests.filter(
    (r) => r.status !== 'PENDING' && r.status !== 'DELIVERED' && r.status !== 'FAILED' && r.status !== 'CANCELLED'
  );
  const activeCount = activeRequests.length;
  const deliveredCount = effectiveRequests.filter((r) => r.status === 'DELIVERED').length;

  // Active highlighted mission (first one)
  const highlightedActive = activeRequests[0] || null;

  // 5 most recent requests
  const recentRequests = [...effectiveRequests]
    .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
    .slice(0, 5);

  const getStatusClass = (st) => {
    const s = (st || '').toLowerCase();
    if (s === 'pending') return 'status-pill--pending';
    if (s === 'assigned') return 'status-pill--assigned';
    if (s === 'in_transit' || s === 'in_flight') return 'status-pill--in_transit';
    if (s === 'delivered') return 'status-pill--delivered';
    return 'status-pill--failed';
  };

  return (
    <div className="page-container" id="hospital-dashboard">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Hospital Dashboard</h1>
          <p className="page-header-subtitle">
            Overview of medical delivery logistics and mission tracking
          </p>
        </div>
        <div>
          <Link
            to="/requests/new"
            className="app-btn app-btn--primary"
            id="btn-new-request"
          >
            <Plus size={16} />
            <span>New Request</span>
          </Link>
        </div>
      </div>

      {/* Explicit Error / Unassigned State */}
      {errorState && (
        <div
          className="white-card"
          style={{ marginBottom: 'var(--space-6)', borderColor: isUnassignedCenter ? '#F5C6CB' : '#F8B4B4' }}
          id="dashboard-error-state"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#9B1C1C' }}>
            {isUnassignedCenter ? <ShieldAlert size={24} /> : <AlertTriangle size={24} />}
            <div>
              <div style={{ fontWeight: 700, fontSize: '1rem' }}>
                {isUnassignedCenter ? 'Account Configuration Required' : 'Unable to Load Data'}
              </div>
              <div style={{ fontSize: '0.875rem', marginTop: '2px', color: 'var(--text-secondary)' }}>
                {errorState}
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="white-card" style={{ textAlign: 'center', padding: '48px' }} id="dashboard-loading">
          <p style={{ color: 'var(--text-secondary)' }}>Loading logistics data…</p>
        </div>
      ) : (
        <>
          {/* Three Stat Cards */}
          <div className="stats-grid-3" id="dashboard-stats-grid">
            <div className="stat-card" id="stat-active-missions">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Active Missions</span>
                  <Activity size={18} color="var(--teal)" />
                </div>
                <div className="stat-value" style={{ color: activeCount > 0 ? 'var(--teal)' : 'var(--ink)' }}>
                  {activeCount}
                </div>
              </div>
              <div className="stat-subtext">In-flight or dispatch assigned</div>
            </div>

            <div className="stat-card" id="stat-pending-requests">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Pending Requests</span>
                  <Clock size={18} color="#8C5300" />
                </div>
                <div className="stat-value" style={{ color: pendingCount > 0 ? '#8C5300' : 'var(--ink)' }}>
                  {pendingCount}
                </div>
              </div>
              <div className="stat-subtext">Awaiting operator dispatch</div>
            </div>

            <div className="stat-card" id="stat-delivered-requests">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="stat-label">Delivered</span>
                  <PackageCheck size={18} color="#147A2E" />
                </div>
                <div className="stat-value" style={{ color: '#147A2E' }}>
                  {deliveredCount}
                </div>
              </div>
              <div className="stat-subtext">Successfully completed missions</div>
            </div>
          </div>

          {/* Highlighted Active Mission Card or Empty State */}
          <div style={{ marginBottom: 'var(--space-8)' }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 'var(--space-3)' }}>
              Active Mission Telemetry
            </h2>
            {highlightedActive ? (
              <div className="white-card white-card--highlight" id="highlighted-active-card">
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                      <span className="mono" style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--ink)' }}>
                        {highlightedActive.request_id || highlightedActive.id}
                      </span>
                      <span className={`status-pill ${getStatusClass(highlightedActive.status)}`}>
                        {highlightedActive.status}
                      </span>
                      {highlightedActive.urgency && (
                        <span className={`priority-chip priority-chip--${highlightedActive.urgency.toLowerCase()}`}>
                          {highlightedActive.urgency}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--ink)' }}>
                      {highlightedActive.medical_type} — {highlightedActive.quantity} units ({highlightedActive.weight_kg} kg)
                    </div>
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                      {highlightedActive.status_note || (highlightedActive.assigned_drone_id ? `Assigned to Drone ${highlightedActive.assigned_drone_id}` : 'In progress')}
                    </div>
                  </div>

                  <div>
                    <Link
                      to={`/mission/${highlightedActive.mission_id || highlightedActive.id}`}
                      className="app-btn app-btn--primary"
                      id="track-live-btn"
                    >
                      <Navigation size={16} />
                      <span>Track live</span>
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <div className="white-card" style={{ textAlign: 'center', padding: '32px' }} id="no-active-missions-empty">
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', fontWeight: 600 }}>
                  No active missions
                </p>
                <p style={{ color: 'var(--text-tertiary)', fontSize: '0.85rem', marginTop: '4px' }}>
                  Submit a new delivery request or check the requests history below.
                </p>
              </div>
            )}
          </div>

          {/* 5 Most Recent Requests */}
          <div className="white-card" id="recent-requests-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700 }}>Recent Requests</h2>
              <Link to="/requests" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--accent-color)' }}>
                View all requests →
              </Link>
            </div>

            {recentRequests.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                No requests found for this hospital account.
              </div>
            ) : (
              <div className="table-responsive">
                <table className="data-table" id="recent-requests-table">
                  <thead>
                    <tr>
                      <th>Request ID</th>
                      <th>Supply</th>
                      <th>Qty & Wt</th>
                      <th>Status</th>
                      <th>Status Note</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRequests.map((req) => (
                      <tr key={req.id}>
                        <td className="mono" style={{ fontWeight: 600 }}>
                          {req.request_id || req.id}
                        </td>
                        <td>{req.medical_type}</td>
                        <td>{req.quantity} units ({req.weight_kg} kg)</td>
                        <td>
                          <span className={`status-pill ${getStatusClass(req.status)}`}>
                            {req.status}
                          </span>
                        </td>
                        <td style={{ color: req.status_note ? 'var(--ink)' : 'var(--text-tertiary)', fontSize: '0.82rem' }}>
                          {req.status_note || '—'}
                        </td>
                        <td>
                          {req.mission_id ? (
                            req.status !== 'DELIVERED' && req.status !== 'FAILED' && req.status !== 'CANCELLED' ? (
                              <Link
                                to={`/mission/${req.mission_id}`}
                                className="app-btn app-btn--primary app-btn--sm"
                              >
                                Track live
                              </Link>
                            ) : (
                              <Link
                                to={`/mission/${req.mission_id}`}
                                className="app-btn app-btn--secondary app-btn--sm"
                              >
                                View mission
                              </Link>
                            )
                          ) : (
                            <Link
                              to={`/mission/${req.id}`}
                              className="app-btn app-btn--secondary app-btn--sm"
                              style={{ color: '#8C5300', borderColor: 'rgba(140, 83, 0, 0.25)', backgroundColor: '#FFFDF5' }}
                              title="Inspect weather halt details on map"
                            >
                              Inspect status
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
