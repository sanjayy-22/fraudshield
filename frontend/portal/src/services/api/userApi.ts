import type { User } from '../../types';
import { db, respond, save, dropoffs } from './store';
export const userApi = {
  async list() { return respond(db().users.filter(u => u.role === 'USER')); },
  async get(id: string) { const user = db().users.find(u => u.id === id); if (!user) throw new Error('Account not found.'); return respond(user); },
  async update(id: string, changes: Pick<User, 'name' | 'phone' | 'company' | 'city'>) { const user = db().users.find(u => u.id === id); if (!user) throw new Error('Account not found.'); Object.assign(user, changes); save(); return respond(user); },
  async history(id: string) { return respond(db().shipments.filter(s => s.userId === id)); },
  async notices(id: string) { return respond(db().notices.filter(n => n.userId === id)); },
  async markRead(id: string, userId: string) { const n = db().notices.find(n => n.id === id && n.userId === userId); if (n) n.read = true; save(); return respond(true); },
  async readAll(userId: string) { db().notices.filter(n => n.userId === userId).forEach(n => n.read = true); save(); return respond(true); },
  dropoffs,
  async connections(userId: string) { const history = db().shipments.filter(s => s.userId === userId); const cities = [...new Set(history.map(s => s.draft.receiver.city))]; return respond({ devices: [{ name: 'Chrome · Windows', detail: 'Device A', count: Math.ceil(history.length * .7) }, { name: 'Safari · iPhone', detail: 'Device B', count: Math.floor(history.length * .3) }], addresses: cities.map(city => ({ name: city, count: history.filter(s => s.draft.receiver.city === city).length })), payments: ['Card •••• 1234', 'Card •••• 8891'] }); },
};
