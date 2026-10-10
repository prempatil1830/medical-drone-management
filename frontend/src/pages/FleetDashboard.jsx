import React, { useEffect, useState } from 'react';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { Plane } from 'lucide-react';

export default function FleetDashboard() {
  const [drones, setDrones] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('ALL');

  const fetchDrones = async () => {
    setLoading(true);
    setError(null);
    try {
      const url = filter === 'AVAILABLE' ? '/drones/available' : '/drones/';
      const response = await api.get(url);
      setDrones(response.data);
    } catch (err) {
      setError('Failed to fetch drone fleet. Please verify uvicorn is running.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDrones();
  }, [filter]);

  const getBatteryStyle = (pct) => {
    if (pct > 50) return 'battery-high';
    if (pct > 20) return 'battery-medium';
    return 'battery-low';
  };

  const getStatusBadgeVariant = (status) => {
    switch (status) {
      case 'AVAILABLE': return 'success';
      case 'CHARGING': return 'warning';
      case 'MAINTENANCE': return 'danger';
      case 'IN_FLIGHT': return 'info';
      case 'ASSIGNED': return 'info';
      default: return 'default';
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="page-title">Fleet Dashboard</h1>
          <p className="page-subtitle">Real-time telemetry and status monitoring of virtual drone fleet.</p>
        </div>
        
        <div style={{ display: 'flex', gap: '0.5rem', background: 'var(--bg-surface)', padding: '0.25rem', borderRadius: 'var(--radius-lg)', border: '1px solid var(--separator-color)' }}>
          <Button 
            variant={filter === 'ALL' ? 'primary' : 'secondary'}
            style={{ padding: '0.4rem 1rem', fontSize: 'var(--text-sm)', borderRadius: 'var(--radius-md)' }}
            onClick={() => setFilter('ALL')}
          >
            All Drones
          </Button>
          <Button 
            variant={filter === 'AVAILABLE' ? 'primary' : 'secondary'}
            style={{ padding: '0.4rem 1rem', fontSize: 'var(--text-sm)', borderRadius: 'var(--radius-md)' }}
            onClick={() => setFilter('AVAILABLE')}
          >
            Available Only
          </Button>
        </div>
      </div>

      {error && <div className="alert alert-danger mb-4">{error}</div>}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Polling fleet telemetry...</p>
        </div>
      ) : drones.length === 0 ? (
        <Card>
          <EmptyState icon={Plane} title="No Active Drones" description="No active drones matching filters. Run the seed script to spawn drones." />
        </Card>
      ) : (
        <div className="drones-grid">
          {drones.map((drone) => (
            <Card key={drone.id} style={{ padding: '1.5rem', position: 'relative', overflow: 'hidden' }}>
              
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{drone.model}</h3>
                  <span style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                    {drone.drone_id}
                  </span>
                </div>
                <Badge variant={getStatusBadgeVariant(drone.status)}>
                  {drone.status}
                </Badge>
              </div>

              <div style={{ marginBottom: '1.25rem' }}>
                <div className="flex justify-between mb-2" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <span>Battery</span>
                  <span style={{ fontWeight: 600, color: drone.battery_pct > 20 ? 'var(--text-primary)' : 'var(--status-danger)' }}>
                    {drone.battery_pct.toFixed(0)}%
                  </span>
                </div>
                <div className="battery-container" style={{ width: '100%' }}>
                  <div className="battery-bar-outer" style={{ width: '100%', height: '10px', border: '1px solid var(--separator-color)', borderRadius: '4px' }}>
                    <div 
                      className={`battery-bar-inner ${getBatteryStyle(drone.battery_pct)}`} 
                      style={{ width: `${drone.battery_pct}%`, height: '100%', borderRadius: '2px' }}
                    />
                  </div>
                </div>
              </div>

              <div style={{ borderTop: '1px solid var(--separator-color)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.65rem', fontSize: '0.85rem' }}>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-secondary)' }}>Zone</span>
                  <span style={{ fontWeight: 500 }}>{drone.zone}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-secondary)' }}>Capacity</span>
                  <span style={{ fontWeight: 500 }}>{drone.max_payload_kg} kg</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-secondary)' }}>Max Range</span>
                  <span style={{ fontWeight: 500 }}>{drone.max_range_km} km</span>
                </div>
                <div className="flex justify-between" style={{ borderTop: '1px dotted var(--separator-color)', paddingTop: '0.5rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Location</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                    {drone.latitude.toFixed(4)}, {drone.longitude.toFixed(4)}
                  </span>
                </div>
              </div>

            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
