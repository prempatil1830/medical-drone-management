/**
 * WorldMap.jsx — Persistent MapLibre map with Light Theme.
 * Follows MapLibre CSP bundler guidance for Vite.
 */
import React, { useRef, useEffect, useState } from 'react';
import maplibregl from 'maplibre-gl/dist/maplibre-gl-csp';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-csp-worker?url';
import 'maplibre-gl/dist/maplibre-gl.css';

maplibregl.setWorkerUrl(workerUrl);

const BLR_CENTER = [77.5946, 12.9716];
const DEFAULT_ZOOM = 12.5;

let currentMap = null;

export function getMap() {
  return currentMap;
}

export { maplibregl };

function restyleMap(map) {
  try {
    const style = map.getStyle();
    if (!style || !style.layers) return;
    const skippedLayers = [];

    for (const layer of style.layers) {
      const layerId = layer.id;
      if (!map.getLayer(layerId)) {
        skippedLayers.push(layerId);
        continue;
      }

      try {
        let changed = false;

        // Water
        if (layerId.includes('water') && layer.type === 'fill') {
          map.setPaintProperty(layerId, 'fill-color', '#BBDDEB');
          changed = true;
        }

        // Landcover / Parks
        const isGreen =
          layerId.includes('park') ||
          layerId.includes('grass') ||
          layerId.includes('wood') ||
          layerId.includes('forest') ||
          layerId.includes('recreation') ||
          layerId.includes('garden') ||
          layerId.includes('pitch') ||
          layerId.includes('cemetery') ||
          layerId.includes('nature') ||
          layerId.includes('protected');

        if (isGreen && layer.type === 'fill') {
          map.setPaintProperty(layerId, 'fill-color', '#CFE6D2');
          map.setPaintProperty(layerId, 'fill-opacity', 1.0);
          changed = true;
        } else if (
          (layerId.includes('landcover') || layerId.includes('landuse')) &&
          layer.type === 'fill'
        ) {
          map.setPaintProperty(layerId, 'fill-color', '#E6ECEE');
          changed = true;
        } else if (layerId === 'background') {
          map.setPaintProperty(layerId, 'background-color', '#E6ECEE');
          changed = true;
        }

        // Roads
        if (layerId.includes('highway') || layerId.includes('road')) {
          if (layer.type === 'line') {
            if (layerId.includes('casing') || layerId.includes('outline')) {
              map.setPaintProperty(layerId, 'line-color', '#D3DCE0');
            } else {
              map.setPaintProperty(layerId, 'line-color', '#FFFFFF');
            }
            changed = true;
          }
        }

        // Buildings
        if (layerId.includes('building') && layer.type === 'fill') {
          map.setLayerZoomRange(layerId, 16, 22);
          map.setPaintProperty(layerId, 'fill-color', '#D0D6D9');
          changed = true;
        }

        // Hide POIs and minor labels
        if (
          layerId.includes('poi') ||
          layerId.includes('minor') ||
          layerId.match(/^label_(other|village|town|state|country)/)
        ) {
          map.setLayoutProperty(layerId, 'visibility', 'none');
          changed = true;
        }

        // Mute text colors
        if (layer.type === 'symbol' && layer.layout && layer.layout['text-field']) {
          if (
            !layerId.includes('poi') &&
            !layerId.includes('minor') &&
            !layerId.match(/^label_(other|village|town|state|country)/)
          ) {
            map.setPaintProperty(layerId, 'text-color', '#4A5B6C');
            map.setPaintProperty(layerId, 'text-halo-color', '#FFFFFF');
            map.setPaintProperty(layerId, 'text-halo-width', 1.5);
            changed = true;
          }
        }

        if (!changed) {
          skippedLayers.push(layerId);
        }
      } catch (err) {
        console.warn(`[WorldMap] Error styling layer ${layerId}:`, err);
        skippedLayers.push(layerId);
      }
    }

    if (skippedLayers.length > 0) {
      console.log(`[WorldMap] Restyle skipped ${skippedLayers.length} layers:`, skippedLayers);
    }
  } catch (outerErr) {
    console.error('[WorldMap] Outer error in restyleMap:', outerErr);
  }
}

export function initRouteLayers(map) {
  try {
    // 1. Full planned road route source (like Swiggy/Zomato planned road line)
    if (!map.getSource('planned-route')) {
      map.addSource('planned-route', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
    }

    if (!map.getSource('active-routes-solid')) {
      map.addSource('active-routes-solid', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
    }

    if (!map.getSource('active-routes-dashed')) {
      map.addSource('active-routes-dashed', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
    }

    let firstSymbolId;
    const layers = map.getStyle().layers || [];
    for (const l of layers) {
      if (l.type === 'symbol') {
        firstSymbolId = l.id;
        break;
      }
    }

    // Full planned delivery route outer casing
    if (!map.getLayer('planned-route-casing')) {
      map.addLayer(
        {
          id: 'planned-route-casing',
          type: 'line',
          source: 'planned-route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#FFFFFF', 'line-width': 10 },
        },
        firstSymbolId
      );
    }

    // Full planned delivery route track (Swiggy/Zomato style planned road corridor)
    if (!map.getLayer('planned-route-track')) {
      map.addLayer(
        {
          id: 'planned-route-track',
          type: 'line',
          source: 'planned-route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#94A3B8', 'line-width': 5, 'line-opacity': 0.75 },
        },
        firstSymbolId
      );
    }

    // Traveled road route casing
    if (!map.getLayer('active-routes-solid-casing')) {
      map.addLayer(
        {
          id: 'active-routes-solid-casing',
          type: 'line',
          source: 'active-routes-solid',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#FFFFFF', 'line-width': 9 },
        },
        firstSymbolId
      );
    }

    // Traveled road route (Solid Emerald Green #0E8F7E behind drone)
    if (!map.getLayer('active-routes-solid')) {
      map.addLayer(
        {
          id: 'active-routes-solid',
          type: 'line',
          source: 'active-routes-solid',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#0E8F7E', 'line-width': 6 },
        },
        firstSymbolId
      );
    }

    // Upcoming road route (Vibrant Delivery Red #D93A1F ahead of drone with clear road dash)
    if (!map.getLayer('active-routes-dashed')) {
      map.addLayer(
        {
          id: 'active-routes-dashed',
          type: 'line',
          source: 'active-routes-dashed',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#D93A1F', 'line-width': 6, 'line-dasharray': [2, 2] },
        },
        firstSymbolId
      );
    }
  } catch (err) {
    console.error('[WorldMap] Error initializing route layers:', err);
  }
}

export default function WorldMap({ children }) {
  const containerRef = useRef(null);
  const [mapError, setMapError] = useState(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    let map = null;
    let ro = null;

    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: 'https://tiles.openfreemap.org/styles/positron',
        center: BLR_CENTER,
        zoom: DEFAULT_ZOOM,
        attributionControl: true,
        preserveDrawingBuffer: true,
      });

      currentMap = map;
      if (typeof window !== 'undefined') {
        window.__map = map;
      }

      map.on('error', (e) => {
        const msg = e.error?.message || e.message || (typeof e === 'string' ? e : 'Map error occurred');
        console.error('[WorldMap error]', e);
        setMapError(msg);
      });

      map.once('style.load', () => {
        restyleMap(map);
        initRouteLayers(map);
      });

      map.once('idle', () => {
        setIsReady(true);
        if (containerRef.current) {
          containerRef.current.setAttribute('data-map-ready', 'true');
        }
      });

      // Explicit non-zero resize after mount
      map.resize();
      requestAnimationFrame(() => {
        if (map) map.resize();
      });

      // ResizeObserver
      ro = new ResizeObserver(() => {
        if (map) map.resize();
      });
      ro.observe(containerRef.current);
    } catch (err) {
      console.error('[WorldMap init error]', err);
      setMapError(err.message || 'Failed to initialize MapLibre GL');
    }

    return () => {
      if (ro) {
        ro.disconnect();
      }
      if (typeof window !== 'undefined' && window.__map === map) {
        window.__map = null;
      }
      if (currentMap === map) {
        currentMap = null;
      }
      if (map) {
        map.remove();
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="world-map-container"
      data-map-ready={isReady ? 'true' : 'false'}
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 0,
      }}
    >
      {/* Loading overlay until first idle */}
      {!isReady && !mapError && (
        <div
          id="map-loading-indicator"
          style={{
            position: 'absolute',
            top: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 9999,
            background: 'rgba(255, 255, 255, 0.95)',
            border: '1px solid #D5DEE2',
            padding: '8px 18px',
            borderRadius: '20px',
            boxShadow: '0 8px 24px rgba(11, 31, 51, 0.12)',
            fontFamily: "'Manrope', sans-serif",
            fontWeight: 700,
            fontSize: '13px',
            color: '#0B1F33',
            pointerEvents: 'none',
          }}
        >
          Loading map...
        </div>
      )}

      {/* Visible error panel if map error occurs */}
      {mapError && (
        <div
          id="map-error-panel"
          style={{
            position: 'absolute',
            top: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 9999,
            background: '#FDEDEA',
            border: '2px solid #D93A1F',
            padding: '12px 24px',
            borderRadius: '16px',
            boxShadow: '0 12px 32px rgba(217, 58, 31, 0.2)',
            fontFamily: "'Manrope', sans-serif",
            color: '#D93A1F',
            fontWeight: 700,
            fontSize: '14px',
            maxWidth: '90%',
          }}
        >
          Map Error: {mapError}
        </div>
      )}

      {/* Children content */}
      <div style={{ position: 'relative', zIndex: 2 }}>{children}</div>
    </div>
  );
}
