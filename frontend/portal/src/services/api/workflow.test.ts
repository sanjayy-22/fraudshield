import { beforeEach, describe, expect, it, vi } from 'vitest';

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
  clear() { this.data.clear(); }
}
beforeEach(() => { vi.resetModules(); vi.stubGlobal('localStorage', new MemoryStorage()); vi.stubGlobal('sessionStorage', new MemoryStorage()); });

describe('Frontend demonstration workflows', () => {
  it('provides a realistic investigation queue with all statuses and a 91-point showcase', async () => {
    const { db } = await import('./store');
    expect(db().users.filter(u => u.role === 'USER').length).toBeGreaterThanOrEqual(20);
    expect(db().shipments.length).toBeGreaterThanOrEqual(50);
    expect(new Set(db().shipments.map(s => s.status))).toEqual(new Set(['Under Review', 'Suspicious', 'On Hold', 'Approved', 'Blocked']));
    expect(db().shipments[0].risk.overall).toBe(91);
  });
  it('updates the quote for weight, collection, protection, and discount', async () => {
    const { emptyDraft, priceFor } = await import('./store');
    const d = emptyDraft();
    const first = priceFor(d);
    expect(priceFor({ ...d, weight: 10 }).total).toBeGreaterThan(first.total);
    expect(priceFor({ ...d, collection: 'Drop-off' }).total).toBe(first.total - 79);
    expect(priceFor({ ...d, protection: 'Additional', declaredValue: 85000 }).protection).toBe(850);
    const discount = priceFor({ ...d, discount: true });
    expect(discount.total).toBe(first.total - discount.discount);
    expect(discount.discount).toBeLessThanOrEqual(100);
  });
  it('uses a consistent risk formula and boundary levels', async () => {
    const { riskLevel, buildRisk } = await import('./store');
    expect([0, 29, 30, 59, 60, 79, 80, 100].map(riskLevel)).toEqual(['LOW', 'LOW', 'MEDIUM', 'MEDIUM', 'HIGH', 'HIGH', 'CRITICAL', 'CRITICAL']);
    expect(buildRisk(85, [true, true, true, true]).overall).toBe(91);
    expect(buildRisk(10, [false, false, false, false]).overall).toBe(6);
  });
  it('creates a shipment that appears in tracking, inbox, and the admin queue', async () => {
    const { db, emptyDraft } = await import('./store');
    const { shipmentApi } = await import('./shipmentApi');
    const { trackingApi } = await import('./trackingApi');
    const { adminApi } = await import('./adminApi');
    const { userApi } = await import('./userApi');
    const user = db().users[0];
    const d = { ...emptyDraft(user), value: 85000, declaredValue: 85000, description: 'Camera equipment' };
    d.receiver = { ...d.sender, city: 'Mumbai', name: 'Demo Receiver' };
    const s = await shipmentApi.create(d, user);
    expect(s.risk.overall).toBe(91);
    expect(s.status).toBe('Suspicious');
    expect((await trackingApi.get(s.id.toLowerCase(), user.id)).id).toBe(s.id);
    expect((await adminApi.list()).some(x => x.id === s.id)).toBe(true);
    expect((await userApi.notices(user.id)).some(n => n.shipmentId === s.id)).toBe(true);
    d.description = 'Changed after creating';
    expect((await adminApi.get(s.id)).draft.description).toBe('Camera equipment');
  });
  it('does not expose another demo customer’s shipment through tracking', async () => {
    const { db } = await import('./store');
    const { trackingApi } = await import('./trackingApi');
    await expect(trackingApi.get(db().shipments[0].id, db().users[1].id)).rejects.toThrow('could not find');
  });
  it('retains original evidence through hold, block, and approval with an audit record per decision', async () => {
    const { db } = await import('./store');
    const { adminApi } = await import('./adminApi');
    const s = db().shipments[0]; const risk = structuredClone(s.risk);
    await expect(adminApi.decide(s.id, 'Blocked', 'Priya Sharma', 'Other', '')).rejects.toThrow('note');
    await adminApi.decide(s.id, 'On Hold', 'Priya Sharma', 'Other', 'Waiting for account verification');
    await adminApi.decide(s.id, 'Blocked', 'Priya Sharma', 'Suspicious activity confirmed', 'Demo investigation outcome');
    const updated = await adminApi.decide(s.id, 'Approved', 'Priya Sharma', 'Additional verification completed', 'New evidence resolved concerns');
    expect(updated.risk).toEqual(risk);
    expect(updated.audit.map(a => a.decision)).toEqual(['Approved', 'Blocked', 'On Hold']);
    expect(updated.status).toBe('Approved');
  });
  it('separates demo account roles and does not save passwords', async () => {
    const { authApi } = await import('./authApi');
    const { db } = await import('./store');
    await expect(authApi.login('aarav@example.com', 'demo123', 'ADMIN')).rejects.toThrow('No demo account');
    const user = await authApi.register('Demo Example', 'demo.person@example.com', 'not-a-real-password');
    expect(authApi.current()?.id).toBe(user.id);
    expect(JSON.stringify(db())).not.toContain('not-a-real-password');
    expect(user.role).toBe('USER');
    authApi.logout(); expect(authApi.current()).toBeNull();
  });
  it('persists decisions across a service reload', async () => {
    const { adminApi } = await import('./adminApi');
    const id = 'FS84729103';
    await adminApi.decide(id, 'On Hold', 'Demo Admin', 'Other', 'Persistence check');
    vi.resetModules();
    const reloaded = await import('./adminApi');
    expect((await reloaded.adminApi.get(id)).status).toBe('On Hold');
    expect((await reloaded.adminApi.get(id)).audit[0].notes).toBe('Persistence check');
  });
});
