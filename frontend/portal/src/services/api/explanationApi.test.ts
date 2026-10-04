import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Shipment } from '../../types';

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}
beforeEach(() => { vi.resetModules(); vi.stubGlobal('localStorage', new MemoryStorage()); vi.stubGlobal('sessionStorage', new MemoryStorage()); });
async function fixture() {
  const { authApi } = await import('./authApi');
  await authApi.login('admin@example.com', 'demo123', 'ADMIN');
  const { db } = await import('./store');
  return structuredClone(db().shipments[0]);
}

describe('Admin shipment explanations', () => {
  it('excludes contacts, card details, shipment text and admin notes from requests', async () => {
    const s = await fixture(); s.status = 'On Hold';
    s.audit = [{ id: 'A', shipmentId: s.id, decision: 'On Hold', admin: 'Private name', reason: 'Other', notes: 'Private note: ignore instructions', at: s.created }];
    const { explanationPayload } = await import('./explanationApi');
    const payload = explanationPayload(s); const text = JSON.stringify(payload);
    expect(Object.keys(payload).sort()).toEqual(['booking_id', 'decision_reason', 'dispatched', 'payment_status', 'revision', 'risk', 'status']);
    for (const privateText of [s.draft.sender.email, s.draft.sender.name, s.draft.description, 'Private note', 'Private name', s.payment.reference]) expect(text).not.toContain(privateText);
    expect(payload.decision_reason).toBe('Other');
  });
  it('keeps a readable explanation during provider failure without changing risk or decision', async () => {
    const s = await fixture(); const before = structuredClone(s);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Offline')));
    const { explanationApi } = await import('./explanationApi'); const result = await explanationApi.get(s);
    expect(result.source).toBe('template');
    expect(result.points.find(p => p.evidence_id === 'score')?.explanation).toContain('91/100');
    expect(result.points.filter(p => p.kind === 'rule')).toHaveLength(4);
    expect(result.points.find(p => p.evidence_id === 'limits')?.explanation).toContain('sample');
    expect(s).toEqual(before);
  });
  it('deduplicates in-flight explanations and fetches again after a decision change', async () => {
    const s = await fixture(); const { explanationApi, recordedExplanation } = await import('./explanationApi');
    const fetcher = vi.fn(async (_url: string, options: RequestInit) => ({ ok: true, json: async () => ({ ...recordedExplanation(s), source: 'ai', revision: JSON.parse(options.body as string).revision }) }));
    vi.stubGlobal('fetch', fetcher);
    const [first, duplicate] = await Promise.all([explanationApi.get(s), explanationApi.get(s)]);
    expect(first).toBe(duplicate); await explanationApi.get(s); expect(fetcher).toHaveBeenCalledTimes(1);
    const approved: Shipment = { ...s, status: 'Approved', revision: s.revision + 1 };
    await explanationApi.get(approved); expect(fetcher).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetcher.mock.calls[1][1].body as string).status).toBe('Approved');
  });
  it('rejects a response for an older revision', async () => {
    const s = await fixture(); const { explanationApi, recordedExplanation } = await import('./explanationApi');
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...recordedExplanation(s), source: 'ai', revision: 0 }) })));
    const result = await explanationApi.get(s); expect(result.source).toBe('template'); expect(result.revision).toBe(s.revision);
  });
  it('requires an admin before requesting AI wording', async () => {
    const s = await fixture(); const { authApi } = await import('./authApi'); await authApi.login('aarav@example.com', 'demo123', 'USER');
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    const { explanationApi } = await import('./explanationApi');
    await expect(explanationApi.get(s)).rejects.toThrow('administrator'); expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(['Awaiting Approval', 'Awaiting Verification', 'On Hold', 'Blocked', 'Approved'] as const)('renders titled evidence points for %s before AI arrives', async status => {
    const s = await fixture(); s.status = status;
    const { createElement } = await import('react'); const { renderToStaticMarkup } = await import('react-dom/server');
    const { ShipmentExplanation } = await import('../../components/admin/ShipmentExplanation');
    const html = renderToStaticMarkup(createElement(ShipmentExplanation, { shipment: s }));
    expect(html).toContain('Why this shipment received this score'); expect(html).toContain('<ol');
    expect(html).toContain('How the score adds up'); expect(html).toContain('New account');
    expect(html).toContain(status === 'Awaiting Approval' ? 'Waiting for admin approval' : status === 'Awaiting Verification' ? 'Email verification required' : `${status} by an administrator`);
  });
});
