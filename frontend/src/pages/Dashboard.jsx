import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plane } from 'lucide-react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import WorldMap from '../components/WorldMap';

/* ── MOCK DATA ───────────────────────────────────────────────────────── */
const MOCK_DRONES = [
  { drone_id: 'BLR-1', status: 'IN_FLIGHT', battery_pct: 78, max_payload_kg: 5, latitude: 12.97, longitude: 77.59 },
  { drone_id: 'BLR-2', status: 'AVAILABLE', battery_pct: 100, max_payload_kg: 3, latitude: 12.98, longitude: 77.60 }
];
const MOCK_REQUESTS = [
  { id: 'req-1', medical_type: 'Blood', quantity: 2, weight_kg: 1.5, status: 'ASSIGNED', urgency: 'CRITICAL', created_at: new Date(Date.now() - 300000).toISOString() },
  { id: 'req-2', medical_type: 'Vaccines', quantity: 50, weight_kg: 3.0, status: 'PENDING', urgency: 'MEDIUM', created_at: new Date(Date.now() - 1200000).toISOString() },
];

export default function Dashboard() {
  const { user, logout } = useAuthStore();
  const isHospital = user?.role === 'hospital' || user?.role === 'hospital_admin';

  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);

  const [useDevData, setUseDevData] = useState(true); // ON by default in spike
  const [drones, setDrones] = useState([]);
  const [requests, setRequests] = useState([]);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mq.matches);
    const handler = (e) => setPrefersReducedMotion(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const fetchData = async () => {
    if (useDevData) {
      setDrones(MOCK_DRONES);
      setRequests(MOCK_REQUESTS);
      setErrorState(null);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setErrorState(null);

      let fetchedDrones = [];
      if (!isHospital) {
        const droneRes = await api.get('/drones/');
        fetchedDrones = droneRes.data;
      }

      const reqRes = await api.get('/requests/?limit=20');
      const fetchedRequests = reqRes.data;

      setDrones(fetchedDrones);
      setRequests(fetchedRequests);

    } catch (err) {
      if (err.response?.status === 403 || err.response?.status === 401) {
        if (isHospital && !user?.center_id) {
           setErrorState('No medical center assigned - ask an admin');
        } else {
           setErrorState('Access denied (403).');
        }
      } else {
        setErrorState('Network error.');
      }
      setDrones([]);
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    if (!useDevData && !errorState) {
      const interval = setInterval(fetchData, 10000);
      return () => clearInterval(interval);
    }
  }, [useDevData, isHospital]);

  const activeDrones = drones.filter(d => ['IN_FLIGHT', 'ASSIGNED'].includes(d.status)).length;
  const availableDrones = drones.filter(d => d.status === 'AVAILABLE').length;
  const totalDrones = drones.length;
  const pendingRequests = requests.filter(r => r.status === 'PENDING').length;
  const activeMissions = requests.filter(r => r.status === 'ASSIGNED' || r.status === 'IN_TRANSIT').length;

  let fleetStatusText = 'No telemetry';
  let fleetStatusColor = 'var(--status-neutral)';
  if (totalDrones > 0) {
    if (availableDrones > 0 || activeDrones > 0) {
      fleetStatusText = 'Operational';
      fleetStatusColor = 'var(--status-safe)';
    } else {
      fleetStatusText = 'Offline';
      fleetStatusColor = 'var(--status-unsafe)';
    }
  }

  const slideIn = {
    hidden: { opacity: 0, x: -20 },
    show: { opacity: 1, x: 0, transition: { duration: 0.4 } }
  };
  const slideInRight = {
    hidden: { opacity: 0, x: 20 },
    show: { opacity: 1, x: 0, transition: { duration: 0.4 } }
  };

  return (
    <>
      <WorldMap />

      {/* Top Stats Strip */}
      <div className="hud-stats-strip">
        <div className="hud-stats-strip__brand">
          <Plane /> AeroMedical
        </div>

        {!isHospital && (
          <div className="hud-stat">
            <span className="hud-stat__value" style={{ color: fleetStatusColor }}>
              {loading ? '--' : `${activeDrones + availableDrones}/${totalDrones}`}
            </span>
            <span className="hud-stat__label">{loading ? 'SYNCING' : fleetStatusText}</span>
          </div>
        )}

        <div className="hud-stat">
          <span className="hud-stat__value">{loading ? '--' : pendingRequests}</span>
          <span className="hud-stat__label">Pending</span>
        </div>

        <div className="hud-stat">
          <span className="hud-stat__value">{loading ? '--' : activeMissions}</span>
          <span className="hud-stat__label">Active Missions</span>
        </div>

        <div className="hud-nav-links">
          <label className="toggle-switch">
            <div className={`toggle-switch__track ${useDevData ? 'toggle-switch__track--active' : ''}`}>
              <div className="toggle-switch__thumb" />
            </div>
            Demo Data
            <input type="checkbox" checked={useDevData} onChange={(e) => setUseDevData(e.target.checked)} style={{ display: 'none' }} />
          </label>

          <span className="hud-user-info">{user?.email}</span>
          <button className="hud-logout-btn" onClick={() => logout()}>Logout</button>
        </div>
      </div>

      {!loading && (
        <motion.div initial="hidden" animate="show" style={{ position: 'relative', zIndex: 10, pointerEvents: 'none' }}>
          
          {/* Left Rail: Requests */}
          <motion.div variants={prefersReducedMotion ? {} : slideIn} className="hud-rail hud-rail--left" style={{ pointerEvents: 'auto' }}>
            <div className="hud-panel">
              <div className="hud-panel__header">
                <span className="hud-panel__title">Network Requests</span>
                <span className="hud-panel__badge">{requests.length}</span>
              </div>
              <div className="hud-panel__body">
                {errorState ? (
                  <div className="glass-alert glass-alert--error">{errorState}</div>
                ) : requests.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
                    No active requests.
                  </div>
                ) : (
                  requests.map(req => (
                    <div key={req.id} className="hud-request-row">
                      <div>
                        <div className="hud-request-row__type">{req.medical_type}</div>
                        <div className="hud-request-row__meta">{req.quantity}x • {req.weight_kg}kg</div>
                      </div>
                      <span className={`status-badge status--${req.status.toLowerCase()}`}>
                        {req.status}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </motion.div>

          {/* Right Rail: Fleet */}
          {!isHospital && (
            <motion.div variants={prefersReducedMotion ? {} : slideInRight} className="hud-rail hud-rail--right" style={{ pointerEvents: 'auto' }}>
              <div className="hud-panel">
                <div className="hud-panel__header">
                  <span className="hud-panel__title">Fleet Telemetry</span>
                  <span className="hud-panel__badge">{drones.length}</span>
                </div>
                <div className="hud-panel__body" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {errorState ? (
                     <div className="glass-alert glass-alert--error">{errorState}</div>
                  ) : drones.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
                      No drones registered.
                    </div>
                  ) : (
                    drones.map(drone => (
                      <div key={drone.drone_id} className="hud-drone-card">
                        <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                          <span className="hud-drone-card__id" style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{drone.drone_id}</span>
                          <span className="hud-drone-card__battery" style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>BAT {drone.battery_pct.toFixed(1)}%</span>
                        </div>
                        <span className={`status-badge status--${drone.status.toLowerCase()}`}>
                          {drone.status}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </motion.div>
      )}
    </>
  );
}
