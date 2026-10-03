import type { User, Role } from '../../types';
import { db, respond, save, dateAfter } from './store';
const SESSION = 'fraudshield-session-v1';
export const authApi = {
  current(): User | null { try { const id = sessionStorage.getItem(SESSION); return db().users.find(u => u.id === id) || null; } catch { return null; } },
  async login(email: string, password: string, role: Role) {
    if (password.length < 6) throw new Error('Enter a demo password with at least 6 characters.');
    const user = db().users.find(u => u.email.toLowerCase() === email.trim().toLowerCase() && u.role === role);
    if (!user) throw new Error('No demo account found. Use the demo account below or create an account.');
    sessionStorage.setItem(SESSION, user.id); return respond(user);
  },
  async register(name: string, email: string, password: string) {
    if (!name.trim() || password.length < 6) throw new Error('Enter a name and a password of at least 6 characters.');
    if (db().users.some(u => u.email.toLowerCase() === email.trim().toLowerCase())) throw new Error('This email already has a demo account. Please sign in.');
    const user: User = { id: `USR${crypto.randomUUID().slice(0, 8)}`, name: name.trim(), email: email.trim().toLowerCase(), phone: '', city: 'Chennai', company: '', joined: dateAfter(0), role: 'USER' };
    db().users.push(user); save(); sessionStorage.setItem(SESSION, user.id); return respond(user);
  },
  logout() { sessionStorage.removeItem(SESSION); },
};
