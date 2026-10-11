import React, { useEffect, useState, useRef, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import WorldMap, { getMap } from '../components/WorldMap';
import api from '../services/api';
import { useAuthStore } from '../store/auth';
import { useDeliveryStore } from '../store/deliveryStore';
import maplibregl from 'maplibre-gl/dist/maplibre-gl-csp';
import { ShieldAlert, ArrowLeft, CheckCircle2, Play, FastForward, Navigation, Home, Package } from 'lucide-react';
import { getRoadCorridorRoute } from '../utils/roadCorridorRouter';

const { Marker, LngLatBounds } = maplibregl;

// ── 4 Bangalore Division Regional Hubs ──────────────────────────────────────────
export const BANGALORE_HUBS = [
  {
    division: 'North',
    name: 'Bangalore North Drone Hub (Yelahanka Base)',
    shortName: 'North Base Hub',
    coords: [77.5963, 13.0645], // [lng, lat]
  },
  {
    division: 'South',
    name: 'Bangalore South Drone Hub (Electronic City Base)',
    shortName: 'South Base Hub',
    coords: [77.6389, 12.8452],
  },
  {
    division: 'East',
    name: 'Bangalore East Drone Hub (Whitefield Base)',
    shortName: 'East Base Hub',
    coords: [77.7499, 12.9698],
  },
  {
    division: 'West',
    name: 'Bangalore West Drone Hub (Rajajinagar Base)',
    shortName: 'West Base Hub',
    coords: [77.5450, 12.9880],
  },
  {
    division: 'Central',
    name: 'Bangalore Central Base Hub (MG Road)',
    shortName: 'Central Base Hub',
    coords: [77.5946, 12.9716],
  },
];

function getClosestHub(pickupCoords) {
  if (!pickupCoords || pickupCoords.length < 2) return BANGALORE_HUBS[4];
  let minD = Infinity;
  let best = BANGALORE_HUBS[4];
  for (const hub of BANGALORE_HUBS) {
    const d = Math.hypot(hub.coords[0] - pickupCoords[0], hub.coords[1] - pickupCoords[1]);
    if (d < minD) {
      minD = d;
      best = hub;
    }
  }
  return best;
}

export default function MissionDetails() {
  const { id } = useParams();
  const { user } = useAuthStore();
  const markDelivered = useDeliveryStore((state) => state.markDelivered);
  const isAlreadyDelivered = useDeliveryStore((state) => state.isDelivered(id));

  const [mission, setMission] = useState(null);
  const [errorState, setErrorState] = useState(null);
  const [simSpeed, setSimSpeed] = useState(1); // 1 = 1x (realistic ~1.4s), 2 = 2x (~0.7s)

  const markersRef = useRef([]);

  // Fetch real mission or request data
  useEffect(() => {
    let isMounted = true;
    setErrorState(null);

    async function loadData() {
      try {
        // 1. Try fetching real mission from backend
        const missionRes = await api.get(`/missions/${id}`);
        if (!isMounted) return;
        const m = missionRes.data;
        const backendCoords = (m.route || []).map((pt) => [pt.lng, pt.lat]);
        const pickup = backendCoords[0] || [77.5946, 12.9716];
        const dest = backendCoords[backendCoords.length - 1] || [77.6036, 12.9806];
        const hub = getClosestHub(pickup);

        // Build 2-leg corridor route: Hub -> Pickup (Leg 1) and Pickup -> Dest (Leg 2)
        // Drone strictly follows designated road air corridors to avoid all buildings
        const leg1 = await getRoadCorridorRoute(hub.coords, pickup, 16);
        const leg2 = (backendCoords.length > 5)
          ? backendCoords
          : await getRoadCorridorRoute(pickup, dest, 22);
        const fullFlightPath = [...leg1, ...leg2.slice(1)];
        const totalKm = (m.distance_km || 4.2) + 2.5;

        const deliveredInitially = isAlreadyDelivered || m.status === 'DELIVERED';

        if (!isMounted) return;
        setMission({
          id: m.mission_id || m.id,
          request_id: m.request_id || id,
          status: deliveredInitially ? 'DELIVERED' : m.status,
          drone_id: m.drone_id || 'DRN-001',
          pickup_name: 'Pickup Supply Depot',
          dest_name: 'Destination Medical Center',
          hub,
          pickup_coords: pickup,
          dest_coords: dest,
          hub_coords: hub.coords,
          route: { coordinates: fullFlightPath },
          leg1Count: leg1.length,
          leg2Count: leg2.length,
          totalDistanceKm: totalKm.toFixed(2),
          distance_to_go: deliveredInitially ? '0.00' : totalKm.toFixed(2),
          speed: deliveredInitially ? 0 : 48,
          eta_minutes: deliveredInitially ? 0 : Math.round((totalKm / 48) * 60),
          battery_level: deliveredInitially ? 74 : 96,
          current_coords: deliveredInitially ? dest : hub.coords,
          weather: m.weather,
          failure_reason: m.failure_reason,
          isTerminal: deliveredInitially || m.status === 'FAILED' || m.status === 'CANCELLED',
          _simIndex: deliveredInitially ? fullFlightPath.length - 1 : 0,
        });
      } catch (err) {
        // 2. If mission not found, check if it's a medical request
        try {
          const reqRes = await api.get(`/requests/${id}`);
          if (!isMounted) return;
          const req = reqRes.data;

          const pCoords = req.pickup ? [req.pickup.lng, req.pickup.lat] : [77.5946, 12.9716];
          const dCoords = req.destination ? [req.destination.lng, req.destination.lat] : [77.6245, 12.9352];
          const hub = getClosestHub(pCoords);

          if (req.mission_id) {
            // Request has a mission ID, fetch that mission
            const mRes = await api.get(`/missions/${req.mission_id}`);
            if (!isMounted) return;
            const m = mRes.data;
            const leg1 = await getRoadCorridorRoute(hub.coords, pCoords, 16);
            const leg2 = await getRoadCorridorRoute(pCoords, dCoords, 22);
            const fullFlightPath = [...leg1, ...leg2.slice(1)];
            const totalKm = 5.6;

            const deliveredInitially = isAlreadyDelivered || m.status === 'DELIVERED';

            if (!isMounted) return;
            setMission({
              id: m.mission_id || m.id,
              request_id: req.request_id || req.id,
              status: deliveredInitially ? 'DELIVERED' : m.status,
              drone_id: m.drone_id || 'DRN-001',
              pickup_name: 'Pickup Center',
              dest_name: 'Destination Hospital',
              hub,
              pickup_coords: pCoords,
              dest_coords: dCoords,
              hub_coords: hub.coords,
              route: { coordinates: fullFlightPath },
              leg1Count: leg1.length,
              leg2Count: leg2.length,
              totalDistanceKm: totalKm.toFixed(2),
              distance_to_go: deliveredInitially ? '0.00' : totalKm.toFixed(2),
              speed: deliveredInitially ? 0 : 48,
              eta_minutes: deliveredInitially ? 0 : 7,
              battery_level: deliveredInitially ? 74 : 96,
              current_coords: deliveredInitially ? dCoords : hub.coords,
              weather: m.weather,
              failure_reason: m.failure_reason,
              isTerminal: deliveredInitially || m.status === 'FAILED' || m.status === 'CANCELLED',
              _simIndex: deliveredInitially ? fullFlightPath.length - 1 : 0,
            });
            return;
          }

          // Request has NO mission and is PENDING (e.g. halted due to weather)
          const leg1 = await getRoadCorridorRoute(hub.coords, pCoords, 16);
          const leg2 = await getRoadCorridorRoute(pCoords, dCoords, 22);
          const previewPath = [...leg1, ...leg2.slice(1)];

          if (!isMounted) return;
          setMission({
            id: req.request_id || req.id,
            request_id: req.request_id || req.id,
            status: req.status || 'PENDING',
            drone_id: req.assigned_drone_id || 'Awaiting assignment',
            pickup_name: 'Pickup Center',
            dest_name: 'Destination Hospital',
            medical_type: req.medical_type,
            quantity: req.quantity,
            weight_kg: req.weight_kg,
            status_note: req.status_note,
            hub,
            hub_coords: hub.coords,
            pickup_coords: pCoords,
            dest_coords: dCoords,
            route: { coordinates: previewPath },
            distance_to_go: '0.00',
            speed: 0,
            eta_minutes: 0,
            battery_level: 100,
            weather: {
              condition: 'UNSAFE',
              note: req.status_note || 'Waiting: unsafe weather conditions at pickup.',
            },
            dispatch_summary: req.dispatch_summary?.text || null,
            isPendingHalted: true,
            _simIndex: 0,
          });
        } catch (reqErr) {
          // 3. Fallback for live simulated preview
          const pCoords = [77.5946, 12.9716];
          const dCoords = [77.6245, 12.9352];
          const hub = getClosestHub(pCoords);
          const leg1 = await getRoadCorridorRoute(hub.coords, pCoords, 16);
          const leg2 = await getRoadCorridorRoute(pCoords, dCoords, 22);
          const fullFlightPath = [...leg1, ...leg2.slice(1)];

          const deliveredInitially = isAlreadyDelivered;

          if (!isMounted) return;
          setMission({
            id: id || 'MIS-LIVE-FLIGHT',
            request_id: id || 'REQ-LIVE',
            status: deliveredInitially ? 'DELIVERED' : 'ASSIGNED',
            drone_id: 'DRN-001',
            pickup_name: 'Bangalore Medical Depot',
            dest_name: 'City Specialty Hospital',
            hub,
            hub_coords: hub.coords,
            pickup_coords: pCoords,
            dest_coords: dCoords,
            route: { coordinates: fullFlightPath },
            leg1Count: leg1.length,
            leg2Count: leg2.length,
            totalDistanceKm: '5.80',
            distance_to_go: deliveredInitially ? '0.00' : '5.80',
            speed: deliveredInitially ? 0 : 48,
            eta_minutes: deliveredInitially ? 0 : 8,
            battery_level: deliveredInitially ? 74 : 96,
            current_coords: deliveredInitially ? dCoords : hub.coords,
            isTerminal: deliveredInitially,
            _simIndex: deliveredInitially ? fullFlightPath.length - 1 : 0,
          });
        }
      }
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, [id, isAlreadyDelivered]);

  // ── Multi-Stage Simulation Timer ─────────────────────────────────────────────
  // Hub -> Pickup (TRAVELLING_TO_PICKUP) -> Handoff (PACKAGE_COLLECTED) -> Destination (IN_TRANSIT -> DELIVERED)
  useEffect(() => {
    if (!mission || mission.isPendingHalted || mission.isTerminal || mission.status === 'PENDING') return;

    const tickMs = simSpeed === 2 ? 700 : 1400; // Slower, realistic pace (~1.4s per step)

    const timer = setInterval(() => {
      setMission((prev) => {
        if (!prev || !prev.route || prev.isPendingHalted || prev.isTerminal) return prev;
        const coords = prev.route.coordinates;
        if (!coords || coords.length <= 1) return prev;

        const currentIdx = prev._simIndex || 0;
        const totalSteps = coords.length - 1;
        const nextIdx = Math.min(totalSteps, currentIdx + 1);

        if (nextIdx === currentIdx && prev.status === 'DELIVERED') return prev;

        const current_coords = coords[nextIdx];
        const remainingSteps = totalSteps - nextIdx;
        const totalKm = parseFloat(prev.totalDistanceKm || 5.8);
        const distance_to_go = ((remainingSteps / totalSteps) * totalKm).toFixed(2);

        // State Machine based on Leg 1 (Hub->Pickup) and Leg 2 (Pickup->Dest)
        let simStatus = prev.status;
        let speed = 48;
        const leg1Boundary = prev.leg1Count || 14;

        if (nextIdx === totalSteps) {
          simStatus = 'DELIVERED';
          speed = 0;
          // Synchronize delivery across Dashboard and Requests tables
          markDelivered(prev.id, prev.request_id);
        } else if (remainingSteps <= 2) {
          simStatus = 'APPROACHING_DESTINATION';
          speed = 32;
        } else if (nextIdx > leg1Boundary) {
          simStatus = 'IN_TRANSIT';
          speed = 48;
        } else if (nextIdx === leg1Boundary || nextIdx === leg1Boundary - 1) {
          // At pickup point loading medicine
          simStatus = 'PACKAGE_COLLECTED';
          speed = 0;
        } else {
          simStatus = 'TRAVELLING_TO_PICKUP';
          speed = 48;
        }

        const eta_minutes = simStatus === 'DELIVERED' ? 0 : Math.max(1, Math.round((parseFloat(distance_to_go) / 48) * 60));
        const battery_level = Math.max(70, Math.round(96 - (nextIdx / totalSteps) * 22));

        return {
          ...prev,
          _simIndex: nextIdx,
          current_coords,
          distance_to_go: simStatus === 'DELIVERED' ? '0.00' : distance_to_go,
          eta_minutes,
          battery_level,
          speed,
          status: simStatus,
          isTerminal: simStatus === 'DELIVERED',
        };
      });
    }, tickMs);

    return () => clearInterval(timer);
  }, [mission?.isPendingHalted, mission?.isTerminal, mission?.status, simSpeed, markDelivered]);

  // ── Render Map Markers & Route Lines ─────────────────────────────────────────
  useEffect(() => {
    const map = getMap();
    if (!map || !mission || errorState) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    const bounds = new LngLatBounds();
    const hubCoords = mission.hub_coords;
    const destCoords = mission.dest_coords;
    const pickupCoords = mission.pickup_coords;
    const droneCoords = mission.current_coords;

    // 1. Regional Division Base Hub Marker
    if (hubCoords) {
      bounds.extend(hubCoords);
      const el = document.createElement('div');
      el.className = 'map-marker-container';
      el.innerHTML = `<div class="map-pin map-pin--hub"></div><div class="map-pin-label" style="transform:translateY(20px)">Base · ${mission.hub?.shortName || 'Hub'}</div>`;
      const marker = new Marker({ element: el }).setLngLat(hubCoords).addTo(map);
      markersRef.current.push(marker);
    }

    // 2. Pickup Location Marker
    if (pickupCoords) {
      bounds.extend(pickupCoords);
      const el = document.createElement('div');
      el.className = 'map-marker-container';
      el.innerHTML = `<div class="map-pin map-pin--pickup"></div><div class="map-pin-label" style="transform:translateY(20px)">Pickup · ${mission.pickup_name || 'Hub'}</div>`;
      const marker = new Marker({ element: el }).setLngLat(pickupCoords).addTo(map);
      markersRef.current.push(marker);
    }

    // 3. Destination Medical Center Marker
    if (destCoords) {
      bounds.extend(destCoords);
      const el = document.createElement('div');
      el.className = 'map-marker-container';
      el.innerHTML = `<div class="map-pin map-pin--dest"></div><div class="map-pin-label" style="transform:translateY(-10px)">Drop · ${mission.dest_name || 'Hospital'}</div>`;
      const marker = new Marker({ element: el }).setLngLat(destCoords).addTo(map);
      markersRef.current.push(marker);
    }

    // 4. Live Flying Drone Marker (heading dynamically calculated)
    if (!mission.isPendingHalted && droneCoords) {
      bounds.extend(droneCoords);
      const el = document.createElement('div');
      el.className = 'drone-marker';
      el.style.width = '48px';
      el.style.height = '48px';

      const routeCoords = mission.route?.coordinates || [];
      const currentIdx = mission._simIndex || 0;
      const targetPoint = routeCoords[Math.min(routeCoords.length - 1, currentIdx + 1)] || destCoords;
      const heading = targetPoint
        ? (Math.atan2(targetPoint[0] - droneCoords[0], targetPoint[1] - droneCoords[1]) * 180) / Math.PI
        : 0;

      el.innerHTML = `<svg viewBox="-30 -30 60 60" style="width:100%; height:100%; overflow:visible">
        <circle class="ring" r="20" style="fill:var(--accent-color)"/>
        <circle r="23" fill="#FFFFFF" style="stroke:var(--accent-color)" stroke-width="3"/>
        <g style="transform:rotate(${heading}deg)">
          <path d="M-11-11L11 11M-11 11L11-11" stroke="#0B1F33" stroke-width="2.5" stroke-linecap="round"/>
          <g fill="#0B1F33"><circle cx="-11" cy="-11" r="4"/><circle cx="11" cy="-11" r="4"/><circle cx="-11" cy="11" r="4"/><circle cx="11" cy="11" r="4"/></g>
          <polygon points="0,-16 -6,-6 6,-6" fill="var(--accent-color)"/>
          <circle r="4" style="fill:var(--accent-color)"/>
        </g>
      </svg>`;

      const marker = new Marker({ element: el }).setLngLat(droneCoords).addTo(map);
      markersRef.current.push(marker);
    }

    try {
      if (bounds.isEmpty() === false) {
        map.fitBounds(bounds, { padding: 130, maxZoom: 14, duration: 800 });
      }
    } catch (e) {}

    const updateRoutes = () => {
      const routeCoords = mission.route?.coordinates || [];
      let droneIdx = Math.max(0, mission._simIndex || 0);

      // Swiggy/Zomato style: render full planned road delivery track
      const plannedSrc = map.getSource('planned-route');
      if (plannedSrc && routeCoords.length > 1) {
        plannedSrc.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: routeCoords } });
      }

      if (mission.isPendingHalted) {
        const dashedSrc = map.getSource('active-routes-dashed');
        if (dashedSrc && routeCoords.length > 1) {
          dashedSrc.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: routeCoords } });
        }
        return;
      }

      const solidRoute = routeCoords.slice(0, droneIdx + 1);
      const dashedRoute = routeCoords.slice(droneIdx);

      if (solidRoute.length === 1) solidRoute.push([solidRoute[0][0] + 0.00001, solidRoute[0][1] + 0.00001]);
      if (dashedRoute.length === 1) dashedRoute.push([dashedRoute[0][0] + 0.00001, dashedRoute[0][1] + 0.00001]);

      const solidSrc = map.getSource('active-routes-solid');
      if (solidSrc && solidRoute.length > 1) {
        solidSrc.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: solidRoute } });
      }

      const dashedSrc = map.getSource('active-routes-dashed');
      if (dashedSrc && dashedRoute.length > 1) {
        dashedSrc.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: dashedRoute } });
      }
    };

    if (map.isStyleLoaded()) {
      updateRoutes();
    } else {
      map.once('style.load', updateRoutes);
    }

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      const plannedSrc = map.getSource('planned-route');
      if (plannedSrc) plannedSrc.setData({ type: 'FeatureCollection', features: [] });
      const solidSrc = map.getSource('active-routes-solid');
      if (solidSrc) solidSrc.setData({ type: 'FeatureCollection', features: [] });
      const dashedSrc = map.getSource('active-routes-dashed');
      if (dashedSrc) dashedSrc.setData({ type: 'FeatureCollection', features: [] });
    };
  }, [mission, errorState]);

  if (!mission && !errorState) return <WorldMap />;

  const isFailed = mission?.status === 'FAILED';
  const isCancelled = mission?.status === 'CANCELLED';
  const isPendingHalted = mission?.isPendingHalted || mission?.status === 'PENDING';
  const isDelivered = mission?.status === 'DELIVERED';

  const totalDistance = parseFloat(mission?.totalDistanceKm || 5.8);
  const remDistance = parseFloat(mission?.distance_to_go || 0);

  let progressPercent = 0;
  if (mission) {
    if (isDelivered) progressPercent = 100;
    else progressPercent = Math.max(0, Math.min(100, (1 - remDistance / totalDistance) * 100));
  }

  const etaDisplay = isDelivered ? '0' : mission?.eta_minutes != null ? mission.eta_minutes : '--';

  const STATUS_ORDER = {
    ASSIGNED: 0,
    TRAVELLING_TO_PICKUP: 1,
    PACKAGE_COLLECTED: 2,
    IN_TRANSIT: 3,
    APPROACHING_DESTINATION: 4,
    DELIVERED: 5,
  };

  const getStepState = (stepIndex) => {
    const currStatus = mission?.status || 'ASSIGNED';
    if (currStatus === 'DELIVERED') return 'done';
    const currIndex = STATUS_ORDER[currStatus] ?? 0;
    if (stepIndex < currIndex) return 'done';
    if (stepIndex === currIndex) return 'current';
    return 'upcoming';
  };

  const stepStyles = {
    done: {
      icon: '#0E8F7E',
      border: 'none',
      svg: (
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12">
          <path d="M2.5 6.2L5 8.5L9.5 3.5" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ),
    },
    current: { icon: '#fff', border: '5px solid var(--accent-color)', svg: null },
    upcoming: { icon: 'transparent', border: '2px solid #C3CED4', svg: null },
  };

  const renderStep = (label, subtext, status, isLast) => {
    const st = stepStyles[status];
    return (
      <li style={{ display: 'flex', gap: '14px', minHeight: isLast ? 'auto' : '44px' }} data-label={label} data-status={status}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <span
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '22px',
              height: '22px',
              boxSizing: 'border-box',
              borderRadius: '50%',
              background: st.icon,
              border: st.border,
            }}
          >
            {st.svg}
          </span>
          {!isLast && <span style={{ flex: 1, width: '2px', background: status === 'done' ? '#0E8F7E' : '#D5DEE2' }}></span>}
        </div>
        <div style={{ paddingBottom: isLast ? 0 : '10px' }}>
          <div style={{ fontSize: '14px', fontWeight: status === 'current' ? 800 : 600, color: status === 'upcoming' ? '#5F7080' : 'var(--ink)' }}>
            {label}
            {status === 'current' && (
              <span style={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: '10px', color: 'var(--accent-color)', marginLeft: '8px', fontWeight: 700 }}>
                ACTIVE
              </span>
            )}
          </div>
          {subtext && <div style={{ fontSize: '11px', color: '#6A7D8E', marginTop: '2px' }}>{subtext}</div>}
        </div>
      </li>
    );
  };

  return (
    <WorldMap>
      {/* Top Left Navigation Bar */}
      <div
        style={{
          position: 'fixed',
          top: '24px',
          left: '24px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          height: '48px',
          padding: '0 18px 0 14px',
          background: '#fff',
          borderRadius: '24px',
          boxShadow: '0 8px 24px rgba(11,31,51,.12)',
          zIndex: 100,
        }}
      >
        <Link to="/" style={{ color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '8px' }} title="Return to Dashboard">
          <ArrowLeft size={18} />
          <span style={{ fontFamily: '"Bricolage Grotesque", sans-serif', fontWeight: 800, fontSize: '18px', letterSpacing: '-.02em' }}>
            AeroMedical
          </span>
        </Link>
        <span style={{ color: '#D5DEE2' }}>|</span>
        <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--teal)' }}>
          {mission?.hub?.division ? `Bangalore ${mission.hub.division} Division` : 'Bangalore Fleet'}
        </span>
      </div>

      {/* Top Right HUD Controls */}
      <div
        className="hud"
        style={{
          position: 'fixed',
          top: '24px',
          right: '24px',
          display: 'flex',
          gap: '10px',
          alignItems: 'center',
          zIndex: 100,
        }}
      >
        {/* Simulation Speed Control */}
        {!isPendingHalted && !isDelivered && (
          <div style={{ display: 'flex', background: '#fff', padding: '4px', borderRadius: '24px', boxShadow: '0 8px 24px rgba(11,31,51,.10)' }}>
            <button
              type="button"
              onClick={() => setSimSpeed(1)}
              style={{
                border: 'none',
                background: simSpeed === 1 ? '#0B1F33' : 'transparent',
                color: simSpeed === 1 ? '#fff' : '#5F7080',
                borderRadius: '16px',
                padding: '4px 12px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              1x Normal
            </button>
            <button
              type="button"
              onClick={() => setSimSpeed(2)}
              style={{
                border: 'none',
                background: simSpeed === 2 ? '#0B1F33' : 'transparent',
                color: simSpeed === 2 ? '#fff' : '#5F7080',
                borderRadius: '16px',
                padding: '4px 12px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              2x Fast
            </button>
          </div>
        )}

        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            height: '48px',
            padding: '0 16px 0 8px',
            background: '#fff',
            borderRadius: '24px',
            fontWeight: 600,
            fontSize: '14px',
            boxShadow: '0 8px 24px rgba(11,31,51,.12)',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px', borderRadius: '50%', background: '#0B1F33', color: '#fff', fontSize: '12px', fontWeight: 800 }}>
            MC
          </span>
          {mission?.dest_name || 'Medical Center'}
        </span>
      </div>

      {/* Main Mission Control Sheet */}
      <section
        className="sheet"
        aria-label="Mission Details"
        style={{
          position: 'fixed',
          top: '92px',
          left: '24px',
          width: '400px',
          boxSizing: 'border-box',
          padding: '24px',
          background: '#fff',
          borderRadius: '28px',
          boxShadow: '0 24px 60px rgba(11,31,51,.16), 0 2px 6px rgba(11,31,51,.06)',
          display: 'flex',
          flexDirection: 'column',
          gap: '18px',
          zIndex: 100,
          maxHeight: 'calc(100vh - 120px)',
          overflowY: 'auto',
        }}
      >
        {errorState ? (
          <div style={{ color: 'var(--red)', fontWeight: 600 }}>{errorState}</div>
        ) : isPendingHalted ? (
          /* Halted due to weather safety */
          <div id="pending-halted-state" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#D93A1F', fontWeight: 800, fontSize: '12px', letterSpacing: '.08em' }}>
              <ShieldAlert size={16} />
              <span>DISPATCH HALTED · SAFETY GATE ACTIVE</span>
            </div>

            <div>
              <h1 style={{ margin: 0, fontFamily: '"Bricolage Grotesque", sans-serif', fontWeight: 800, fontSize: '28px', color: 'var(--ink)' }}>
                Waiting for Safe Weather
              </h1>
              <p style={{ marginTop: '6px', color: '#4A5B6C', fontSize: '14px', lineHeight: 1.45 }}>
                {mission.medical_type} delivery of {mission.quantity} units ({mission.weight_kg} kg) held at pickup location.
              </p>
            </div>

            <div
              style={{
                background: '#FDEDEA',
                borderLeft: '4px solid #D93A1F',
                padding: '12px 14px',
                borderRadius: '10px',
                fontSize: '13px',
                lineHeight: 1.45,
                color: '#942310',
                fontWeight: 500,
              }}
            >
              <div style={{ fontWeight: 800, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: '4px' }}>
                Weather Safety Check
              </div>
              <div>{mission.status_note || 'Waiting: unsafe weather conditions at pickup.'}</div>
              {mission.dispatch_summary && (
                <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(217, 58, 31, 0.2)', fontSize: '12px', color: '#7A1C0B', fontStyle: 'italic' }}>
                  {mission.dispatch_summary}
                </div>
              )}
            </div>

            <div style={{ background: '#F8FAFC', borderRadius: '12px', padding: '14px', border: '1px solid rgba(11, 31, 51, 0.08)' }}>
              <div style={{ fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                Delivery Request Information
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Request ID:</span>
                <span className="mono" style={{ fontWeight: 700 }}>{mission.id}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Status:</span>
                <span className="status-pill status-pill--pending">PENDING</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Assigned Drone:</span>
                <span className="mono" style={{ color: 'var(--text-tertiary)' }}>Awaiting clear sky</span>
              </div>
            </div>
          </div>
        ) : (
          /* Active Flight / Swiggy-Zomato Delivery Simulation */
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span
                id="mission-label"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontWeight: 800,
                  fontSize: '12px',
                  letterSpacing: '.12em',
                  color: isDelivered ? '#0E8F7E' : '#4A5B6C',
                }}
              >
                {!isDelivered && !isFailed && !isCancelled && (
                  <span className="beat" style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-color)' }}></span>
                )}
                {isDelivered ? 'DELIVERY COMPLETE' : isFailed ? 'MISSION FAILED' : isCancelled ? 'MISSION CANCELLED' : 'LIVE MISSION IN FLIGHT'}
              </span>
              <span className="mono" style={{ fontSize: '12px', color: '#6A7D8E', fontWeight: 600 }}>
                {mission.drone_id} · {mission.hub?.division} Div
              </span>
            </div>

            {/* Delivered Celebration Card */}
            {isDelivered ? (
              <div
                id="delivered-celebration-card"
                style={{
                  background: '#EDF9F5',
                  border: '1.5px solid #0E8F7E',
                  borderRadius: '16px',
                  padding: '18px',
                  textAlign: 'center',
                }}
              >
                <div style={{ display: 'inline-flex', padding: '10px', borderRadius: '50%', background: '#0E8F7E', color: '#fff', marginBottom: '10px' }}>
                  <CheckCircle2 size={32} />
                </div>
                <h2 style={{ margin: 0, fontFamily: '"Bricolage Grotesque", sans-serif', fontSize: '22px', fontWeight: 800, color: '#09574D' }}>
                  Package Safely Delivered!
                </h2>
                <p style={{ margin: '6px 0 16px', fontSize: '13px', color: '#3E6660', lineHeight: 1.4 }}>
                  The medical supplies have been handed over to <strong>{mission.dest_name}</strong>. Flight telemetry and verification hashes have been synced.
                </p>
                <Link
                  to="/"
                  className="app-btn app-btn--primary"
                  id="return-dashboard-btn"
                  style={{ width: '100%', justifyContent: 'center', padding: '12px' }}
                >
                  <ArrowLeft size={16} />
                  <span>Return to Hospital Dashboard</span>
                </Link>
              </div>
            ) : (
              <div>
                <h1 style={{ margin: 0, fontFamily: '"Bricolage Grotesque", sans-serif', fontWeight: 800, lineHeight: '.95', display: 'flex', alignItems: 'baseline', gap: '10px' }}>
                  <span id="countdown-val" style={{ fontSize: '76px', letterSpacing: '-.045em' }}>
                    {etaDisplay}
                  </span>
                  <span style={{ fontSize: '22px', fontWeight: 500, letterSpacing: '-.01em' }}>min away</span>
                </h1>
                <p style={{ margin: '8px 0 0', fontSize: '14px', lineHeight: '1.45', color: '#4A5B6C' }}>
                  {mission.status === 'TRAVELLING_TO_PICKUP' ? (
                    <>
                      Drone dispatched from <strong>{mission.hub?.shortName}</strong> heading to pickup depot.
                    </>
                  ) : mission.status === 'PACKAGE_COLLECTED' ? (
                    <>
                      Drone landed at <strong>{mission.pickup_name}</strong>. Loading medical package.
                    </>
                  ) : (
                    <>
                      Drone {mission.drone_id} en route to <strong>{mission.dest_name}</strong>.{' '}
                      <span id="dist-val">{mission.distance_to_go}</span> km to go.
                    </>
                  )}
                </p>
              </div>
            )}

            {/* Drone Battery (Decreases proportionally as battery % drops) */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', fontWeight: 800, marginBottom: '8px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background:
                        mission.battery_level > 50
                          ? '#0E8F7E'
                          : mission.battery_level > 20
                          ? '#E59B00'
                          : '#D93A1F',
                    }}
                  ></span>
                  Drone Battery
                </span>
                <span id="battery-val" className="mono" style={{ fontWeight: 600 }}>
                  {mission.battery_level}%
                </span>
              </div>
              <div style={{ height: '8px', borderRadius: '4px', background: '#E3EAED', overflow: 'hidden' }}>
                <div
                  id="battery-bar"
                  style={{
                    width: `${Math.min(100, Math.max(0, mission.battery_level))}%`,
                    height: '8px',
                    borderRadius: '4px',
                    background:
                      mission.battery_level > 50
                        ? '#0E8F7E'
                        : mission.battery_level > 20
                        ? '#E59B00'
                        : '#D93A1F',
                    transition: 'width 0.8s ease, background 0.5s ease',
                  }}
                ></div>
              </div>
            </div>

            {/* Multi-phase Swiggy/Zomato style Delivery Timeline */}
            <ol id="timeline-list" style={{ listStyle: 'none', margin: '6px 0 0', padding: 0 }}>
              {renderStep(
                `Dispatched from ${mission.hub?.shortName || 'Base Hub'}`,
                `Departed ${mission.hub?.division || 'Bangalore'} regional base station`,
                getStepState(0),
                false
              )}
              {renderStep(
                'Flying to Pickup Location',
                `En route to ${mission.pickup_name}`,
                getStepState(1),
                false
              )}
              {renderStep(
                'Package Loaded at Pickup',
                'Medical cargo secured in temperature-regulated drone bay',
                getStepState(2),
                false
              )}
              {renderStep(
                'In Transit to Destination',
                `Navigating Bangalore flight corridor to ${mission.dest_name}`,
                getStepState(3),
                false
              )}
              {renderStep(
                'Approaching Destination',
                'Final descent & safety clearance',
                getStepState(4),
                false
              )}
              {renderStep(
                'Delivered to Hospital',
                'Package dropped safely at hospital landing bay',
                getStepState(5),
                true
              )}
            </ol>
          </>
        )}
      </section>

      {/* Bottom Telemetry HUD */}
      <div
        className="hud"
        style={{
          position: 'fixed',
          right: '24px',
          bottom: '28px',
          display: 'flex',
          gap: '24px',
          alignItems: 'center',
          padding: '14px 26px',
          background: '#fff',
          borderRadius: '28px',
          boxShadow: '0 8px 24px rgba(11,31,51,.12)',
          zIndex: 100,
        }}
      >
        <div>
          <div style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '.1em', color: '#4A5B6C' }}>REGIONAL HUB</div>
          <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: '16px' }}>
            {mission?.hub?.division ? `BLR-${mission.hub.division.toUpperCase()}` : 'BLR-CENTRAL'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '.1em', color: '#4A5B6C' }}>DISTANCE</div>
          <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: '20px' }}>
            {mission?.isPendingHalted ? '0.00 km' : `${mission?.distance_to_go || '--'} km`}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '.1em', color: '#4A5B6C' }}>SPEED</div>
          <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 500, fontSize: '20px' }}>
            {mission?.isPendingHalted ? '0 km/h' : `${mission?.speed || 0} km/h`}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '.1em', color: '#4A5B6C' }}>STATUS</div>
          <div style={{ fontFamily: '"IBM Plex Mono", monospace', fontWeight: 600, fontSize: '16px', color: isDelivered ? '#0E8F7E' : 'var(--ink)' }}>
            {mission?.isPendingHalted ? 'WEATHER HALTED' : mission?.status?.replace(/_/g, ' ') || '--'}
          </div>
        </div>
      </div>
    </WorldMap>
  );
}
