import type { ReviewStatus } from '../../types';
import { db, respond, save } from './store';
export const adminApi = {
  async list() { return respond(db().shipments); },
  async get(id: string) { const s = db().shipments.find(s => s.id === id); if (!s) throw new Error('This shipment could not be found.'); return respond(s); },
  async decide(id: string, decision: ReviewStatus, admin: string, reason: string, notes: string) {
    if (!reason || (reason === 'Other' && !notes.trim())) throw new Error('Select a reason and add a note when choosing Other.');
    const s = db().shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.');
    s.status = decision;
    s.audit.unshift({ id: crypto.randomUUID(), shipmentId: id, decision, admin, reason, notes: notes.trim(), at: new Date().toISOString() });
    db().notices.unshift({ id: crypto.randomUUID(), userId: s.userId, title: `Shipment update: ${decision}`, body: `Your booking ${id} has been ${decision === 'Approved' ? 'approved for shipping' : decision === 'On Hold' ? 'placed on hold for additional review' : 'blocked following review'}. Contact support through your usual channel for help.`, type: 'verification', at: new Date().toISOString(), read: false, shipmentId: id });
    save(); return respond(s);
  },
  async audit() { return respond(db().shipments.flatMap(s => s.audit).sort((a, b) => b.at.localeCompare(a.at))); },
};
