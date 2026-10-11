import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from './store/auth';
import Navbar from './components/Navbar';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import NewRequest from './pages/NewRequest';
import MyRequests from './pages/MyRequests';
import OperatorConsole from './pages/OperatorConsole';
import FleetDashboard from './pages/FleetDashboard';
import AdminAnalytics from './pages/AdminAnalytics';
import MissionDetails from './pages/MissionDetails';
import { AlertTriangle, X } from 'lucide-react';

export function getRoleHome(role) {
  if (role === 'hospital' || role === 'hospital_admin') {
    return '/';
  }
  // Operator and Admin home
  return '/operator';
}

// Route Table metadata for probe a
export const ROUTE_TABLE = [
  { path: '/login', allowedRoles: ['public'], component: 'Login' },
  { path: '/register', allowedRoles: ['public'], component: 'Register' },
  { path: '/', allowedRoles: ['hospital', 'hospital_admin'], component: 'Dashboard' },
  { path: '/requests/new', allowedRoles: ['hospital', 'hospital_admin'], component: 'NewRequest' },
  { path: '/requests', allowedRoles: ['hospital', 'hospital_admin'], component: 'MyRequests' },
  { path: '/operator', allowedRoles: ['operator', 'admin', 'system_admin'], component: 'OperatorConsole' },
  { path: '/fleet', allowedRoles: ['operator', 'admin', 'system_admin'], component: 'FleetDashboard' },
  { path: '/admin', allowedRoles: ['admin', 'system_admin'], component: 'AdminAnalytics' },
  { path: '/mission/:id', allowedRoles: ['hospital', 'hospital_admin', 'operator', 'admin', 'system_admin'], component: 'MissionDetails' },
  { path: '/missions/:id', allowedRoles: ['hospital', 'hospital_admin', 'operator', 'admin', 'system_admin'], component: 'MissionDetails' },
];

function PublicRoute({ children }) {
  const { token, user } = useAuthStore();
  if (token && user) {
    return <Navigate to={getRoleHome(user.role)} replace />;
  }
  return children;
}

function RoleRoute({ allowedRoles, children }) {
  const { token, user, setFlashMessage } = useAuthStore();
  const location = useLocation();

  if (!token || !user) {
    return <Navigate to="/login" replace />;
  }

  const userRole = user.role || 'hospital';
  const isAllowed = allowedRoles.includes(userRole);

  if (!isAllowed) {
    // Set explicit not allowed flash message and redirect to role's home
    const home = getRoleHome(userRole);
    setFlashMessage(`Access not allowed: Your role '${userRole}' is not permitted to view '${location.pathname}'.`);
    return <Navigate to={home} replace />;
  }

  return children;
}

function AppLayout({ children }) {
  const { token, user, flashMessage, clearFlashMessage } = useAuthStore();
  const location = useLocation();

  const isPublicAuthPage = location.pathname === '/login' || location.pathname === '/register';
  const showNavbar = token && user && !isPublicAuthPage;

  return (
    <div className="app-layout">
      {showNavbar && <Navbar />}

      {/* Global Role Access Banner (e.g. "not allowed" message) */}
      {showNavbar && flashMessage && (
        <div
          className="flash-banner flash-banner--error"
          id="flash-message-banner"
          style={{ padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertTriangle size={18} />
            <span id="flash-message-text">{flashMessage}</span>
          </div>
          <button
            type="button"
            onClick={clearFlashMessage}
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: '4px' }}
            title="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      )}

      <main className="main-content">
        {children}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          {/* Public Routes */}
          <Route
            path="/login"
            element={
              <PublicRoute>
                <Login />
              </PublicRoute>
            }
          />
          <Route
            path="/register"
            element={
              <PublicRoute>
                <Register />
              </PublicRoute>
            }
          />

          {/* Hospital Routes */}
          <Route
            path="/"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin']}>
                <Dashboard />
              </RoleRoute>
            }
          />
          <Route
            path="/requests/new"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin']}>
                <NewRequest />
              </RoleRoute>
            }
          />
          <Route
            path="/requests"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin']}>
                <MyRequests />
              </RoleRoute>
            }
          />

          {/* Operator Routes */}
          <Route
            path="/operator"
            element={
              <RoleRoute allowedRoles={['operator', 'admin', 'system_admin']}>
                <OperatorConsole />
              </RoleRoute>
            }
          />
          <Route
            path="/fleet"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin', 'operator', 'admin', 'system_admin']}>
                <FleetDashboard />
              </RoleRoute>
            }
          />

          {/* Admin Routes */}
          <Route
            path="/admin"
            element={
              <RoleRoute allowedRoles={['admin', 'system_admin']}>
                <AdminAnalytics />
              </RoleRoute>
            }
          />

          {/* Shared Mission Tracking Route */}
          <Route
            path="/mission/:id"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin', 'operator', 'admin', 'system_admin']}>
                <MissionDetails />
              </RoleRoute>
            }
          />
          <Route
            path="/missions/:id"
            element={
              <RoleRoute allowedRoles={['hospital', 'hospital_admin', 'operator', 'admin', 'system_admin']}>
                <MissionDetails />
              </RoleRoute>
            }
          />

          {/* Fallback Catchall */}
          <Route
            path="*"
            element={
              <Navigate to="/" replace />
            }
          />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}
