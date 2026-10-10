import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Table } from '../components/ui/Table';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { EmptyState } from '../components/ui/EmptyState';
import { Search } from 'lucide-react';

export default function RequestQueue() {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  const [centersMap, setCentersMap] = useState({});
  
  const [statusFilter, setStatusFilter] = useState('');
  const [urgencyFilter, setUrgencyFilter] = useState('');
  
  const [skip, setSkip] = useState(0);
  const LIMIT = 10;
  const [hasMore, setHasMore] = useState(true);

  useEffect(() => {
    async function loadCenters() {
      try {
        const response = await api.get('/medical-centers/');
        const mapping = {};
        response.data.forEach(center => {
          mapping[center.id] = center.name;
        });
        setCentersMap(mapping);
      } catch (err) {
        console.error('Failed to load centers list for mapping:', err);
      }
    }
    loadCenters();
  }, []);

  const fetchRequests = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        skip,
        limit: LIMIT,
      };
      if (statusFilter) params.status = statusFilter;
      if (urgencyFilter) params.urgency = urgencyFilter;

      const response = await api.get('/requests/', { params });
      const data = response.data;
      setRequests(data);
      
      setHasMore(data.length === LIMIT);
    } catch (err) {
      setError('Failed to fetch request queue. Please check server connection.');
    } finally {
      setLoading(false);
    }
  };

  const [dispatchingId, setDispatchingId] = useState(null);

  const handleDispatch = async (reqId) => {
    setDispatchingId(reqId);
    setError(null);
    try {
      const response = await api.post(`/requests/${reqId}/dispatch`);
      const data = response.data;
      if (data.mission_id) {
        alert(`Dispatch successful! Mission created: ${data.mission_id}`);
      } else if (data.weather_halted) {
        alert(`Dispatch Halted: Weather is UNSAFE.`);
      } else if (data.safety_decision && data.safety_decision !== 'PASS') {
        alert(`Dispatch Halted by Safety Agent: ${data.safety_reason}`);
      } else {
        alert(`Dispatch completed: ${data.allocation_reason}`);
      }
      fetchRequests();
    } catch (err) {
      setError(err.response?.data?.detail || 'Dispatch failed.');
    } finally {
      setDispatchingId(null);
    }
  };

  useEffect(() => {
    fetchRequests();
  }, [skip, statusFilter, urgencyFilter]);

  const handleFilterChange = (type, val) => {
    setSkip(0);
    if (type === 'status') setStatusFilter(val);
    if (type === 'urgency') setUrgencyFilter(val);
  };

  const getAgeString = (isoString) => {
    const created = new Date(isoString);
    const now = new Date();
    const diffMs = now - created;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    
    return created.toLocaleDateString(undefined, { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="page-title">Request Queue</h1>
          <p className="page-subtitle">Monitored queue of all medical payload requests.</p>
        </div>
      </div>

      {error && <div className="alert alert-danger mb-4">{error}</div>}

      <Card className="mb-6" style={{ padding: '1rem 1.5rem' }}>
        <div className="flex items-center gap-4 flex-wrap">
          <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Filters:</span>
          
          <div className="flex items-center gap-2">
            <label style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>Status</label>
            <Select
              style={{ width: '150px', minHeight: '36px' }}
              value={statusFilter}
              onChange={(e) => handleFilterChange('status', e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="PENDING">Pending</option>
              <option value="ASSIGNED">Assigned</option>
              <option value="IN_TRANSIT">In Transit</option>
              <option value="DELIVERED">Delivered</option>
              <option value="CANCELLED">Cancelled</option>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <label style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>Urgency</label>
            <Select
              style={{ width: '150px', minHeight: '36px' }}
              value={urgencyFilter}
              onChange={(e) => handleFilterChange('urgency', e.target.value)}
            >
              <option value="">All Priorities</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </Select>
          </div>
        </div>
      </Card>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Fetching queue data...</p>
        </div>
      ) : requests.length === 0 ? (
        <Card>
          <EmptyState icon={Search} title="No Requests Found" description="No medical delivery requests match your active filters." />
        </Card>
      ) : (
        <Card style={{ padding: '0', overflow: 'hidden' }}>
          <Table>
            <thead>
              <tr>
                <th>Request ID</th>
                <th>Center Node</th>
                <th>Medical Supply Type</th>
                <th>Quantity & Weight</th>
                <th>Urgency</th>
                <th>Time Elapsed</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((req) => (
                <tr key={req.id}>
                  <td style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                    {req.request_id.slice(0, 8)}...
                  </td>
                  <td style={{ fontWeight: 500 }}>
                    {centersMap[req.center_id] || req.center_id}
                  </td>
                  <td>{req.medical_type}</td>
                  <td>
                    {req.quantity} units ({req.weight_kg} kg)
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className={`urgency-indicator urgency-${req.urgency}`} />
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{req.urgency}</span>
                    </div>
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>
                    {getAgeString(req.created_at)}
                  </td>
                  <td>
                    <Badge variant={req.status === 'PENDING' ? 'warning' : req.status === 'ASSIGNED' ? 'info' : req.status === 'DELIVERED' ? 'success' : 'default'}>
                      {req.status}
                    </Badge>
                  </td>
                  <td>
                    {req.status === 'PENDING' ? (
                      <Button
                        variant="primary"
                        style={{ padding: '4px 12px', minHeight: '32px' }}
                        disabled={dispatchingId !== null}
                        onClick={() => handleDispatch(req.id)}
                      >
                        {dispatchingId === req.id ? 'Dispatching...' : 'Dispatch'}
                      </Button>
                    ) : req.mission_id ? (
                      <Link to={`/missions/${req.mission_id}`} style={{ textDecoration: 'none' }}>
                        <Button variant="secondary" style={{ padding: '4px 12px', minHeight: '32px' }}>
                          Track Live
                        </Button>
                      </Link>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)' }}>-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          
          <div className="flex justify-between items-center" style={{ padding: '1rem 1.5rem', borderTop: '1px solid var(--separator-color)' }}>
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
              Showing records {skip + 1} - {skip + requests.length}
            </div>
            <div className="flex gap-2">
              <Button 
                variant="secondary"
                onClick={() => setSkip(Math.max(0, skip - LIMIT))}
                disabled={skip === 0}
              >
                Previous
              </Button>
              <Button 
                variant="secondary"
                onClick={() => setSkip(skip + LIMIT)}
                disabled={!hasMore}
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
