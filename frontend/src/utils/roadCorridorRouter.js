/**
 * roadCorridorRouter.js
 * 
 * Intelligent Road Air Corridor routing for Bangalore Medical Drone Flights.
 * Ensures drones fly strictly above major road networks, avenues, ring roads,
 * and arterial corridors, avoiding high-density building complexes.
 * 
 * Strategy:
 * 1. Primary: Fetches real-world road geometries from OpenStreetMap routing service (OSRM).
 * 2. Offline Fallback: Built-in graph of Bangalore's designated arterial road corridors
 *    (Hosur Rd, Outer Ring Rd, Old Airport Rd, Bellary Rd, Sarjapur Rd, 80ft/100ft Roads).
 * 3. Polyline resampling: Generates uniform, smooth flight waypoints for realistic simulation.
 */

function haversineDist(c1, c2) {
  const R = 6371; // km
  const dLat = ((c2[1] - c1[1]) * Math.PI) / 180;
  const dLng = ((c2[0] - c1[0]) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((c1[1] * Math.PI) / 180) *
      Math.cos((c2[1] * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── Bangalore Road Corridor Network (Offline Fallback) ────────────────────────
// Carefully mapped coordinates along actual Bangalore roadways and junctions:
const ROAD_NODES = {
  // Central Arterials
  MG_ROAD: [77.5946, 12.9716],
  BRIGADE_ROAD: [77.6045, 12.9730],
  RICHMOND_CIRCLE: [77.5990, 12.9620],
  LANGFORD_TOWN_RD: [77.6030, 12.9530],
  ADUGODI_HOSUR: [77.6105, 12.9420],
  DAIRY_CIRCLE: [77.5990, 12.9390],

  // Hosur Road Corridor (Central to South Electronic City)
  FORUM_HOSUR: [77.6150, 12.9345],
  MADIWALA_HOSUR: [77.6200, 12.9250],
  SILK_BOARD: [77.6250, 12.9170],
  BOMMANAHALLI_HOSUR: [77.6330, 12.9050],
  KUDLU_GATE_HOSUR: [77.6430, 12.8850],
  ELECTRONIC_CITY_TOLL: [77.6650, 12.8480],
  SOUTH_BASE_HUB: [77.6389, 12.8452],

  // Koramangala 80ft & 100ft Road Corridors
  KORAMANGALA_80FT_W: [77.6210, 12.9370],
  KORAMANGALA_80FT_MID: [77.6260, 12.9355],
  SONY_WORLD_JUNCTION: [77.6340, 12.9350],
  KORAMANGALA_100FT_MID: [77.6380, 12.9335],
  KORAMANGALA_STBED: [77.6440, 12.9300],

  // Inner Ring Road (Koramangala to Domlur / Old Airport Rd)
  EJIPURA_INNER_RING: [77.6370, 12.9420],
  DOMLUR_INNER_RING: [77.6400, 12.9520],
  DOMLUR_FLYOVER: [77.6380, 12.9620],

  // Old Airport Road & East Corridor (Central to Whitefield)
  TRINITY_CIRCLE: [77.6200, 12.9680],
  MANIPAL_HOSPITAL_AIRPORT_RD: [77.6580, 12.9590],
  HAL_AIRPORT_RD: [77.6750, 12.9560],
  MARATHAHALLI_BRIDGE: [77.6950, 12.9520],
  KUNDALAHALLI_GATE: [77.7200, 12.9580],
  WHITEFIELD_HOPE_FARM: [77.7499, 12.9698],

  // Outer Ring Road (ORR) Corridor (Silk Board to Hebbal)
  HSR_ORR: [77.6400, 12.9130],
  AGARA_JUNCTION: [77.6480, 12.9240],
  BELLANDUR_ORR: [77.6710, 12.9290],
  ECOSPACE_ORR: [77.6820, 12.9360],
  MAHADEVAPURA_ORR: [77.7010, 12.9850],
  KR_PURAM_ORR: [77.7010, 12.9920],
  KASTURI_NAGAR_ORR: [77.6680, 13.0150],
  NAGAWARA_ORR: [77.6350, 13.0420],
  HEBBAL_FLYOVER: [77.5920, 13.0350],

  // Bellary Road Corridor (Central to North Yelahanka)
  CUNNINGHAM_RD: [77.5900, 12.9850],
  MEKHRI_CIRCLE: [77.5840, 13.0110],
  KODIGEHALLI_GATE: [77.5980, 13.0550],
  NORTH_BASE_HUB: [77.5963, 13.0645],

  // West Corridor (Rajajinagar & West Chord Road)
  MAJESTIC_STATION: [77.5700, 12.9770],
  OKALIPURAM: [77.5550, 12.9820],
  WEST_BASE_HUB: [77.5450, 12.9880],
  NAVRANG_CIRCLE: [77.5500, 13.0120],
  YESHWANTHPUR_JUNCTION: [77.5550, 13.0280],

  // Sarjapur Road Corridor
  SARJAPUR_WATER_TANK: [77.6320, 12.9260],
  JAKKASANDRA_SARJAPUR: [77.6450, 12.9240],
  BELLANDUR_GATE_SARJAPUR: [77.6850, 12.9180],

  // Bannerghatta Road Corridor
  JAYADEVA_FLYOVER: [77.5980, 12.9180],
  AREKERE_BANNERGHATTA: [77.5970, 12.8750],
};

// Graph adjacency (bi-directional road segments)
const ROAD_EDGES = [
  // Hosur Road Spine
  ['MG_ROAD', 'BRIGADE_ROAD'],
  ['BRIGADE_ROAD', 'RICHMOND_CIRCLE'],
  ['MG_ROAD', 'RICHMOND_CIRCLE'],
  ['RICHMOND_CIRCLE', 'LANGFORD_TOWN_RD'],
  ['LANGFORD_TOWN_RD', 'ADUGODI_HOSUR'],
  ['ADUGODI_HOSUR', 'FORUM_HOSUR'],
  ['FORUM_HOSUR', 'MADIWALA_HOSUR'],
  ['MADIWALA_HOSUR', 'SILK_BOARD'],
  ['SILK_BOARD', 'BOMMANAHALLI_HOSUR'],
  ['BOMMANAHALLI_HOSUR', 'KUDLU_GATE_HOSUR'],
  ['KUDLU_GATE_HOSUR', 'ELECTRONIC_CITY_TOLL'],
  ['ELECTRONIC_CITY_TOLL', 'SOUTH_BASE_HUB'],

  // Koramangala 80ft & 100ft Roads
  ['FORUM_HOSUR', 'KORAMANGALA_80FT_W'],
  ['KORAMANGALA_80FT_W', 'KORAMANGALA_80FT_MID'],
  ['KORAMANGALA_80FT_MID', 'SONY_WORLD_JUNCTION'],
  ['SONY_WORLD_JUNCTION', 'KORAMANGALA_100FT_MID'],
  ['KORAMANGALA_100FT_MID', 'KORAMANGALA_STBED'],
  ['KORAMANGALA_STBED', 'HSR_ORR'],

  // Inner Ring Road
  ['SONY_WORLD_JUNCTION', 'EJIPURA_INNER_RING'],
  ['EJIPURA_INNER_RING', 'DOMLUR_INNER_RING'],
  ['DOMLUR_INNER_RING', 'DOMLUR_FLYOVER'],

  // Sarjapur Road
  ['MADIWALA_HOSUR', 'SARJAPUR_WATER_TANK'],
  ['SARJAPUR_WATER_TANK', 'JAKKASANDRA_SARJAPUR'],
  ['JAKKASANDRA_SARJAPUR', 'AGARA_JUNCTION'],
  ['AGARA_JUNCTION', 'BELLANDUR_GATE_SARJAPUR'],

  // Outer Ring Road Spine
  ['SILK_BOARD', 'HSR_ORR'],
  ['HSR_ORR', 'AGARA_JUNCTION'],
  ['AGARA_JUNCTION', 'BELLANDUR_ORR'],
  ['BELLANDUR_ORR', 'ECOSPACE_ORR'],
  ['ECOSPACE_ORR', 'MARATHAHALLI_BRIDGE'],
  ['MARATHAHALLI_BRIDGE', 'MAHADEVAPURA_ORR'],
  ['MAHADEVAPURA_ORR', 'KR_PURAM_ORR'],
  ['KR_PURAM_ORR', 'KASTURI_NAGAR_ORR'],
  ['KASTURI_NAGAR_ORR', 'NAGAWARA_ORR'],
  ['NAGAWARA_ORR', 'HEBBAL_FLYOVER'],

  // Old Airport Road
  ['MG_ROAD', 'TRINITY_CIRCLE'],
  ['TRINITY_CIRCLE', 'DOMLUR_FLYOVER'],
  ['DOMLUR_FLYOVER', 'MANIPAL_HOSPITAL_AIRPORT_RD'],
  ['MANIPAL_HOSPITAL_AIRPORT_RD', 'HAL_AIRPORT_RD'],
  ['HAL_AIRPORT_RD', 'MARATHAHALLI_BRIDGE'],
  ['MARATHAHALLI_BRIDGE', 'KUNDALAHALLI_GATE'],
  ['KUNDALAHALLI_GATE', 'WHITEFIELD_HOPE_FARM'],

  // Bellary Road (North)
  ['MG_ROAD', 'CUNNINGHAM_RD'],
  ['CUNNINGHAM_RD', 'MEKHRI_CIRCLE'],
  ['MEKHRI_CIRCLE', 'HEBBAL_FLYOVER'],
  ['HEBBAL_FLYOVER', 'KODIGEHALLI_GATE'],
  ['KODIGEHALLI_GATE', 'NORTH_BASE_HUB'],

  // West Arterials
  ['MG_ROAD', 'MAJESTIC_STATION'],
  ['MAJESTIC_STATION', 'OKALIPURAM'],
  ['OKALIPURAM', 'WEST_BASE_HUB'],
  ['WEST_BASE_HUB', 'NAVRANG_CIRCLE'],
  ['NAVRANG_CIRCLE', 'YESHWANTHPUR_JUNCTION'],
  ['YESHWANTHPUR_JUNCTION', 'HEBBAL_FLYOVER'],

  // Bannerghatta Road
  ['ADUGODI_HOSUR', 'DAIRY_CIRCLE'],
  ['DAIRY_CIRCLE', 'JAYADEVA_FLYOVER'],
  ['JAYADEVA_FLYOVER', 'AREKERE_BANNERGHATTA'],
];

// Build adjacency graph map
const ADJ_LIST = {};
for (const key of Object.keys(ROAD_NODES)) {
  ADJ_LIST[key] = [];
}
for (const [u, v] of ROAD_EDGES) {
  if (ADJ_LIST[u] && ADJ_LIST[v]) {
    const d = haversineDist(ROAD_NODES[u], ROAD_NODES[v]);
    ADJ_LIST[u].push({ node: v, dist: d });
    ADJ_LIST[v].push({ node: u, dist: d });
  }
}

function findNearestRoadNode(coord) {
  let minD = Infinity;
  let best = 'MG_ROAD';
  for (const [key, pt] of Object.entries(ROAD_NODES)) {
    const d = haversineDist(coord, pt);
    if (d < minD) {
      minD = d;
      best = key;
    }
  }
  return best;
}

// Shortest path via Dijkstra on the Bangalore road corridor network
function findShortestCorridorPath(startNode, endNode) {
  if (startNode === endNode) return [ROAD_NODES[startNode]];

  const distances = {};
  const prev = {};
  const unvisited = new Set(Object.keys(ROAD_NODES));

  for (const node of unvisited) {
    distances[node] = Infinity;
  }
  distances[startNode] = 0;

  while (unvisited.size > 0) {
    let curr = null;
    let minDist = Infinity;
    for (const node of unvisited) {
      if (distances[node] < minDist) {
        minDist = distances[node];
        curr = node;
      }
    }

    if (!curr || minDist === Infinity || curr === endNode) break;
    unvisited.delete(curr);

    for (const edge of ADJ_LIST[curr] || []) {
      if (!unvisited.has(edge.node)) continue;
      const alt = distances[curr] + edge.dist;
      if (alt < distances[edge.node]) {
        distances[edge.node] = alt;
        prev[edge.node] = curr;
      }
    }
  }

  // Backtrack path
  const path = [];
  let u = endNode;
  while (u) {
    path.unshift(ROAD_NODES[u]);
    u = prev[u];
  }

  return path.length > 1 ? path : [ROAD_NODES[startNode], ROAD_NODES[endNode]];
}

/**
 * Resample polyline so waypoints are evenly distributed by distance.
 * This ensures the drone flies at a uniform, smooth speed without erratic jumps.
 */
export function resamplePolyline(points, numSteps = 24) {
  if (!points || points.length === 0) return [];
  if (points.length === 1 || numSteps <= 1) return Array(numSteps).fill(points[0]);

  const cumDists = [0];
  for (let i = 1; i < points.length; i++) {
    cumDists.push(cumDists[i - 1] + haversineDist(points[i - 1], points[i]));
  }
  const totalDist = cumDists[cumDists.length - 1];
  if (totalDist === 0) return Array(numSteps).fill(points[0]);

  const resampled = [points[0]];
  for (let s = 1; s < numSteps - 1; s++) {
    const targetDist = (s / (numSteps - 1)) * totalDist;
    let idx = 1;
    while (idx < cumDists.length && cumDists[idx] < targetDist) {
      idx++;
    }
    const prevDist = cumDists[idx - 1];
    const segDist = cumDists[idx] - prevDist;
    const ratio = segDist > 0 ? (targetDist - prevDist) / segDist : 0;
    const p1 = points[idx - 1];
    const p2 = points[idx];
    resampled.push([
      p1[0] + (p2[0] - p1[0]) * ratio,
      p1[1] + (p2[1] - p1[1]) * ratio,
    ]);
  }
  resampled.push(points[points.length - 1]);
  return resampled;
}

/**
 * Build offline road corridor route:
 * 1. Snaps start to nearest road intersection via local street line.
 * 2. Navigates Bangalore arterial road graph.
 * 3. Enters destination via local street line.
 */
function getOfflineRoadCorridor(start, end) {
  const startRoadNode = findNearestRoadNode(start);
  const endRoadNode = findNearestRoadNode(end);

  const startPt = ROAD_NODES[startRoadNode];
  const endPt = ROAD_NODES[endRoadNode];

  // Route along arterial network
  const networkPath = findShortestCorridorPath(startRoadNode, endRoadNode);

  // Connect start -> road network, following street alignment (avoiding diagonals through blocks)
  const fullRawPath = [];

  // Local street entry to road network (orthogonal street step)
  fullRawPath.push(start);
  if (Math.abs(start[0] - startPt[0]) > 0.0005 || Math.abs(start[1] - startPt[1]) > 0.0005) {
    fullRawPath.push([start[0], startPt[1]]); // Turn along street alignment
  }
  fullRawPath.push(startPt);

  // Add road corridor network points
  for (let i = 1; i < networkPath.length - 1; i++) {
    fullRawPath.push(networkPath[i]);
  }

  // Local street exit from road network to destination
  fullRawPath.push(endPt);
  if (Math.abs(end[0] - endPt[0]) > 0.0005 || Math.abs(end[1] - endPt[1]) > 0.0005) {
    fullRawPath.push([endPt[0], end[1]]); // Turn along destination access street
  }
  fullRawPath.push(end);

  return fullRawPath;
}

/**
 * Main export: Computes building-avoiding road flight path between start & end.
 * First queries OSRM driving route for 100% exact street alignment.
 * If OSRM is slow (> 2.0s) or fails, falls back to the Bangalore Road Corridor graph.
 */
export async function getRoadCorridorRoute(start, end, targetSteps = 24) {
  if (!start || !end) return [start || [77.5946, 12.9716], end || [77.6245, 12.9352]];

  // 1. Try real OpenStreetMap road routing
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2200);

    const osrmUrl = `https://router.project-osrm.org/route/v1/driving/${start[0]},${start[1]};${end[0]},${end[1]}?overview=full&geometries=geojson`;
    const res = await fetch(osrmUrl, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      const coords = data.routes?.[0]?.geometry?.coordinates;
      if (Array.isArray(coords) && coords.length >= 2) {
        return resamplePolyline(coords, targetSteps);
      }
    }
  } catch (err) {
    // Network timeout, rate limit, or offline - fall through to offline graph
  }

  // 2. Offline Bangalore Arterial Road Corridor Routing
  const offlineRaw = getOfflineRoadCorridor(start, end);
  return resamplePolyline(offlineRaw, targetSteps);
}
