import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, ChevronLeft, ChevronRight, AlertTriangle, ShieldAlert } from 'lucide-react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { useDeliveryStore } from '../store/deliveryStore';

const PAGE_SIZE = 10;

export default function MyRequests() {
  const { user } = useAuthStore();
  const applyOverrides = useDeliveryStore((state) => state.applyOverrides);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);
  const [filter, setFilter] = useState('All'); // 'All' | 'Pending' | 'Active' | 'Delivered'
  const [skip, setSkip] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const fetchRequests = async () => {
    setLoading(true);
    setErrorState(null);

    try {
      const params = {
        skip: skip,
        limit: PAGE_SIZE,
      };

      if (filter === 'Pending') {
        params.status = 'PENDING';
      } else if (filter === 'Delivered') {
        params.status = 'DELIVERED';
      }

      const response = await api.get('/requests/', { params });
      let data = response.data || [];

      // If filter is Active, client-side refine (or query)
      if (filter === 'Active') {
        data = data.filter(
          (r) => r.status !== 'PENDING' && r.status !== 'DELIVERED' && r.status !== 'FAILED' && r.status !== 'CANCELLED'
        );
      }

      setRequests(data);
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      if (err.response?.status === 403) {
        setErrorState('No medical center assigned — ask an administrator to assign a center.');
      } else if (err.response?.status === 401) {
        setErrorState('Session expired. Please log in.');
      } else {
        setErrorState('Network error: unable to load requests.');
      }
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRequests();
  }, [filter, skip]);

  const handleFilterChange = (newFilter) => {
    setFilter(newFilter);
    setSkip(0);
  };

  const getStatusClass = (st) => {
    const s = (st || '').toLowerCase();
    if (s === 'pending') return 'status-pill--pending';
    if (s === 'assigned') return 'status-pill--assigned';
    if (s === 'in_transit' || s === 'in_flight') return 'status-pill--in_transit';
    if (s === 'delivered') return 'status-pill--delivered';
    return 'status-pill--failed';
  };

  const isTerminal = (status) => {
    return status === 'DELIVERED' || status === 'FAILED' || status === 'CANCELLED';
  };

  return (
    <div className="page-container" id="my-requests-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-header-title">My Requests</h1>
          <p className="page-header-subtitle">
            All medical delivery dispatches, status notes, and tracking links
          </p>
        </div>
        <div>
          <Link to="/requests/new" className="app-btn app-btn--primary" id="btn-create-request">
            <Plus size={16} />
            <span>New Request</span>
          </Link>
        </div>
      </div>

      {/* Error State */}
      {errorState && (
        <div
          className="white-card"
          style={{ marginBottom: 'var(--space-6)', borderColor: '#F8B4B4' }}
          id="requests-error-alert"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#9B1C1C' }}>
            <AlertTriangle size={24} />
            <div>
              <div style={{ fontWeight: 700, fontSize: '1rem' }}>Request Access Notice</div>
              <div style={{ fontSize: '0.875rem', marginTop: '2px', color: 'var(--text-secondary)' }}>
                {errorState}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Filter Chips & Table Card */}
      <div className="white-card" id="requests-card">
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            marginBottom: 'var(--space-4)',
          }}
        >
          <div className="filter-group" id="requests-filter-group">
            {['All', 'Pending', 'Active', 'Delivered'].map((f) => (
              <button
                key={f}
                type="button"
                className={`filter-btn ${filter === f ? 'active' : ''}`}
                onClick={() => handleFilterChange(f)}
                id={`filter-${f.toLowerCase()}`}
              >
                {f}
              </button>
            ))}
          </div>

          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600 }}>
            Showing page {Math.floor(skip / PAGE_SIZE) + 1}
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }}>
            Loading delivery requests…
          </div>
        ) : requests.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }} id="no-requests-empty">
            <p style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--ink)' }}>
              No requests found
            </p>
            <p style={{ fontSize: '0.85rem', marginTop: '4px', color: 'var(--text-tertiary)' }}>
              {filter === 'All' ? 'You have not submitted any medical requests yet.' : `No requests with status '${filter}'.`}
            </p>
          </div>
        ) : (
          <>
            <div className="table-responsive">
              <table className="data-table" id="my-requests-table">
                <thead>
                  <tr>
                    <th>Request ID</th>
                    <th>Medical Supply</th>
                    <th>Units</th>
                    <th>Weight</th>
                    <th>Urgency</th>
                    <th>Status</th>
                    <th>Status Note</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {applyOverrides(requests).map((req) => {
                    const missionTerminal = isTerminal(req.status);
                    const canTrackLive = !missionTerminal && (req.mission_id || req.status === 'IN_TRANSIT' || req.status === 'ASSIGNED');
                    const missionLink = `/mission/${req.mission_id || req.id}`;

                    return (
                      <tr key={req.id}>
                        <td className="mono" style={{ fontWeight: 600 }}>
                          {req.request_id || req.id}
                        </td>
                        <td>{req.medical_type}</td>
                        <td>{req.quantity}</td>
                        <td>{req.weight_kg} kg</td>
                        <td>
                          {req.urgency && (
                            <span className={`priority-chip priority-chip--${req.urgency.toLowerCase()}`}>
                              {req.urgency}
                            </span>
                          )}
                        </td>
                        <td>
                          <span className={`status-pill ${getStatusClass(req.status)}`}>
                            {req.status}
                          </span>
                        </td>
                        <td style={{ color: req.status_note ? 'var(--ink)' : 'var(--text-tertiary)', fontSize: '0.82rem', maxWidth: '240px' }}>
                          {req.status_note || '—'}
                        </td>
                        <td>
                          {req.mission_id ? (
                            canTrackLive ? (
                              <Link
                                to={`/mission/${req.mission_id}`}
                                className="app-btn app-btn--primary app-btn--sm"
                                id={`track-btn-${req.id}`}
                              >
                                Track live
                              </Link>
                            ) : (
                              <Link
                                to={`/mission/${req.mission_id}`}
                                className="app-btn app-btn--secondary app-btn--sm"
                                id={`view-btn-${req.id}`}
                              >
                                View mission
                              </Link>
                            )
                          ) : (
                            <Link
                              to={`/mission/${req.id}`}
                              className="app-btn app-btn--secondary app-btn--sm"
                              style={{ color: '#8C5300', borderColor: 'rgba(140, 83, 0, 0.25)', backgroundColor: '#FFFDF5' }}
                              id={`view-btn-${req.id}`}
                              title="Inspect weather halt details on map"
                            >
                              Inspect status
                            </Link>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginTop: 'var(--space-4)',
                paddingTop: 'var(--space-3)',
                borderTop: '1px solid rgba(11, 31, 51, 0.06)',
              }}
            >
              <button
                type="button"
                className="app-btn app-btn--secondary app-btn--sm"
                onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
                disabled={skip === 0}
                id="btn-prev-page"
              >
                <ChevronLeft size={14} />
                <span>Previous</span>
              </button>

              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                Offset: {skip} — {skip + requests.length}
              </span>

              <button
                type="button"
                className="app-btn app-btn--secondary app-btn--sm"
                onClick={() => setSkip(skip + PAGE_SIZE)}
                disabled={!hasMore}
                id="btn-next-page"
              >
                <span>Next</span>
                <ChevronRight size={14} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
