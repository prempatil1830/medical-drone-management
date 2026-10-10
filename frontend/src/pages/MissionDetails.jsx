import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Plane, AlertTriangle, ArrowLeft, Navigation } from 'lucide-react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import api from '../services/api';
import { useAuthStore } from '../store/auth';

const TIMELINE_STEPS = [
  { status: 'ASSIGNED', label: 'Drone assigned' },
  { status: 'TRAVELLING_TO_PICKUP', label: 'Heading to pickup' },
  { status: 'PACKAGE_COLLECTED', label: 'Package collected' },
  { status: 'IN_TRANSIT', label: 'In transit' },
  { status: 'APPROACHING_DESTINATION', label: 'Approaching destination' },
  { status: 'DELIVERED', label: 'Delivered' }
];

export default function MissionDetails() {
  const { id } = useParams();
  const { token, user } = useAuthStore();
  const isHospital = user?.role === 'hospital' || user?.role === 'hospital_admin';

  const [mission, setMission] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);
  
  const [droneLocation, setDroneLocation] = useState(null);
  const [droneHeading, setDroneHeading] = useState(0);

  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const animationRef = useRef(null);

  const applyPalette = useCallback((map) => {
    if (!map.isStyleLoaded()) return;
    const layers = map.getStyle().layers || [];
    for (const layer of layers) {
      try {
        if (layer.id.includes('water') && layer.type === 'fill') {
          map.setPaintProperty(layer.id, 'fill-color', '#BBDDEB');
        }
        if ((layer.id === 'background' || layer.id.includes('landcover') || layer.id.includes('landuse')) && layer.type === 'fill') {
          map.setPaintProperty(layer.id, 'fill-color', '#E6ECEE');
        }
        if (layer.id.includes('park') && layer.type === 'fill') {
          map.setPaintProperty(layer.id, 'fill-color', '#CFE6D2');
          map.setPaintProperty(layer.id, 'fill-opacity', 1.0);
        }
        if (layer.id.includes('building') && layer.type === 'fill') {
          map.setPaintProperty(layer.id, 'fill-color', '#D0D6D9');
        }
      } catch (e) {}
    }
  }, []);

  const fetchMission = async () => {
    try {
      setLoading(true);
      const res = await api.get(`/missions/${id}/`);
      setMission(res.data);
      if (res.data.current_lat && res.data.current_lng) {
        setDroneLocation([res.data.current_lng, res.data.current_lat]);
      }
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
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMission();
  }, [id, isHospital]);

  // WebSocket
  useEffect(() => {
    if (!mission || !token || errorState) return;
    
    // In dev, assuming the backend WS is available. 
    // Format: ws://localhost:8000/api/missions/{id}/ws?token={token}
    const wsUrl = `ws://localhost:8000/api/missions/${id}/ws?token=${token}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'telemetry') {
        const newLoc = [data.data.longitude, data.data.latitude];
        if (data.data.heading !== undefined) setDroneHeading(data.data.heading);
        
        // Simple interpolation could be done via requestAnimationFrame, but for the spike
        // we'll just update state which updates the marker location instantly (MapLibre doesn't tween markers automatically)
        setDroneLocation(newLoc);
        
        if (mapRef.current && markerRef.current) {
          markerRef.current.setLngLat(newLoc);
          const el = markerRef.current.getElement();
          if (el) el.style.transform = `${el.style.transform} rotate(${data.data.heading || 0}deg)`;
        }
      } else if (data.type === 'status_update') {
        setMission(prev => ({ ...prev, status: data.data.status }));
      }
    };

    return () => ws.close();
  }, [mission?.id, token, errorState]);

  // Map Initialization
  useEffect(() => {
    if (!mapContainer.current || loading || errorState) return;
    if (mapRef.current) return;

    try {
      const map = new maplibregl.Map({
        container: mapContainer.current,
        style: 'https://tiles.openfreemap.org/styles/positron',
        center: droneLocation || [77.5946, 12.9716],
        zoom: 14,
        attributionControl: true
      });

      map.on('style.load', () => {
        applyPalette(map);
        
        if (mission?.route?.coordinates) {
          const coords = mission.route.coordinates.map(c => [c[1], c[0]]); // assuming backend gives [lat, lng]
          map.addSource('route', {
            type: 'geojson',
            data: {
              type: 'Feature',
              properties: {},
              geometry: { type: 'LineString', coordinates: coords }
            }
          });
          map.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route',
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint: { 'line-color': '#4A5B6C', 'line-width': 4, 'line-dasharray': [2, 2] }
          });
        }
      });

      const el = document.createElement('div');
      el.className = 'drone-marker';
      el.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="#0B1F33"><path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>`;
      
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat(droneLocation || [77.5946, 12.9716])
        .addTo(map);

      mapRef.current = map;
      markerRef.current = marker;
    } catch (e) {
      console.error("MapLibre failed to load", e);
      setErrorState('Failed to load map style or engine.');
    }
  }, [loading, errorState, mission, droneLocation]);

  const recenterMap = () => {
    if (mapRef.current && droneLocation) {
      mapRef.current.flyTo({ center: droneLocation, zoom: 15, duration: 800 });
    }
  };

  if (loading) {
    return <div style={{ padding: '24px', fontFamily: 'var(--font-sans)', color: 'var(--ink)' }}>Loading mission data...</div>;
  }

  if (errorState) {
    return (
      <div style={{ padding: '24px', maxWidth: '600px', margin: '40px auto' }}>
        <div className="hud-panel" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'var(--red)', marginBottom: '16px' }}>
            <AlertTriangle size={24} />
            <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0, fontSize: '20px' }}>Access Error</h2>
          </div>
          <p style={{ fontFamily: 'var(--font-sans)', color: 'var(--text-secondary)' }}>{errorState}</p>
          <Link to="/" style={{ display: 'inline-block', marginTop: '16px', color: 'var(--accent-color)', fontWeight: 600 }}>← Return to Dashboard</Link>
        </div>
      </div>
    );
  }

  const isFailed = mission.status === 'FAILED' || mission.status === 'CANCELLED';

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: 'var(--bg-main)' }}>
      {/* Sidebar Panel */}
      <div className="mission-sidebar" style={{ width: '400px', flexShrink: 0, background: 'var(--bg-surface)', borderRight: '1px solid var(--separator-color)', display: 'flex', flexDirection: 'column', zIndex: 10, boxShadow: 'var(--shadow-md)' }}>
        
        <div style={{ padding: '20px', borderBottom: '1px solid var(--separator-color)', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link to="/" style={{ color: 'var(--text-secondary)' }}><ArrowLeft size={20} /></Link>
          <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', margin: 0, color: 'var(--ink)' }}>
            Mission {mission.id.split('-')[0]}
          </h1>
        </div>

        <div style={{ padding: '20px', flex: 1, overflowY: 'auto' }}>
          
          <div style={{ display: 'flex', gap: '16px', marginBottom: '24px' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '4px' }}>Drone</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: 'var(--ink)' }}>{mission.drone_id}</div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '4px' }}>ETA</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: 'var(--ink)' }}>
                {mission.estimated_arrival_time ? new Date(mission.estimated_arrival_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}
              </div>
            </div>
          </div>

          {mission.weather && (
            <div style={{ padding: '12px', background: 'var(--bg-main)', borderRadius: 'var(--radius-md)', marginBottom: '24px', border: '1px solid var(--separator-color)' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>WEATHER</span>
              <div style={{ fontSize: '14px', color: 'var(--ink)', marginTop: '4px' }}>{mission.weather.condition} • {mission.weather.wind_kph} km/h</div>
            </div>
          )}

          {isFailed ? (
            <div style={{ background: 'var(--red-dim)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(217, 58, 31, 0.2)' }}>
              <div style={{ color: 'var(--red)', fontWeight: 700, fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '8px' }}>Mission Failed</div>
              <div style={{ color: 'var(--ink)', fontFamily: 'var(--font-sans)', fontSize: '14px' }}>
                {mission.failure_reason || 'Unknown error occurred during flight.'}
              </div>
            </div>
          ) : (
            <div className="timeline" style={{ position: 'relative', paddingLeft: '16px' }}>
              <div style={{ position: 'absolute', top: 0, bottom: 0, left: '7px', width: '2px', background: 'var(--separator-color)' }} />
              
              {TIMELINE_STEPS.map((step, idx) => {
                const currentIdx = TIMELINE_STEPS.findIndex(s => s.status === mission.status);
                const isPast = idx < currentIdx;
                const isCurrent = idx === currentIdx;
                
                return (
                  <div key={step.status} style={{ position: 'relative', marginBottom: '24px', opacity: isPast || isCurrent ? 1 : 0.4 }}>
                    <div style={{ 
                      position: 'absolute', left: '-16px', top: '4px', width: '10px', height: '10px', borderRadius: '50%', 
                      background: isPast ? 'var(--teal)' : isCurrent ? 'var(--accent-color)' : 'var(--bg-main)',
                      border: isPast || isCurrent ? 'none' : '2px solid var(--text-tertiary)',
                      boxShadow: isCurrent ? '0 0 0 3px var(--focus-ring)' : 'none',
                      zIndex: 2
                    }} />
                    <div style={{ fontFamily: 'var(--font-sans)', fontSize: '14px', fontWeight: isCurrent ? 700 : 500, color: isCurrent ? 'var(--ink)' : 'var(--text-secondary)' }}>
                      {step.label}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Map Area */}
      <div style={{ flex: 1, position: 'relative' }}>
        <div ref={mapContainer} style={{ width: '100%', height: '100%' }} />
        <button 
          onClick={recenterMap}
          style={{ position: 'absolute', bottom: '24px', right: '24px', background: 'var(--bg-surface)', border: '1px solid var(--separator-color)', padding: '12px', borderRadius: '50%', cursor: 'pointer', boxShadow: 'var(--shadow-md)', color: 'var(--ink)' }}
          title="Recenter Map"
        >
          <Navigation size={20} />
        </button>
      </div>
    </div>
  );
}
