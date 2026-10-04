import type { ReviewStatus } from '../../types';
import { db, respond, transaction, dateAfter } from './store';
import { requireAdmin, assertReviewable, assertCanDispatch, isDispatched } from './workflow';
import { scoreDraft } from './riskApi';

export const adminApi = {
  async list() { return respond(db().shipments); },
  async get(id: string) { const s = db().shipments.find(s => s.id === id); if (!s) throw new Error('This shipment could not be found.'); return respond(s); },
  async decide(id: string, decision: ReviewStatus, reason: string, notes: string, revision: number) {
    const admin = requireAdmin();
    if (!['Approved', 'On Hold', 'Blocked'].includes(decision)) throw new Error('Choose approve, hold, or block.');
    if (!reason || (reason === 'Other' && !notes.trim())) throw new Error('Select a reason and add a note when choosing Other.');
    return transaction(store => {
      const s = store.shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.');
      assertReviewable(s, revision);
      if (s.status === decision) return s;
      if (decision === 'Approved' && s.status === 'Awaiting Verification') throw new Error('The customer must complete the email verification step before this shipment can be approved.');
      if (decision === 'Approved' && (s.payment.status !== 'Paid' || s.risk.source === 'unavailable')) throw new Error('A completed payment and an available risk score are required for approval.');
      const at = new Date().toISOString();
      s.status = decision; s.approvedAt = decision === 'Approved' ? at : undefined; s.revision++;
      s.audit.unshift({ id: crypto.randomUUID(), shipmentId: id, decision, admin: admin.name, reason, notes: notes.trim(), at, riskSnapshot: structuredClone(s.risk) });
      const message = decision === 'Approved' ? 'Approved and ready to ship. Collection has not started.' : decision === 'On Hold' ? 'On hold while the administrator reviews more information. Shipping has not started.' : 'Blocked from shipping. This action does not issue a refund.';
      store.notices.unshift({ id: crypto.randomUUID(), userId: s.userId, title: 'Shipment update: ' + decision, body: id + ': ' + message, type: 'verification', at, read: false, shipmentId: id });
      return s;
    });
  },
  async dispatch(id: string, revision: number) {
    const admin = requireAdmin();
    return transaction(store => {
      const s = store.shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.');
      if (isDispatched(s)) return s;
      assertReviewable(s, revision); assertCanDispatch(s);
      const at = new Date().toISOString();
      s.dispatchedAt = at; s.delivery = 'Picked Up'; s.location = s.draft.sender.city; s.expected = dateAfter(4); s.revision++;
      s.audit.unshift({ id: crypto.randomUUID(), shipmentId: id, decision: 'Dispatched', admin: admin.name, reason: 'Approved booking released', notes: 'Simulated dispatch; no carrier was contacted.', at, riskSnapshot: structuredClone(s.risk) });
      store.notices.unshift({ id: crypto.randomUUID(), userId: s.userId, title: 'Shipment dispatch simulated', body: id + ' has moved to Picked Up in the demo. No real pickup was requested.', type: 'shipment', at, read: false, shipmentId: id });
      return s;
    });
  },
  async retryScore(id: string, revision: number) {
    const admin = requireAdmin();
    const snapshot = structuredClone(db().shipments.find(s => s.id === id));
    if (!snapshot) throw new Error('Shipment not found.');
    assertReviewable(snapshot, revision);
    if (snapshot.status === 'Approved') throw new Error('Place the booking on hold before changing its risk evidence.');
    const user = db().users.find(u => u.id === snapshot.userId); if (!user) throw new Error('Customer not found.');
    const risk = await scoreDraft(snapshot.draft, user, id, snapshot.created, db().shipments);
    if (risk.source === 'unavailable') throw new Error(risk.error || 'Model scoring is unavailable.');
    return transaction(store => {
      const s = store.shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.');
      assertReviewable(s, revision);
      s.audit.unshift({ id: crypto.randomUUID(), shipmentId: id, decision: 'Score updated', admin: admin.name, reason: 'Saved model scoring completed', notes: 'Previous risk evidence retained in this entry.', at: new Date().toISOString(), riskSnapshot: structuredClone(s.risk) });
      s.risk = risk; s.revision++;
      return s;
    });
  },
  async audit() { return respond(db().shipments.flatMap(s => s.audit).sort((a, b) => b.at.localeCompare(a.at))); },
};
