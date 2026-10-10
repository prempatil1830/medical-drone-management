/**
 * WorldMap.jsx — Persistent MapLibre map with Light Theme.
 */
import React, { useRef, useEffect, useCallback } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const BLR_CENTER = [77.5946, 12.9716];
const DEFAULT_ZOOM = 12.5;

let sharedMap = null;
let sharedContainer = null;

export function getMap() {
  return sharedMap;
}

export default function WorldMap({ children }) {
  const containerRef = useRef(null);

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
      } catch (e) {
        // silently skip
      }
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    if (!sharedContainer) {
      sharedContainer = document.createElement('div');
      sharedContainer.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:0;';
    }
    containerRef.current.appendChild(sharedContainer);

    if (!sharedMap) {
      const map = new maplibregl.Map({
        container: sharedContainer,
        style: 'https://tiles.openfreemap.org/styles/positron',
        center: BLR_CENTER,
        zoom: DEFAULT_ZOOM,
        attributionControl: true,
      });
      
      map.on('style.load', () => {
        applyPalette(map);
      });
      sharedMap = map;
    } else {
      if (sharedMap.isStyleLoaded()) {
        applyPalette(sharedMap);
      }
    }
  }, [applyPalette]);

  return (
    <div ref={containerRef} style={{ position: 'fixed', inset: 0, width: '100vw', height: '100vh', zIndex: 0 }}>
      <div style={{ position: 'relative', zIndex: 2 }}>{children}</div>
    </div>
  );
}
