import { beforeEach, describe, expect, it, vi } from 'vitest';
class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}
function modelResponse(probability = 1) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
    if (url.endsWith('/payments/config')) return { ok: true, json: async () => ({ enabled: true, key_id: 'rzp_test_portal', currency: 'INR' }) };
    if (url.endsWith('/payments/razorpay/order')) return { ok: true, json: async () => ({ key_id: 'rzp_test_portal', order_id: 'order_test_portal', amount: 40300, currency: 'INR' }) };
    if (url.endsWith('/payments/razorpay/verify')) return { ok: true, json: async () => ({ status: 'Paid', mode: 'razorpay', reference: 'pay_test_portal', amount: 403, paid_at: new Date().toISOString() }) };
    if (url.endsWith('/notifications/shipment')) return { ok: true, json: async () => ({ sent: true }) };
    const request = JSON.parse(options.body as string);
    return { ok: true, json: async () => ({ booking_id: request.booking_id, source: 'trained', probability, model_version: 'lightgbm-test', scored_at: request.created, shap: [{ name: 'Order value', value: -.2 }], assumptions: ['Unvalidated logistics mapping'], missing_features: ['is_transfer'], unknown_categories: [] }) };
  }));
  const browserWindow = (globalThis as { window?: object }).window || {};
  vi.stubGlobal('window', Object.assign(browserWindow, { dispatchEvent: () => true, addEventListener: () => undefined,
    removeEventListener: () => undefined, Razorpay: class {
    private options: { handler: (result: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => void };
    constructor(options: typeof this.options) { this.options = options; }
    on() { }
    open() { this.options.handler({ razorpay_order_id: 'order_test_portal', razorpay_payment_id: 'pay_test_portal', razorpay_signature: 'a'.repeat(64) }); }
  } }));
}
beforeEach(() => { vi.resetModules(); vi.stubGlobal('localStorage', new MemoryStorage()); vi.stubGlobal('sessionStorage', new MemoryStorage()); modelResponse(); });
async function customer() {
  const { authApi } = await import('./authApi');
  const user = await authApi.login('aarav@example.com', 'demo123', 'USER');
  const { emptyDraft } = await import('./store');
  const draft = emptyDraft(user); draft.receiver = { ...draft.sender, name: 'Demo receiver', city: 'Mumbai' }; draft.description = 'Camera equipment';
  return { user, draft };
}
async function administrator() { const { authApi } = await import('./authApi'); return authApi.login('admin@example.com', 'demo123', 'ADMIN'); }
async function booking() { const { user, draft } = await customer(); const { shipmentApi } = await import('./shipmentApi'); return shipmentApi.create(draft, user, 'confirmation-1'); }

describe('Payment, saved model, approval, and dispatch workflow', () => {
  it('keeps seeded approval statuses coherent with shipping', async () => {
    const { db } = await import('./store');
    expect(db().shipments).toHaveLength(64);
    expect(new Set(db().shipments.map(s => s.status))).toEqual(new Set(['Awaiting Approval', 'On Hold', 'Approved', 'Blocked']));
    expect(db().shipments.filter(s => s.status !== 'Approved').every(s => s.delivery === 'Created')).toBe(true);
  });
  it('updates quotes and keeps risk boundaries consistent', async () => {
    const { emptyDraft, priceFor, riskLevel, buildRisk } = await import('./store'); const draft = emptyDraft(); const first = priceFor(draft);
    expect(priceFor({ ...draft, weight: 10 }).total).toBeGreaterThan(first.total);
    expect(priceFor({ ...draft, collection: 'Drop-off' }).total).toBe(first.total - 79);
    expect(priceFor({ ...draft, protection: 'Additional', declaredValue: 85000 }).protection).toBe(850);
    expect(priceFor({ ...draft, discount: true }).discount).toBeLessThanOrEqual(100);
    expect([0, 29, 30, 59, 60, 79, 80, 100].map(riskLevel)).toEqual(['LOW', 'LOW', 'MEDIUM', 'MEDIUM', 'HIGH', 'HIGH', 'CRITICAL', 'CRITICAL']);
    expect(buildRisk(85, [true, true, true, true]).overall).toBe(91);
  });
  it.each([0.01, 0.7])('routes a paid booking by its risk score at probability %s', async probability => {
    modelResponse(probability); const s = await booking();
    const { adminApi } = await import('./adminApi'); const { trackingApi } = await import('./trackingApi'); const { userApi } = await import('./userApi');
    expect(s.status).toBe(probability < 0.5 ? 'Approved' : 'Awaiting Verification'); expect(s.delivery).toBe('Created');
    expect(s.payment.status).toBe('Paid'); expect(s.risk.source).toBe('trained'); expect(s.risk.ai).toBe(probability * 100);
    expect(s.risk.factors.some(f => f.name === 'New device')).toBe(false);
    expect((await adminApi.list()).some(x => x.id === s.id)).toBe(true);
    expect((await trackingApi.get(s.id, s.userId)).status).toBe(s.status);
    expect((await userApi.notices(s.userId)).some(n => n.shipmentId === s.id)).toBe(true);
    const scoreCall = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/score'))!;
    const request = JSON.parse(scoreCall[1]!.body as string);
    expect(JSON.stringify(request)).not.toContain('@example.com');
    expect(request.history.every((h: { created: string }) => h.created < s.created)).toBe(true);
  });
  it('requires the emailed step-up code and then approves without an administrator', async () => {
    modelResponse(.7); const { user } = await customer(); const s = await booking();
    expect(s.status).toBe('Awaiting Verification');
    const { adminApi } = await import('./adminApi'); await administrator();
    await expect(adminApi.decide(s.id, 'Approved', 'Verified customer', '', s.revision)).rejects.toThrow('email verification');
    const { authApi } = await import('./authApi'); authApi.logout(); await authApi.login(user.email, 'demo123', 'USER');
    const { shipmentApi } = await import('./shipmentApi');
    const verified = await shipmentApi.verifyStepUpCode(s.id, user, '123456');
    expect(verified.status).toBe('Approved'); expect(verified.audit[0].admin).toBe('Email verification');
  });
  it('deduplicates simultaneous confirmation and protects the paid draft', async () => {
    const { user, draft } = await customer(); const { shipmentApi } = await import('./shipmentApi'); const { db } = await import('./store');
    const [a, b] = await Promise.all([shipmentApi.create(draft, user, 'same'), shipmentApi.create(draft, user, 'same')]);
    expect(a.id).toBe(b.id); expect(db().payments.filter(p => p.submissionId === 'same')).toHaveLength(1);
    expect(db().shipments.filter(s => s.payment.reference === a.payment.reference)).toHaveLength(1);
    draft.description = 'Changed after payment';
    await expect(shipmentApi.create(draft, user, 'same')).rejects.toThrow('changed');
    expect(db().shipments.find(s => s.id === a.id)?.draft.description).toBe('Camera equipment');
  });
  it('does not create a booking when payment failed', async () => {
    const { user, draft } = await customer(); const { paymentApi } = await import('./paymentApi'); const { db, save } = await import('./store'); const { shipmentApi } = await import('./shipmentApi');
    vi.spyOn(paymentApi, 'pay').mockResolvedValue({ status: 'Failed', mode: 'razorpay', reference: 'pay_failed', amount: 403, paidAt: new Date().toISOString(), userId: user.id, submissionId: 'failed', draftKey: JSON.stringify(draft) });
    const count = db().shipments.length;
    await expect(shipmentApi.create(draft, user, 'failed')).rejects.toThrow('Payment');
    expect(db().shipments).toHaveLength(count);
  });
  it('keeps paid bookings pending on model failure and blocks approval until a successful retry', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
      if (url.endsWith('/payments/config')) return { ok: true, json: async () => ({ enabled: true, key_id: 'rzp_test_portal', currency: 'INR' }) };
      if (url.endsWith('/payments/razorpay/order')) return { ok: true, json: async () => ({ key_id: 'rzp_test_portal', order_id: 'order_test_portal', amount: 40300, currency: 'INR' }) };
      if (url.endsWith('/payments/razorpay/verify')) return { ok: true, json: async () => ({ status: 'Paid', mode: 'razorpay', reference: 'pay_test_portal', amount: 403, paid_at: new Date().toISOString() }) };
      if (url.endsWith('/score')) throw new Error('Offline');
      return { ok: true, json: async () => ({ sent: true }) };
    }));
    const s = await booking(); expect(s.risk.source).toBe('unavailable'); expect(s.risk.overall).toBeNull();
    const { adminApi } = await import('./adminApi'); await administrator();
    await expect(adminApi.decide(s.id, 'Approved', 'Verified customer', '', s.revision)).rejects.toThrow('risk score');
    await expect(adminApi.dispatch(s.id, s.revision)).rejects.toThrow('approve');
    modelResponse(.25); const scored = await adminApi.retryScore(s.id, s.revision);
    expect(scored.status).toBe('Awaiting Approval'); expect(scored.risk.ai).toBe(25);
    expect(scored.audit[0].riskSnapshot?.source).toBe('unavailable');
    expect((await adminApi.decide(s.id, 'Approved', 'Verified customer', '', scored.revision)).status).toBe('Approved');
  });
  it('rejects invalid model results instead of substituting simulated scores', async () => {
    modelResponse(NaN); const s = await booking(); expect(s.risk.source).toBe('unavailable'); expect(s.risk.shap).toEqual([]);
  });
  it('requires an admin and reason, retains evidence, and rejects stale decisions', async () => {
    const s = await booking(); const { adminApi } = await import('./adminApi');
    await expect(adminApi.decide(s.id, 'Approved', 'Verified customer', '', s.revision)).rejects.toThrow('administrator');
    await administrator();
    await expect(adminApi.decide(s.id, 'Blocked', 'Other', '', s.revision)).rejects.toThrow('note');
    const held = await adminApi.decide(s.id, 'On Hold', 'Other', 'Verify recipient', s.revision);
    await expect(adminApi.decide(s.id, 'Approved', 'Verified customer', '', s.revision)).rejects.toThrow('changed');
    const blocked = await adminApi.decide(s.id, 'Blocked', 'Other', 'Unresolved verification', held.revision);
    await expect(adminApi.dispatch(s.id, blocked.revision)).rejects.toThrow('approve');
    const approved = await adminApi.decide(s.id, 'Approved', 'Additional verification completed', 'Customer confirmed details', blocked.revision);
    expect(approved.delivery).toBe('Created'); expect(approved.dispatchedAt).toBeUndefined();
    expect(approved.risk).toEqual(s.risk); expect(approved.audit.map(a => a.decision)).toEqual(['Approved', 'Blocked', 'On Hold']);
    expect(approved.audit.every(a => JSON.stringify(a.riskSnapshot) === JSON.stringify(s.risk))).toBe(true);
  });
  it('requires payment plus approval before dispatch, makes dispatch idempotent, and locks review afterward', async () => {
    const s = await booking(); await administrator(); const { adminApi } = await import('./adminApi'); const { db, save } = await import('./store');
    await expect(adminApi.dispatch(s.id, s.revision)).rejects.toThrow('approve');
    const approved = await adminApi.decide(s.id, 'Approved', 'Verified customer', '', s.revision);
    await expect(adminApi.retryScore(s.id, approved.revision)).rejects.toThrow('hold');
    db().shipments.find(x => x.id === s.id)!.payment.status = 'Failed'; save();
    await expect(adminApi.dispatch(s.id, approved.revision)).rejects.toThrow('Payment');
    db().shipments.find(x => x.id === s.id)!.payment.status = 'Paid'; save();
    const sent = await adminApi.dispatch(s.id, approved.revision);
    expect(sent.delivery).toBe('Picked Up'); expect(sent.dispatchedAt).toBeTruthy();
    expect((await adminApi.dispatch(s.id, approved.revision)).audit).toHaveLength(2);
    await expect(adminApi.decide(s.id, 'Blocked', 'Other', 'Late decision', sent.revision)).rejects.toThrow('already started');
  });
  it('scopes tracking to the customer and separates demo roles', async () => {
    const { trackingApi } = await import('./trackingApi'); const { authApi } = await import('./authApi'); const { db } = await import('./store');
    await expect(trackingApi.get(db().shipments[0].id, db().users[1].id)).rejects.toThrow('could not find');
    await expect(authApi.login('aarav@example.com', 'demo123', 'ADMIN')).rejects.toThrow('Account not found');
    const user = await authApi.register('Example', 'new@example.com', 'not-a-real-password'); expect(user.role).toBe('USER');
    expect(JSON.stringify(db())).not.toContain('not-a-real-password'); authApi.logout(); expect(authApi.current()).toBeNull();
  });
  it('refreshes cached data after a different tab writes and preserves it across reload', async () => {
    const { db, save } = await import('./store'); save(); const stored = JSON.parse(localStorage.getItem('fraudshield-portal-v1')!);
    stored.shipments[0].status = 'On Hold'; stored.shipments[0].revision++;
    localStorage.setItem('fraudshield-portal-v1', JSON.stringify(stored));
    expect(db().shipments[0].status).toBe('On Hold');
    vi.resetModules(); const fresh = await import('./store'); expect(fresh.db().shipments[0].revision).toBe(2);
  });
  it('migrates old reviews and clears unapproved shipping progress', async () => {
    const { db } = await import('./store'); const old = JSON.parse(JSON.stringify(db()));
    old.shipments[0].status = 'Suspicious'; old.shipments[0].delivery = 'In Transit'; delete old.shipments[0].payment; delete old.shipments[0].risk.source; delete old.payments;
    localStorage.setItem('fraudshield-portal-v1', JSON.stringify(old)); vi.resetModules(); const fresh = await import('./store');
    expect(fresh.db().shipments[0].status).toBe('Awaiting Approval'); expect(fresh.db().shipments[0].delivery).toBe('Created'); expect(fresh.db().shipments[0].risk.source).toBe('simulated');
  });
});
