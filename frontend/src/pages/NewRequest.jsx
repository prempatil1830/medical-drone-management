import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, AlertCircle } from 'lucide-react';
import api from '../services/api';
import { useAuthStore } from '../store/auth';

const MEDICAL_TYPES = [
  'Blood',
  'Organs',
  'Vaccines',
  'Emergency Medicine',
  'Plasma',
  'Insulin',
  'Other',
];

const URGENCIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

export default function NewRequest() {
  const { user } = useAuthStore();
  const navigate = useNavigate();

  const [centers, setCenters] = useState([]);
  const [centerId, setCenterId] = useState(user?.center_id || '');
  const [medicalType, setMedicalType] = useState('Blood');
  const [quantity, setQuantity] = useState(2);
  const [weightKg, setWeightKg] = useState(1.5);
  const [urgency, setUrgency] = useState('HIGH');

  // Pickup and Destination coordinates
  const [pickupLat, setPickupLat] = useState(12.9716);
  const [pickupLng, setPickupLng] = useState(77.5946);
  const [destLat, setDestLat] = useState(12.9352);
  const [destLng, setDestLng] = useState(77.6245);

  const [loading, setLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [generalError, setGeneralError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  useEffect(() => {
    async function loadCenters() {
      try {
        const res = await api.get('/medical-centers/');
        setCenters(res.data || []);
        if (!centerId && res.data && res.data.length > 0) {
          // If user has center_id, check if it matches, otherwise use first
          const matched = user?.center_id ? res.data.find(c => c.id === user.center_id) : null;
          setCenterId(matched ? matched.id : res.data[0].id);
        }
      } catch (err) {
        console.error('Failed to load centers:', err);
      }
    }
    loadCenters();
  }, [user, centerId]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setFieldErrors({});
    setGeneralError(null);
    setSuccessMsg(null);

    const activeCenterId = user?.center_id || centerId;

    if (!activeCenterId) {
      setGeneralError('No medical center assigned to your account or selected.');
      setLoading(false);
      return;
    }

    const payload = {
      center_id: activeCenterId,
      medical_type: medicalType,
      quantity: parseInt(quantity, 10),
      weight_kg: parseFloat(weightKg),
      urgency: urgency,
      pickup: {
        lat: parseFloat(pickupLat),
        lng: parseFloat(pickupLng),
      },
      destination: {
        lat: parseFloat(destLat),
        lng: parseFloat(destLng),
      },
    };

    try {
      const res = await api.post('/requests/', payload);
      const created = res.data;
      setSuccessMsg('Request submitted! AI engine evaluating weather & dispatching drone…');
      setTimeout(() => {
        // Direct jump to live mission tracking
        navigate(`/mission/${created.mission_id || created.request_id || created.id}`);
      }, 1200);
    } catch (err) {
      if (err.response?.status === 422) {
        const details = err.response.data?.detail;
        if (Array.isArray(details)) {
          const mapped = {};
          details.forEach((item) => {
            const field = item.loc?.[item.loc.length - 1];
            if (field) mapped[field] = item.msg;
          });
          setFieldErrors(mapped);
          setGeneralError('Please correct the validation errors below.');
        } else {
          setGeneralError(typeof details === 'string' ? details : 'Validation failed.');
        }
      } else if (err.response?.status === 403) {
        setGeneralError(err.response?.data?.detail || 'Forbidden: You do not have permission to submit for this center.');
      } else {
        setGeneralError(err.response?.data?.detail || 'Network error submitting delivery request.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container" id="new-request-page">
      <div style={{ maxWidth: '720px', margin: '0 auto' }}>
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Link to="/requests" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', fontWeight: 600 }}>
            <ArrowLeft size={16} />
            <span>Back to Requests</span>
          </Link>
        </div>

        <div className="white-card">
          <div style={{ marginBottom: 'var(--space-6)' }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--ink)' }}>
              Create Medical Delivery Request
            </h1>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Dispatch an urgent medical payload via autonomous drone
            </p>
          </div>

          {generalError && (
            <div
              className="flash-banner flash-banner--error"
              role="alert"
              style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-5)' }}
              id="new-request-error"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertCircle size={16} />
                <span>{generalError}</span>
              </div>
            </div>
          )}

          {successMsg && (
            <div
              className="flash-banner"
              style={{
                backgroundColor: '#EDF7EE',
                borderBottom: '1px solid #C3E6CB',
                color: '#155724',
                borderRadius: 'var(--radius-md)',
                marginBottom: 'var(--space-5)',
              }}
              id="new-request-success"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={16} />
                <span>{successMsg}</span>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate id="new-request-form">
            {/* Medical Center selection */}
            <div className="form-group">
              <label htmlFor="req-center" className="form-label">Originating Medical Center</label>
              {user?.center_id ? (
                <input
                  id="req-center"
                  className="form-input"
                  type="text"
                  value={centers.find(c => c.id === user.center_id)?.name || user.center_id}
                  disabled
                  style={{ backgroundColor: '#F8FAFC' }}
                />
              ) : (
                <select
                  id="req-center"
                  className={`form-select ${fieldErrors.center_id ? 'form-input--error' : ''}`}
                  value={centerId}
                  onChange={(e) => setCenterId(e.target.value)}
                  required
                >
                  {centers.length === 0 ? (
                    <option value="">No centers available</option>
                  ) : (
                    centers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.type})
                      </option>
                    ))
                  )}
                </select>
              )}
              {fieldErrors.center_id && <div className="field-error">{fieldErrors.center_id}</div>}
            </div>

            {/* Medical Type & Urgency */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
              <div className="form-group">
                <label htmlFor="req-type" className="form-label">Medical Supply Type</label>
                <select
                  id="req-type"
                  className="form-select"
                  value={medicalType}
                  onChange={(e) => setMedicalType(e.target.value)}
                >
                  {MEDICAL_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                {fieldErrors.medical_type && <div className="field-error">{fieldErrors.medical_type}</div>}
              </div>

              <div className="form-group">
                <label htmlFor="req-urgency" className="form-label">Urgency Tier</label>
                <select
                  id="req-urgency"
                  className="form-select"
                  value={urgency}
                  onChange={(e) => setUrgency(e.target.value)}
                >
                  {URGENCIES.map((u) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
                {fieldErrors.urgency && <div className="field-error">{fieldErrors.urgency}</div>}
              </div>
            </div>

            {/* Quantity and Weight */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
              <div className="form-group">
                <label htmlFor="req-quantity" className="form-label">Quantity (Units)</label>
                <input
                  id="req-quantity"
                  className={`form-input ${fieldErrors.quantity ? 'form-input--error' : ''}`}
                  type="number"
                  min="1"
                  max="100"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  required
                />
                {fieldErrors.quantity && <div className="field-error">{fieldErrors.quantity}</div>}
              </div>

              <div className="form-group">
                <label htmlFor="req-weight" className="form-label">Payload Weight (kg)</label>
                <input
                  id="req-weight"
                  className={`form-input ${fieldErrors.weight_kg ? 'form-input--error' : ''}`}
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="15"
                  value={weightKg}
                  onChange={(e) => setWeightKg(e.target.value)}
                  required
                />
                {fieldErrors.weight_kg && <div className="field-error">{fieldErrors.weight_kg}</div>}
              </div>
            </div>

            {/* Coordinates */}
            <div style={{ marginTop: 'var(--space-2)', marginBottom: 'var(--space-6)' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--ink)', marginBottom: 'var(--space-3)' }}>
                Flight Trajectory Coordinates
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                <div style={{ background: '#F8FAFC', padding: '12px', borderRadius: '8px', border: '1px solid rgba(11, 31, 51, 0.06)' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                    Pickup Location
                  </span>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px' }}>
                    <div>
                      <label className="form-label" style={{ fontSize: '0.65rem' }}>Latitude</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.0001"
                        value={pickupLat}
                        onChange={(e) => setPickupLat(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="form-label" style={{ fontSize: '0.65rem' }}>Longitude</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.0001"
                        value={pickupLng}
                        onChange={(e) => setPickupLng(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ background: '#F8FAFC', padding: '12px', borderRadius: '8px', border: '1px solid rgba(11, 31, 51, 0.06)' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                    Destination Location
                  </span>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px' }}>
                    <div>
                      <label className="form-label" style={{ fontSize: '0.65rem' }}>Latitude</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.0001"
                        value={destLat}
                        onChange={(e) => setDestLat(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="form-label" style={{ fontSize: '0.65rem' }}>Longitude</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.0001"
                        value={destLng}
                        onChange={(e) => setDestLng(e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <button
              className="app-btn app-btn--primary"
              type="submit"
              disabled={loading || successMsg}
              style={{ width: '100%', padding: '12px', fontSize: '1rem' }}
              id="submit-request-btn"
            >
              {loading ? 'Submitting Request…' : 'Submit Delivery Request'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
