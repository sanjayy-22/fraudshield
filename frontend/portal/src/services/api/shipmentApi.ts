import type { Shipment, ShipmentDraft, User } from '../../types';
import { db, respond, transaction, priceFor, dateAfter, emptyDraft } from './store';
import { scoreDraft } from './riskApi';
import { paymentApi } from './paymentApi';
import { requireCustomer } from './workflow';

const api = import.meta.env.VITE_PORTAL_API_URL || '/portal-api';
async function send<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${api}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || 'The email service is unavailable.');
  return result as T;
}

function automaticStatus(score: number | null, source: string) {
  if (score === null || source === 'unavailable' || score >= 60) return 'Awaiting Approval' as const;
  return score < 30 ? 'Approved' as const : 'Awaiting Verification' as const;
}

export const shipmentApi = {
  async list(userId: string) { return respond(db().shipments.filter(s => s.userId === userId)); },
  async create(draft: ShipmentDraft, user: User, submissionId: string): Promise<Shipment> {
    requireCustomer(user.id);
    draft = structuredClone(draft); user = structuredClone(user);
    if (!submissionId) throw new Error('A booking confirmation reference is required.');
    const payment = await paymentApi.pay(draft, user.id, submissionId);
    if (payment.status !== 'Paid' || payment.amount !== priceFor(draft).total) throw new Error('Payment was not confirmed. The shipment has not been submitted.');
    const existing = db().shipments.find(s => s.payment.reference === payment.reference);
    if (existing) {
      if (existing.payment.draftKey !== payment.draftKey) throw new Error('Booking details changed after payment. Start a new confirmation.');
      return respond(existing);
    }
    const id = `FS${Date.now().toString().slice(-9)}${crypto.randomUUID().slice(0, 3).toUpperCase()}`;
    const created = payment.paidAt;
    const risk = await scoreDraft(draft, user, id, created, db().shipments);
    const status = automaticStatus(risk.overall, risk.source);
    const automatic = status !== 'Awaiting Approval';
    const audit = automatic ? [{ id: crypto.randomUUID(), shipmentId: id, decision: status, admin: 'Automated checks',
      reason: status === 'Approved' ? 'Low-risk automatic allow' : 'Additional email verification required',
      notes: status === 'Approved' ? 'The recorded score was below the allow threshold. No administrator action was required.' : 'The recorded score fell in the step-up band. Shipment stays paused until the customer verifies their email.',
      at: created, riskSnapshot: structuredClone(risk) }] : [];
    const shipment: Shipment = { id, userId: user.id, created, expected: dateAfter(4), location: draft.sender.city,
      delivery: 'Created', status, ...(status === 'Approved' ? { approvedAt: created } : {}), draft: structuredClone(draft),
      price: priceFor(draft), risk, audit, payment, revision: 1 };
    const saved = await transaction(store => {
      const duplicate = store.shipments.find(s => s.payment.reference === payment.reference);
      if (duplicate) {
        if (duplicate.payment.draftKey !== payment.draftKey) throw new Error('Booking details changed after payment. Start a new confirmation.');
        return duplicate;
      }
      if (!store.payments.some(p => p.reference === payment.reference)) store.payments.push(payment);
      store.shipments.unshift(shipment);
      store.notices.unshift({ id: crypto.randomUUID(), userId: user.id,
        title: status === 'Approved' ? 'Shipment approved automatically' : status === 'Awaiting Verification' ? 'Email verification needed' : 'Shipment awaiting review',
        body: status === 'Approved' ? `Shipment ${id} passed the automatic checks and is approved to proceed. No admin approval was needed.` : status === 'Awaiting Verification' ? `Shipment ${id} needs the verification code sent to your email before it can proceed. No admin approval is needed after you verify.` : `Shipment ${id} needs an administrator to review its risk evidence before it can proceed.`,
        type: status === 'Awaiting Approval' ? 'reminder' : 'verification', at: created, read: false, shipmentId: id });
      return shipment;
    });
    if (status !== 'Awaiting Verification') {
      try { await send('/notifications/shipment', { shipment_id: id, email: user.email, status: status === 'Approved' ? 'Allowed' : 'Awaiting Approval' }); } catch { /* Payment and booking remain recorded; the UI shows the local inbox notice. */ }
    }
    return saved;
  },
  async resendStepUpCode(id: string, user: User) {
    requireCustomer(user.id);
    const shipment = db().shipments.find(s => s.id === id && s.userId === user.id);
    if (!shipment || shipment.status !== 'Awaiting Verification') throw new Error('This shipment does not need email verification.');
    return send<{ sent: boolean }>('/verification/send-code', { shipment_id: id, email: user.email });
  },
  async verifyStepUpCode(id: string, user: User, code: string): Promise<Shipment> {
    requireCustomer(user.id);
    const current = db().shipments.find(s => s.id === id && s.userId === user.id);
    if (!current || current.status !== 'Awaiting Verification') throw new Error('This shipment is not waiting for email verification.');
    await send('/verification/verify-code', { shipment_id: id, email: user.email, code });
    return transaction(store => {
      const shipment = store.shipments.find(s => s.id === id && s.userId === user.id);
      if (!shipment || shipment.status !== 'Awaiting Verification') throw new Error('This shipment has already changed. Refresh and try again.');
      const at = new Date().toISOString(); shipment.status = 'Approved'; shipment.approvedAt = at; shipment.revision++;
      shipment.audit.unshift({ id: crypto.randomUUID(), shipmentId: id, decision: 'Approved', admin: 'Email verification',
        reason: 'Step-up verification completed', notes: 'The customer entered the one-time code sent to their registered email. No administrator approval was required.', at,
        riskSnapshot: structuredClone(shipment.risk) });
      store.notices.unshift({ id: crypto.randomUUID(), userId: user.id, title: 'Shipment approved after verification',
        body: `Shipment ${id} passed the email step-up check and is approved to proceed.`, type: 'shipment', at, read: false, shipmentId: id });
      return shipment;
    });
  },
  quote: priceFor,
  initialDraft: emptyDraft,
};
