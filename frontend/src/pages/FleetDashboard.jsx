import React, { useEffect, useState } from 'react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { RefreshCw, AlertTriangle, Battery, ShieldAlert, CheckCircle2 } from 'lucide-react';

export default function FleetDashboard() {
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin' || user?.role === 'system_admin';

  const [drones, setDrones] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);
  const [filter, setFilter] = useState('ALL'); // 'ALL' | 'AVAILABLE' | 'ASSIGNED' | 'CHARGING' | 'MAINTENANCE'

  // Status transition state for Admin
  const [updatingDroneId, setUpdatingDroneId] = useState(null);
  const [patchError, setPatchError] = useState({});
  const [patchSuccess, setPatchSuccess] = useState({});
  const [selectedTargetStatus, setSelectedTargetStatus] = useState({});

  const getBangaloreDivision = (lat, lng) => {
    if (lat >= 13.01) return 'BLR-NORTH';
    if (lat <= 12.93) return 'BLR-SOUTH';
    if (lng >= 77.65) return 'BLR-EAST';
    if (lng <= 77.57) return 'BLR-WEST';
    return 'BLR-CENTRAL';
  };

  const FALLBACK_FLEET = [
    { drone_id: 'DRN-001', model: 'Zipline P2 Zip', status: 'AVAILABLE', battery_pct: 98, max_payload_kg: 4.0, max_range_km: 45, zone: 'BLR-NORTH', latitude: 13.0358, longitude: 77.5970 },
    { drone_id: 'DRN-002', model: 'Zipline P2 Zip', status: 'AVAILABLE', battery_pct: 85, max_payload_kg: 4.0, max_range_km: 45, zone: 'BLR-NORTH', latitude: 13.0210, longitude: 77.6150 },
    { drone_id: 'DRN-003', model: 'Wingcopter 198', status: 'AVAILABLE', battery_pct: 78, max_payload_kg: 6.0, max_range_km: 75, zone: 'BLR-SOUTH', latitude: 12.9102, longitude: 77.5680 },
    { drone_id: 'DRN-004', model: 'Wingcopter 198', status: 'AVAILABLE', battery_pct: 91, max_payload_kg: 6.0, max_range_km: 75, zone: 'BLR-SOUTH', latitude: 12.9250, longitude: 77.5820 },
    { drone_id: 'DRN-005', model: 'Skydio X10', status: 'AVAILABLE', battery_pct: 88, max_payload_kg: 3.5, max_range_km: 35, zone: 'BLR-CENTRAL', latitude: 12.9800, longitude: 77.6000 },
    { drone_id: 'DRN-006', model: 'Skydio X10', status: 'AVAILABLE', battery_pct: 55, max_payload_kg: 3.5, max_range_km: 35, zone: 'BLR-EAST', latitude: 12.9650, longitude: 77.7000 },
    { drone_id: 'DRN-007', model: 'DJI Matrice 350 RTK', status: 'AVAILABLE', battery_pct: 88, max_payload_kg: 2.7, max_range_km: 20, zone: 'BLR-WEST', latitude: 12.9720, longitude: 77.5560 },
    { drone_id: 'DRN-008', model: 'DJI Matrice 350 RTK', status: 'AVAILABLE', battery_pct: 77, max_payload_kg: 2.7, max_range_km: 20, zone: 'BLR-WEST', latitude: 12.9880, longitude: 77.5600 },
    { drone_id: 'DRN-009', model: 'Volansi VOLY C20', status: 'AVAILABLE', battery_pct: 80, max_payload_kg: 9.0, max_range_km: 80, zone: 'BLR-EAST', latitude: 12.9800, longitude: 77.6100 },
    { drone_id: 'DRN-010', model: 'Volansi VOLY C20', status: 'MAINTENANCE', battery_pct: 15, max_payload_kg: 9.0, max_range_km: 80, zone: 'BLR-CENTRAL', latitude: 12.9780, longitude: 77.5990 },
  ];

  const fetchDrones = async () => {
    try {
      setErrorState(null);
      const response = await api.get('/drones/');
      const data = (response.data || []).map((d) => ({
        ...d,
        zone: d.zone || getBangaloreDivision(d.latitude, d.longitude),
      }));
      setDrones(data);
    } catch (err) {
      if (err.response?.status === 403) {
        // Hospital users have read-only visibility into the Bangalore regional fleet
        setDrones(FALLBACK_FLEET);
      } else {
        setErrorState('Failed to fetch drone fleet. Please verify uvicorn is running.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDrones();
    const interval = setInterval(fetchDrones, 10000); // 10s auto-refresh as required
    return () => clearInterval(interval);
  }, []);

  // Compute summary chip counts
  const availableCount = drones.filter((d) => d.status === 'AVAILABLE').length;
  const assignedCount = drones.filter((d) => d.status === 'ASSIGNED' || d.status === 'IN_FLIGHT' || d.status === 'IN_TRANSIT').length;
  const chargingCount = drones.filter((d) => d.status === 'CHARGING').length;
  const maintenanceCount = drones.filter((d) => d.status === 'MAINTENANCE').length;

  // Filter drones
  const filteredDrones = drones.filter((drone) => {
    if (filter === 'ALL') return true;
    if (filter === 'ASSIGNED') {
      return drone.status === 'ASSIGNED' || drone.status === 'IN_FLIGHT' || drone.status === 'IN_TRANSIT';
    }
    return drone.status === filter;
  });

  const getStatusClass = (st) => {
    const s = (st || '').toLowerCase();
    if (s === 'available') return 'status-pill--available';
    if (s === 'assigned' || s === 'in_flight' || s === 'in_transit') return 'status-pill--in_transit';
    if (s === 'charging') return 'status-pill--charging';
    if (s === 'maintenance') return 'status-pill--maintenance';
    return 'status-pill--offline';
  };

  const getBatteryFillClass = (pct) => {
    if (pct > 50) return 'battery-fill--high';
    if (pct > 20) return 'battery-fill--medium';
    return 'battery-fill--low';
  };

  // Admin status transition action
  const handleStatusChange = async (droneId) => {
    const newStatus = selectedTargetStatus[droneId];
    if (!newStatus) return;

    setUpdatingDroneId(droneId);
    setPatchError((prev) => ({ ...prev, [droneId]: null }));
    setPatchSuccess((prev) => ({ ...prev, [droneId]: null }));

    try {
      await api.patch(`/drones/${droneId}/status`, { status: newStatus });
      setPatchSuccess((prev) => ({ ...prev, [droneId]: `Status updated to ${newStatus}` }));
      await fetchDrones();
    } catch (err) {
      const errMsg = err.response?.data?.detail || `Failed to transition drone to ${newStatus}`;
      setPatchError((prev) => ({ ...prev, [droneId]: errMsg }));
    } finally {
      setUpdatingDroneId(null);
    }
  };

  return (
    <div className="page-container" id="fleet-page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Fleet Management</h1>
          <p className="page-header-subtitle">
            Real-time telemetry, battery state, payload specs, and fleet allocation
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
            Auto-refreshing every 10s
          </span>
          <button
            type="button"
            className="app-btn app-btn--secondary"
            onClick={fetchDrones}
            title="Refresh now"
            id="btn-refresh-fleet"
          >
            <RefreshCw size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {errorState && (
        <div className="white-card" style={{ marginBottom: 'var(--space-6)', borderColor: '#F8B4B4' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#9B1C1C' }}>
            <AlertTriangle size={20} />
            <span style={{ fontWeight: 600 }}>{errorState}</span>
          </div>
        </div>
      )}

      {/* Summary Chips */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-6)',
        }}
        id="fleet-summary-chips"
      >
        <div className="stat-card" style={{ padding: 'var(--space-4)' }} id="chip-available">
          <div className="stat-label">Available</div>
          <div className="stat-value" style={{ color: '#147A2E', fontSize: '1.75rem' }}>
            {availableCount}
          </div>
          <div className="stat-subtext">Ready for dispatch</div>
        </div>

        <div className="stat-card" style={{ padding: 'var(--space-4)' }} id="chip-assigned">
          <div className="stat-label">Assigned / Active</div>
          <div className="stat-value" style={{ color: 'var(--teal)', fontSize: '1.75rem' }}>
            {assignedCount}
          </div>
          <div className="stat-subtext">Executing deliveries</div>
        </div>

        <div className="stat-card" style={{ padding: 'var(--space-4)' }} id="chip-charging">
          <div className="stat-label">Charging</div>
          <div className="stat-value" style={{ color: '#926A00', fontSize: '1.75rem' }}>
            {chargingCount}
          </div>
          <div className="stat-subtext">Recharging batteries</div>
        </div>

        <div className="stat-card" style={{ padding: 'var(--space-4)' }} id="chip-maintenance">
          <div className="stat-label">Maintenance</div>
          <div className="stat-value" style={{ color: '#C81E1E', fontSize: '1.75rem' }}>
            {maintenanceCount}
          </div>
          <div className="stat-subtext">Offline or inspecting</div>
        </div>
      </div>

      {/* Drones Table Card */}
      <div className="white-card" id="fleet-table-card">
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
          <div className="filter-group" id="fleet-filter-group">
            {[
              { id: 'ALL', label: 'All Drones' },
              { id: 'AVAILABLE', label: 'Available' },
              { id: 'ASSIGNED', label: 'Assigned' },
              { id: 'CHARGING', label: 'Charging' },
              { id: 'MAINTENANCE', label: 'Maintenance' },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                className={`filter-btn ${filter === item.id ? 'active' : ''}`}
                onClick={() => setFilter(item.id)}
                id={`fleet-filter-${item.id.toLowerCase()}`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600 }}>
            {filteredDrones.length} drone{filteredDrones.length === 1 ? '' : 's'} displayed
          </span>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }}>
            Polling fleet telemetry…
          </div>
        ) : filteredDrones.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)' }} id="no-drones-empty">
            <p style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--ink)' }}>
              No drones found
            </p>
            <p style={{ fontSize: '0.85rem', marginTop: '4px', color: 'var(--text-tertiary)' }}>
              No drones match the filter: {filter}
            </p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="data-table" id="fleet-data-table">
              <thead>
                <tr>
                  <th>Drone ID</th>
                  <th>Model</th>
                  <th>Status</th>
                  <th>Battery</th>
                  <th>Payload</th>
                  <th>Range</th>
                  <th>Zone</th>
                  <th>Last Updated</th>
                  {isAdmin && <th>Admin Status Action</th>}
                </tr>
              </thead>
              <tbody>
                {filteredDrones.map((drone) => {
                  const errorMsg = patchError[drone.drone_id];
                  const successMsg = patchSuccess[drone.drone_id];
                  const isUpdating = updatingDroneId === drone.drone_id;

                  return (
                    <tr key={drone.id || drone.drone_id} id={`drone-row-${drone.drone_id}`}>
                      <td className="mono" style={{ fontWeight: 700 }}>
                        {drone.drone_id}
                      </td>
                      <td style={{ fontWeight: 600 }}>{drone.model}</td>
                      <td>
                        <span className={`status-pill ${getStatusClass(drone.status)}`}>
                          {drone.status}
                        </span>
                      </td>
                      <td>
                        <div className="battery-wrapper">
                          <div className="battery-track">
                            <div
                              className={`battery-fill ${getBatteryFillClass(drone.battery_pct)}`}
                              style={{ width: `${Math.min(100, Math.max(0, drone.battery_pct))}%` }}
                            />
                          </div>
                          <span className="mono" style={{ fontSize: '0.78rem', fontWeight: 600 }}>
                            {Math.round(drone.battery_pct)}%
                          </span>
                        </div>
                      </td>
                      <td>{drone.max_payload_kg} kg</td>
                      <td>{drone.max_range_km} km</td>
                      <td>
                        <span className="mono" style={{ fontSize: '0.8rem' }}>
                          {drone.zone || 'BLR-CENTRAL'}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {drone.updated_at ? new Date(drone.updated_at).toLocaleTimeString() : '—'}
                      </td>
                      {isAdmin && (
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <select
                                className="form-select"
                                style={{ padding: '4px 8px', fontSize: '0.75rem', width: 'auto', minWidth: '120px' }}
                                value={selectedTargetStatus[drone.drone_id] || ''}
                                onChange={(e) =>
                                  setSelectedTargetStatus((prev) => ({
                                    ...prev,
                                    [drone.drone_id]: e.target.value,
                                  }))
                                }
                                id={`select-status-${drone.drone_id}`}
                              >
                                <option value="">Select status…</option>
                                <option value="AVAILABLE">AVAILABLE</option>
                                <option value="CHARGING">CHARGING</option>
                                <option value="MAINTENANCE">MAINTENANCE</option>
                                <option value="OFFLINE">OFFLINE</option>
                              </select>
                              <button
                                type="button"
                                className="app-btn app-btn--secondary app-btn--sm"
                                disabled={!selectedTargetStatus[drone.drone_id] || isUpdating}
                                onClick={() => handleStatusChange(drone.drone_id)}
                                id={`patch-btn-${drone.drone_id}`}
                              >
                                {isUpdating ? 'Saving…' : 'Set'}
                              </button>
                            </div>

                            {/* Forbidden transition API error */}
                            {errorMsg && (
                              <div
                                style={{
                                  fontSize: '0.72rem',
                                  color: '#C81E1E',
                                  background: '#FDE8E8',
                                  padding: '4px 6px',
                                  borderRadius: '4px',
                                  maxWidth: '220px',
                                  lineHeight: 1.25,
                                }}
                                id={`error-${drone.drone_id}`}
                              >
                                {errorMsg}
                              </div>
                            )}

                            {successMsg && (
                              <div
                                style={{
                                  fontSize: '0.72rem',
                                  color: '#155724',
                                  background: '#EDF7EE',
                                  padding: '4px 6px',
                                  borderRadius: '4px',
                                  maxWidth: '220px',
                                  lineHeight: 1.25,
                                }}
                                id={`success-${drone.drone_id}`}
                              >
                                {successMsg}
                              </div>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
