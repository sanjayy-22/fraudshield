import type { User, Role } from '../../types';
import { db, respond, save, dateAfter } from './store';
import { currentDeviceType } from './device';
const SESSION = 'fraudshield-session-v1';
const PENDING_DEVICE_LOGIN = 'fraudshield-pending-device-login-v1';
const api = import.meta.env.VITE_PORTAL_API_URL || '/portal-api';

async function deviceRequest<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${api}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || 'Could not verify this sign-in device. Try again.');
  return result as T;
}

function findAccount(email: string, role: Role) {
  return db().users.find(u => u.email.toLowerCase() === email.trim().toLowerCase() && u.role === role);
}

export const authApi = {
  current(): User | null { try { const id = sessionStorage.getItem(SESSION); return db().users.find(u => u.id === id) || null; } catch { return null; } },
  async beginLogin(email: string, password: string, role: Role) {
    if (password.length < 6) throw new Error('Enter a password with at least 6 characters.');
    const user = findAccount(email, role);
    if (!user) throw new Error('Account not found. Create an account first.');
    const deviceType = currentDeviceType();
    const result = await deviceRequest<{ verification_required: boolean; last_accessed_device_type?: User['last_accessed_device_type']; destination?: string }>('/auth/device/check', { email: user.email, device_type: deviceType });
    if (result.verification_required) {
      sessionStorage.setItem(PENDING_DEVICE_LOGIN, JSON.stringify({ id: user.id, email: user.email, deviceType, role }));
      return { verificationRequired: true as const, destination: result.destination || user.email };
    }
    user.last_accessed_device_type = result.last_accessed_device_type || deviceType;
    save(); sessionStorage.removeItem(PENDING_DEVICE_LOGIN); sessionStorage.setItem(SESSION, user.id);
    return { verificationRequired: false as const, user: await respond(user) };
  },
  async verifyDeviceLogin(code: string) {
    let pending: { id: string; email: string; deviceType: ReturnType<typeof currentDeviceType>; role: Role } | null = null;
    try { pending = JSON.parse(sessionStorage.getItem(PENDING_DEVICE_LOGIN) || 'null'); } catch { /* ignore an invalid pending sign-in */ }
    if (!pending) throw new Error('Sign-in verification expired. Start again.');
    const result = await deviceRequest<{ verified: boolean; last_accessed_device_type: User['last_accessed_device_type'] }>('/auth/device/verify', {
      email: pending.email, device_type: pending.deviceType, code,
    });
    const user = db().users.find(u => u.id === pending!.id && u.role === pending!.role);
    if (!user || !result.verified) throw new Error('Could not complete this sign-in. Start again.');
    user.last_accessed_device_type = result.last_accessed_device_type;
    save(); sessionStorage.removeItem(PENDING_DEVICE_LOGIN); sessionStorage.setItem(SESSION, user.id);
    return respond(user);
  },
  cancelDeviceLogin() { sessionStorage.removeItem(PENDING_DEVICE_LOGIN); },
  async login(email: string, password: string, role: Role) {
    if (password.length < 6) throw new Error('Enter a password with at least 6 characters.');
    const user = findAccount(email, role);
    if (!user) throw new Error('Account not found. Create an account first.');
    sessionStorage.setItem(SESSION, user.id); return respond(user);
  },
  async register(name: string, email: string, password: string, role: Role = 'USER', inviteCode = '') {
    if (!name.trim() || password.length < 6) throw new Error('Enter a name and a password of at least 6 characters.');
    if (role === 'ADMIN') {
      const response = await fetch(`${import.meta.env.VITE_PORTAL_API_URL || '/portal-api'}/auth/admin-invite/validate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: inviteCode }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Admin account creation is not available.');
    }
    if (db().users.some(u => u.email.toLowerCase() === email.trim().toLowerCase())) throw new Error('This email already has an account. Please sign in.');
    const deviceType = currentDeviceType();
    const cleanEmail = email.trim().toLowerCase();
    await deviceRequest('/auth/device/enroll', { email: cleanEmail, device_type: deviceType });
    const user: User = { id: `${role === 'ADMIN' ? 'ADM' : 'USR'}${crypto.randomUUID().slice(0, 8)}`, name: name.trim(), email: cleanEmail, phone: '', city: 'Chennai', company: role === 'ADMIN' ? 'FraudShield Operations' : '', joined: dateAfter(0), role, last_accessed_device_type: deviceType };
    db().users.push(user); save(); sessionStorage.setItem(SESSION, user.id); return respond(user);
  },
  logout() { sessionStorage.removeItem(SESSION); },
};
