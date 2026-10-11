import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { AlertCircle, RefreshCw, Send, Sparkles, CheckCircle2 } from 'lucide-react';

const PRIORITY_ORDER = {
  CRITICAL: 0,
  Critical: 0,
  HIGH: 1,
  High: 1,
  MEDIUM: 2,
  Medium: 2,
  NORMAL: 3,
  Normal: 3,
  LOW: 4,
  Low: 4,
};

function getPriorityWeight(req) {
  const p = req.priority_tier || req.urgency;
  return PRIORITY_ORDER[p] !== undefined ? PRIORITY_ORDER[p] : 5;
}

// Format wait time strictly as e.g. "36d 15h" / "4h 20m" / "6 min"
function formatWaitTime(createdAt) {
  if (!createdAt) return '—';
  const diffMs = Math.max(0, Date.now() - new Date(createdAt).getTime());
  const totalMin = Math.floor(diffMs / 60000);
  const days = Math.floor(totalMin / 1440);
  const hours = Math.floor((totalMin % 1440) / 60);
  const mins = totalMin % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${mins}m`;
  }
  return `${mins} min`;
}

function formatRouteBadge(decision) {
  const reason = decision.reason || '';
  const distMatch = reason.match(/distance\s+([\d.]+)\s*km/i);
  const etaMatch = reason.match(/ETA\s+([\d.]+)\s*min/i);
  if (distMatch && etaMatch) {
    return `${distMatch[1]} km · ${etaMatch[1]} min`;
  }
  return decision.decision || 'ROUTE COMPUTED';
}

export default function OperatorConsole() {
  const { user } = useAuthStore();
  const navigate = useNavigate();

  const isOperator = user?.role === 'operator' || user?.role === 'admin' || user?.role === 'system_admin';

  const [requests, setRequests] = useState([]);
  const [centers, setCenters] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [filter, setFilter] = useState('All'); // 'All' | 'Waiting' | 'Active'
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);

  // Decision trail state for selected request
  const [decisions, setDecisions] = useState([]);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [decisionsError, setDecisionsError] = useState(null);

  // Summary state for selected request ({ text, source, generated_at })
  const [summaryData, setSummaryData] = useState(null);

  // Dispatch state
  const [dispatchingId, setDispatchingId] = useState(null);
  const [dispatchHaltedMessages, setDispatchHaltedMessages] = useState({});

  // Helper to fetch summary for a request
  const fetchSummary = (reqId) => {
    if (!reqId || !isOperator) {
      setSummaryData(null);
      return;
    }
    api.get(`/requests/${reqId}/summary`)
      .then((res) => {
        setSummaryData(res.data);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setSummaryData(null);
        }
      });
  };

  useEffect(() => {
    fetchSummary(selectedId);
  }, [selectedId, isOperator]);

  // Load medical centers
  useEffect(() => {
    api.get('/medical-centers/')
      .then((res) => {
        const map = {};
        (res.data || []).forEach((c) => {
          map[c.id] = c.name;
        });
        setCenters(map);
      })
      .catch(() => {});
  }, []);

  // Fetch requests
  const fetchRequests = async () => {
    if (!isOperator) return;
    try {
      setErrorState(null);
      const res = await api.get('/requests/', { params: { limit: 100 } });
      const raw = res.data || [];

      // Sort by priority tier, then created_at ascending
      const sorted = [...raw].sort((a, b) => {
        const pa = getPriorityWeight(a);
        const pb = getPriorityWeight(b);
        if (pa !== pb) return pa - pb;
        return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      });

      setRequests(sorted);

      // Default select the first item if nothing selected
      setSelectedId((prev) => {
        if (prev && sorted.some((r) => r.id === prev)) return prev;
        return sorted[0]?.id || null;
      });
    } catch (err) {
      if (err.response?.status === 403) {
        setErrorState('Access denied: operator role required.');
      } else {
        setErrorState('Network error connecting to backend service.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRequests();
    const interval = setInterval(fetchRequests, 10000);
    return () => clearInterval(interval);
  }, [isOperator]);

  // Fetch decisions when selected request changes
  useEffect(() => {
    if (!selectedId || !isOperator) {
      setDecisions([]);
      return;
    }

    setDecisionsLoading(true);
    setDecisionsError(null);

    api.get(`/requests/${selectedId}/decisions`)
      .then((res) => {
        setDecisions(res.data || []);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setDecisions([]);
        } else {
          setDecisionsError('Could not load decision trail.');
        }
      })
      .finally(() => {
        setDecisionsLoading(false);
      });
  }, [selectedId, isOperator]);

  // Filter requests
  const filteredRequests = useMemo(() => {
    return requests.filter((r) => {
      if (filter === 'Waiting') return r.status === 'PENDING';
      if (filter === 'Active') {
        return r.status !== 'PENDING' && r.status !== 'DELIVERED' && r.status !== 'FAILED' && r.status !== 'CANCELLED';
      }
      return true;
    });
  }, [requests, filter]);

  // Selected request details
  const selectedReq = useMemo(() => {
    return requests.find((r) => r.id === selectedId) || null;
  }, [requests, selectedId]);

  // Decision trail slices for latest attempt
  const { latestAttemptRows, attemptTimeStr } = useMemo(() => {
    if (!decisions.length) return { latestAttemptRows: [], attemptTimeStr: null };
    const sorted = [...decisions].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    let lastPriorityIdx = -1;
    for (let i = sorted.length - 1; i >= 0; i--) {
      if (sorted[i].agent_name === 'PriorityAgent') {
        lastPriorityIdx = i;
        break;
      }
    }
    const rows = lastPriorityIdx >= 0 ? sorted.slice(lastPriorityIdx) : sorted;
    const attemptTime = lastPriorityIdx >= 0 ? sorted[lastPriorityIdx].timestamp : sorted[0].timestamp;
    const timeStr = attemptTime
      ? new Date(attemptTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : null;
    return { latestAttemptRows: rows, attemptTimeStr: timeStr };
  }, [decisions]);

  // Dispatch action
  const handleDispatch = async (reqId) => {
    setDispatchingId(reqId);
    setDispatchHaltedMessages((prev) => ({ ...prev, [reqId]: null }));

    try {
      const res = await api.post(`/requests/${reqId}/dispatch`);
      const data = res.data;

      if (data?.weather_halted) {
        setDispatchHaltedMessages((prev) => ({
          ...prev,
          [reqId]: (data.allocation_reason || 'Dispatch halted due to unsafe weather.').trim(),
        }));
      } else if (!data?.allocated_drone_id && data?.allocation_reason) {
        setDispatchHaltedMessages((prev) => ({
          ...prev,
          [reqId]: data.allocation_reason.trim(),
        }));
      } else if (data?.safety_decision && data?.safety_decision !== 'PASS') {
        setDispatchHaltedMessages((prev) => ({
          ...prev,
          [reqId]: (data.safety_reason || `Safety gate: ${data.safety_decision}`).trim(),
        }));
      }

      await fetchRequests();
      if (selectedId === reqId) {
        const decRes = await api.get(`/requests/${reqId}/decisions`);
        setDecisions(decRes.data || []);
        fetchSummary(reqId);
      }

      setTimeout(() => {
        fetchSummary(reqId);
      }, 5000);
    } catch (err) {
      const status = err.response?.status || 500;
      const detail = err.response?.data?.detail || 'Dispatch failed. Network or server error.';
      setDispatchHaltedMessages((prev) => ({
        ...prev,
        [reqId]: `Error (${status}): ${detail}`,
      }));
    } finally {
      setDispatchingId(null);
    }
  };

  const getPriorityStyle = (tier) => {
    const t = (tier || 'LOW').toUpperCase();
    if (t === 'CRITICAL') return 'priority-chip--critical';
    if (t === 'HIGH') return 'priority-chip--high';
    if (t === 'MEDIUM') return 'priority-chip--medium';
    return 'priority-chip--low';
  };

  const getStatusClass = (st) => {
    const s = (st || '').toLowerCase();
    if (s === 'pending') return 'status-pill--pending';
    if (s === 'assigned') return 'status-pill--assigned';
    if (s === 'in_transit' || s === 'in_flight') return 'status-pill--in_transit';
    if (s === 'delivered') return 'status-pill--delivered';
    return 'status-pill--failed';
  };

  return (
    <div className="page-container" id="operator-console-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Dispatch Console</h1>
          <p className="page-header-subtitle">
            Autonomous multi-agent orchestration and mission dispatch queue
          </p>
        </div>
        <div>
          <button
            type="button"
            className="app-btn app-btn--secondary"
            onClick={fetchRequests}
            title="Refresh queue"
            id="btn-refresh-queue"
          >
            <RefreshCw size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {errorState && (
        <div className="white-card" style={{ marginBottom: 'var(--space-6)', borderColor: '#F8B4B4' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#9B1C1C' }}>
            <AlertCircle size={20} />
            <span style={{ fontWeight: 600 }}>{errorState}</span>
          </div>
        </div>
      )}

      {/* Two-column layout (No Map) */}
      <div className="operator-layout" id="operator-layout-grid">
        {/* Left Column: Dispatch Queue */}
        <div className="white-card" id="dispatch-queue-card" style={{ padding: 'var(--space-5)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
            <div>
              <h2 style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--ink)' }}>
                Dispatch Queue
              </h2>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                {filteredRequests.length} request{filteredRequests.length === 1 ? '' : 's'}
              </span>
            </div>

            <div className="filter-group" id="operator-filter-group">
              {['All', 'Waiting', 'Active'].map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`filter-btn ${filter === f ? 'active' : ''}`}
                  onClick={() => setFilter(f)}
                  id={`operator-filter-${f.toLowerCase()}`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }}>
              Loading queue…
            </div>
          ) : filteredRequests.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }} id="no-queue-empty">
              <p style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--ink)' }}>
                No requests in queue
              </p>
              <p style={{ fontSize: '0.85rem', marginTop: '4px', color: 'var(--text-tertiary)' }}>
                Filter: {filter}
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }} id="queue-items-container">
              {filteredRequests.map((req) => {
                const isSelected = req.id === selectedId;
                const pTier = req.priority_tier || req.urgency || 'NORMAL';
                const isWaiting = req.status === 'PENDING';
                const waitFormatted = formatWaitTime(req.created_at);
                const centerName = centers[req.center_id] || req.center_id || 'Medical Center';
                const isDispatching = dispatchingId === req.id;
                const haltedMsg = dispatchHaltedMessages[req.id];

                return (
                  <article
                    key={req.id}
                    onClick={() => setSelectedId(req.id)}
                    id={`queue-card-${req.id}`}
                    style={{
                      border: isSelected ? '2px solid var(--ink)' : '1px solid rgba(11, 31, 51, 0.12)',
                      borderRadius: '16px',
                      padding: '16px',
                      cursor: 'pointer',
                      backgroundColor: isSelected ? '#FAFBFD' : '#FFFFFF',
                      boxShadow: isSelected ? '0 4px 12px rgba(11, 31, 51, 0.06)' : 'none',
                      transition: 'all 0.15s ease',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px',
                    }}
                  >
                    {/* Top Row: Priority chip, Medical type, Wait time */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className={`priority-chip ${getPriorityStyle(pTier)}`}>
                          {pTier}
                        </span>
                        <span style={{ fontWeight: 800, fontSize: '1rem', color: 'var(--ink)' }}>
                          {req.medical_type}
                        </span>
                      </div>
                      <span className="mono" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                        wait: {waitFormatted}
                      </span>
                    </div>

                    {/* Middle Row: Units, weight, center */}
                    <div className="mono" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {req.quantity} units · {req.weight_kg} kg · {centerName}
                    </div>

                    {/* Bottom Row: Status, Assigned Drone & Dispatch button */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', paddingTop: '4px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className={`status-pill ${getStatusClass(req.status)}`}>
                          {req.status}
                        </span>
                        {req.assigned_drone_id && (
                          <span className="mono" style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
                            Drone: {req.assigned_drone_id}
                          </span>
                        )}
                      </div>

                      {isWaiting ? (
                        <button
                          type="button"
                          className="app-btn app-btn--primary app-btn--sm"
                          disabled={isDispatching}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDispatch(req.id);
                          }}
                          id={`dispatch-btn-${req.id}`}
                        >
                          <Send size={12} />
                          <span>{isDispatching ? 'Dispatching…' : 'Dispatch'}</span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="app-btn app-btn--secondary app-btn--sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/mission/${req.mission_id || req.id}`);
                          }}
                          id={`mission-btn-${req.id}`}
                        >
                          View Mission
                        </button>
                      )}
                    </div>

                    {/* Halted Message inline */}
                    {haltedMsg && (
                      <div
                        style={{
                          fontSize: '0.78rem',
                          color: '#C81E1E',
                          background: '#FDE8E8',
                          padding: '8px 12px',
                          borderRadius: '8px',
                          lineHeight: 1.35,
                        }}
                        id={`halted-msg-${req.id}`}
                      >
                        {haltedMsg}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Decision Trail & Summary Card */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }} id="right-column-decisions">
          {/* Summary Card */}
          <div className="white-card" id="summary-card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <Sparkles size={18} color="var(--accent-color)" />
              <h2 style={{ fontSize: '1.1rem', fontWeight: 800 }}>Dispatch Explanation</h2>
            </div>

            {summaryData ? (
              <div>
                <p style={{ fontSize: '0.9rem', lineHeight: 1.5, color: 'var(--ink)' }}>
                  {summaryData.text}
                </p>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '12px', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                  <span className="mono">Source: {summaryData.source || 'agent-pipeline'}</span>
                  {summaryData.generated_at && (
                    <span>{new Date(summaryData.generated_at).toLocaleTimeString()}</span>
                  )}
                </div>
              </div>
            ) : selectedReq ? (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                {selectedReq.status === 'PENDING'
                  ? 'Click "Dispatch" to run autonomous safety checks and generate AI dispatch summary.'
                  : (selectedReq.status_note || 'No AI summary generated for this request yet.')}
              </p>
            ) : (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-tertiary)' }}>
                Select a request on the left to view summary.
              </p>
            )}
          </div>

          {/* Decision Trail Card */}
          <div className="white-card" id="decision-trail-card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
              <div>
                <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>Decision Trail</h2>
                {selectedReq && (
                  <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {selectedReq.request_id || selectedReq.id}
                  </span>
                )}
              </div>
              {attemptTimeStr && (
                <span className="mono" style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                  ATTEMPT {attemptTimeStr}
                </span>
              )}
            </div>

            {decisionsLoading ? (
              <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                Loading decisions…
              </div>
            ) : decisionsError ? (
              <div style={{ color: '#C81E1E', fontSize: '0.85rem' }}>{decisionsError}</div>
            ) : latestAttemptRows.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '28px', color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>
                No agent decisions logged for this request yet.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {latestAttemptRows.map((dec, i) => {
                  const pass = dec.decision === 'GO' || dec.decision === 'PASS' || dec.decision === 'APPROVED' || !dec.decision.includes('FAIL');
                  return (
                    <div
                      key={dec.id || i}
                      style={{
                        padding: '12px',
                        borderRadius: '12px',
                        background: '#F8FAFC',
                        border: '1px solid rgba(11, 31, 51, 0.06)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--ink)' }}>
                          {dec.agent_name}
                        </span>
                        <span
                          className="mono"
                          style={{
                            fontSize: '0.7rem',
                            fontWeight: 700,
                            padding: '2px 6px',
                            borderRadius: '4px',
                            background: pass ? 'rgba(20, 122, 46, 0.1)' : 'rgba(200, 30, 30, 0.1)',
                            color: pass ? '#147A2E' : '#C81E1E',
                          }}
                        >
                          {dec.agent_name === 'RouteAgent' ? formatRouteBadge(dec) : dec.decision}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                        {dec.reason}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
