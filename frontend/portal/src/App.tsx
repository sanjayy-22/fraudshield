import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, Link } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ToastProvider, Empty } from './components/ui/shared';
import { AppLayout } from './components/layout/AppLayout';
import { AuthPage } from './pages/AuthPage';
import { UserDashboard } from './pages/UserDashboard';
import { ShipmentsPage } from './pages/ShipmentsPage';
import { CreateShipmentPage } from './pages/CreateShipmentPage';
import { TrackingPage } from './pages/TrackingPage';
import { MessagesPage } from './pages/MessagesPage';
import { ProfilePage } from './pages/ProfilePage';
import { AdminDashboard, AdminPackages, PackageReview, AdminUserPage, AuditPage } from './pages/AdminPages';
import type { Role } from './types';
function Guard({ role }: { role: Role }) { const { user } = useAuth(); const location = useLocation(); if (!user) return <Navigate to={role === 'ADMIN' ? '/admin/login' : '/login'} state={{ from: location.pathname }} replace/>; if (user.role !== role) return <Navigate to={user.role === 'ADMIN' ? '/admin/dashboard' : '/user/dashboard'} replace/>; return <Outlet/>; }
function Start() { const { user } = useAuth(); return <Navigate to={user ? user.role === 'ADMIN' ? '/admin/dashboard' : '/user/dashboard' : '/login'} replace/>; }
export default function App() { return <BrowserRouter><AuthProvider><ToastProvider><Routes><Route path="/" element={<Start/>}/><Route path="/login" element={<AuthPage/>}/><Route path="/register" element={<AuthPage register/>}/><Route path="/admin/login" element={<AuthPage admin/>}/><Route element={<Guard role="USER"/>}><Route element={<AppLayout/>}><Route path="/user/dashboard" element={<UserDashboard/>}/><Route path="/user/shipments" element={<ShipmentsPage/>}/><Route path="/user/create-shipment" element={<CreateShipmentPage/>}/><Route path="/user/track" element={<TrackingPage/>}/><Route path="/user/inbox" element={<MessagesPage/>}/><Route path="/user/alerts" element={<MessagesPage alerts/>}/><Route path="/user/profile" element={<ProfilePage/>}/></Route></Route><Route element={<Guard role="ADMIN"/>}><Route element={<AppLayout/>}><Route path="/admin/dashboard" element={<AdminDashboard/>}/><Route path="/admin/packages" element={<AdminPackages/>}/><Route path="/admin/packages/suspicious" element={<AdminPackages preset="Suspicious"/>}/><Route path="/admin/packages/on-hold" element={<AdminPackages preset="On Hold"/>}/><Route path="/admin/packages/approved" element={<AdminPackages preset="Approved"/>}/><Route path="/admin/packages/blocked" element={<AdminPackages preset="Blocked"/>}/><Route path="/admin/packages/review/:id" element={<PackageReview/>}/><Route path="/admin/users/:id" element={<AdminUserPage/>}/><Route path="/admin/audit" element={<AuditPage/>}/></Route></Route><Route path="*" element={<div className="not-found"><Empty title="This page took a different route" message="Let’s get you back to your workspace."><Link className="btn primary" to="/">Back to workspace</Link></Empty></div>}/></Routes></ToastProvider></AuthProvider></BrowserRouter>; }
