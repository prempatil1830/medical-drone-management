import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { Plus } from 'lucide-react';

export default function RequestPage() {
  const [centers, setCenters] = useState([]);
  const [centersLoading, setCentersLoading] = useState(true);
  
  const [showCenterForm, setShowCenterForm] = useState(false);
  const [centerName, setCenterName] = useState('');
  const [centerType, setCenterType] = useState('hospital');
  const [centerAddress, setCenterAddress] = useState('');
  const [centerLat, setCenterLat] = useState(12.9716);
  const [centerLng, setCenterLng] = useState(77.5946);
  const [centerContact, setCenterContact] = useState('+91-80-55555555');
  const [centerError, setCenterError] = useState(null);
  
  const [centerId, setCenterId] = useState('');
  const [medicalType, setMedicalType] = useState('Vaccines');
  const [quantity, setQuantity] = useState(10);
  const [weightKg, setWeightKg] = useState(1.5);
  const [urgency, setUrgency] = useState('MEDIUM');
  const [pickupLat, setPickupLat] = useState(12.9716);
  const [pickupLng, setPickupLng] = useState(77.5946);
  const [destLat, setDestLat] = useState(12.9352);
  const [destLng, setDestLng] = useState(77.6245);
  
  const [loading, setLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [generalError, setGeneralError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  
  const navigate = useNavigate();

  const fetchCenters = async () => {
    setCentersLoading(true);
    try {
      const response = await api.get('/medical-centers/');
      setCenters(response.data);
      if (response.data.length > 0) {
        setCenterId(response.data[0].id);
      }
    } catch (err) {
      console.error('Failed to load medical centers:', err);
    } finally {
      setCentersLoading(false);
    }
  };

  useEffect(() => {
    fetchCenters();
  }, []);

  const handleCreateCenter = async (e) => {
    e.preventDefault();
    setCenterError(null);
    try {
      const payload = {
        name: centerName,
        type: centerType,
        address: centerAddress,
        latitude: parseFloat(centerLat),
        longitude: parseFloat(centerLng),
        contact: centerContact
      };
      const response = await api.post('/medical-centers/', payload);
      const newCenter = response.data;
      setCenters([...centers, newCenter]);
      setCenterId(newCenter.id);
      setShowCenterForm(false);
      setCenterName('');
      setCenterAddress('');
    } catch (err) {
      setCenterError(err.response?.data?.detail || 'Failed to create medical center. Verify coordinates (-90 to 90 lat, -180 to 180 lng).');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setFieldErrors({});
    setGeneralError(null);
    setSuccessMsg(null);

    if (!centerId) {
      setGeneralError('Please select or register a medical center first.');
      setLoading(false);
      return;
    }

    const payload = {
      center_id: centerId,
      medical_type: medicalType,
      quantity: parseInt(quantity),
      weight_kg: parseFloat(weightKg),
      urgency,
      pickup: {
        lat: parseFloat(pickupLat),
        lng: parseFloat(pickupLng)
      },
      destination: {
        lat: parseFloat(destLat),
        lng: parseFloat(destLng)
      }
    };

    try {
      await api.post('/requests/', payload);
      setSuccessMsg('Medical dispatch request submitted successfully!');
      setTimeout(() => {
        navigate('/request-queue');
      }, 1500);
    } catch (err) {
      if (err.response && err.response.status === 422) {
        const details = err.response.data.detail;
        const errors = {};
        if (Array.isArray(details)) {
          details.forEach((item) => {
            const path = item.loc.slice(1).join('.');
            errors[path] = item.msg;
          });
        }
        setFieldErrors(errors);
      } else {
        setGeneralError(err.response?.data?.detail || 'An unexpected error occurred.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="page-title">Submit Dispatch Request</h1>
        <p className="page-subtitle">Schedule a new medical payload delivery.</p>
      </div>

      {generalError && <div className="alert alert-danger mb-6">{generalError}</div>}
      {successMsg && <div className="alert alert-success mb-6">{successMsg}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: showCenterForm ? '1fr' : '2fr 1fr', gap: '2rem', alignItems: 'start' }}>
        
        {!showCenterForm && (
          <Card>
            <h2 className="card-title">Payload & Route Specifications</h2>
            
            <form onSubmit={handleSubmit}>
              
              <div className="form-group">
                <label className="form-label" htmlFor="centerId">Originating Medical Center</label>
                {centersLoading ? (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Loading centers...</p>
                ) : (
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <div style={{ flex: 1 }}>
                      <select
                        id="centerId"
                        className={`form-control ${fieldErrors['center_id'] ? 'is-invalid' : ''}`}
                        value={centerId}
                        onChange={(e) => setCenterId(e.target.value)}
                      >
                        {centers.map(c => (
                          <option key={c.id} value={c.id}>{c.name} ({c.type})</option>
                        ))}
                      </select>
                      {fieldErrors['center_id'] && <span className="invalid-feedback">{fieldErrors['center_id']}</span>}
                    </div>
                    <Button variant="secondary" type="button" onClick={() => setShowCenterForm(true)}>
                      <Plus size={16} /> Add New
                    </Button>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <Select
                  label="Medical Supply Type"
                  id="medicalType"
                  value={medicalType}
                  onChange={(e) => setMedicalType(e.target.value)}
                  error={fieldErrors['medical_type']}
                >
                  <option value="Vaccines">Vaccines</option>
                  <option value="Blood">Blood</option>
                  <option value="Organs">Organs</option>
                  <option value="Emergency Medicine">Emergency Medicine</option>
                  <option value="Plasma">Plasma</option>
                  <option value="Insulin">Insulin</option>
                  <option value="Other">Other</option>
                </Select>

                <Select
                  label="Urgency Priority"
                  id="urgency"
                  value={urgency}
                  onChange={(e) => setUrgency(e.target.value)}
                  error={fieldErrors['urgency']}
                >
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                  <option value="CRITICAL">Critical</option>
                </Select>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <Input
                  label="Quantity (Units)"
                  type="number"
                  id="quantity"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  error={fieldErrors['quantity']}
                  required
                />
                
                <Input
                  label="Total Weight (kg)"
                  type="number"
                  step="0.1"
                  id="weightKg"
                  value={weightKg}
                  onChange={(e) => setWeightKg(e.target.value)}
                  error={fieldErrors['weight_kg']}
                  required
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '1rem', borderTop: '1px solid var(--separator-color)', paddingTop: '1.5rem' }}>
                
                <div>
                  <h3 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '1rem' }}>Pickup Location</h3>
                  <Input
                    label="Latitude"
                    type="number"
                    step="0.0001"
                    value={pickupLat}
                    onChange={(e) => setPickupLat(e.target.value)}
                    error={fieldErrors['pickup.lat']}
                    required
                  />
                  <Input
                    label="Longitude"
                    type="number"
                    step="0.0001"
                    value={pickupLng}
                    onChange={(e) => setPickupLng(e.target.value)}
                    error={fieldErrors['pickup.lng']}
                    required
                  />
                </div>

                <div>
                  <h3 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '1rem' }}>Destination Location</h3>
                  <Input
                    label="Latitude"
                    type="number"
                    step="0.0001"
                    value={destLat}
                    onChange={(e) => setDestLat(e.target.value)}
                    error={fieldErrors['destination.lat']}
                    required
                  />
                  <Input
                    label="Longitude"
                    type="number"
                    step="0.0001"
                    value={destLng}
                    onChange={(e) => setDestLng(e.target.value)}
                    error={fieldErrors['destination.lng']}
                    required
                  />
                </div>

              </div>

              <Button variant="primary" type="submit" style={{ width: '100%', marginTop: '1.5rem' }} disabled={loading}>
                {loading ? 'Submitting Request...' : 'Dispatch Drone'}
              </Button>
            </form>
          </Card>
        )}

        {!showCenterForm && (
          <Card style={{ padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Validation Rules</h3>
            <ul style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.75rem', paddingLeft: '1.25rem' }}>
              <li>Quantity must be a positive integer greater than zero.</li>
              <li>Weight must be a positive number greater than zero.</li>
              <li>Coordinates must fit geographic limits:
                <ul style={{ marginTop: '0.25rem', paddingLeft: '1rem' }}>
                  <li>Latitude: -90.0 to 90.0</li>
                  <li>Longitude: -180.0 to 180.0</li>
                </ul>
              </li>
              <li>Ensure the Originating Medical Center exists in the network.</li>
            </ul>
          </Card>
        )}

        {showCenterForm && (
          <Card style={{ maxWidth: '600px', margin: '0 auto' }}>
            <h2 className="card-title">Register Medical Center</h2>
            <p className="card-description">Add a node to support dispatch references.</p>
            
            {centerError && <div className="alert alert-danger mb-4">{centerError}</div>}
            
            <form onSubmit={handleCreateCenter}>
              <Input
                label="Center Name"
                type="text"
                id="centerName"
                placeholder="e.g. St. John's Clinic"
                value={centerName}
                onChange={(e) => setCenterName(e.target.value)}
                required
              />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <Select
                  label="Center Type"
                  id="centerType"
                  value={centerType}
                  onChange={(e) => setCenterType(e.target.value)}
                >
                  <option value="hospital">Hospital</option>
                  <option value="clinic">Clinic</option>
                  <option value="warehouse">Supply Depot</option>
                </Select>

                <Input
                  label="Contact Info"
                  type="text"
                  id="centerContact"
                  value={centerContact}
                  onChange={(e) => setCenterContact(e.target.value)}
                  required
                />
              </div>

              <Input
                label="Physical Address"
                type="text"
                id="centerAddress"
                placeholder="e.g. 12th Cross, Indiranagar"
                value={centerAddress}
                onChange={(e) => setCenterAddress(e.target.value)}
                required
              />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                <Input
                  label="Center Latitude"
                  type="number"
                  step="0.0001"
                  value={centerLat}
                  onChange={(e) => setCenterLat(e.target.value)}
                  required
                />
                <Input
                  label="Center Longitude"
                  type="number"
                  step="0.0001"
                  value={centerLng}
                  onChange={(e) => setCenterLng(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: '1rem', marginTop: '1.5rem' }}>
                <Button variant="primary" type="submit" style={{ flex: 1 }}>
                  Create Center
                </Button>
                <Button variant="secondary" type="button" onClick={() => setShowCenterForm(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          </Card>
        )}

      </div>
    </div>
  );
}
