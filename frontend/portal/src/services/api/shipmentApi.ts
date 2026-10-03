import type { Shipment, ShipmentDraft, User } from '../../types';
import { db, respond, save, priceFor, dateAfter, emptyDraft } from './store';
import { scoreDraft } from './riskApi';
export const shipmentApi = {
  async list(userId: string) { return respond(db().shipments.filter(s => s.userId === userId)); },
  async create(draft: ShipmentDraft, user: User): Promise<Shipment> {
    const risk = scoreDraft(draft, user);
    const id = `FS${Date.now().toString().slice(-9)}${crypto.randomUUID().slice(0, 3).toUpperCase()}`;
    const shipment: Shipment = { id, userId: user.id, created: dateAfter(0), expected: dateAfter(4), location: draft.sender.city, delivery: 'Created', status: risk.overall >= 60 ? 'Suspicious' : 'Under Review', draft: structuredClone(draft), price: priceFor(draft), risk, audit: [] };
    db().shipments.unshift(shipment);
    db().notices.unshift({ id: crypto.randomUUID(), userId: user.id, title: 'Shipment created', body: `Your ${draft.sender.city} → ${draft.receiver.city} booking is ready. Track it with ${id}. Payment was simulated; no money was charged.`, type: 'shipment', at: dateAfter(0), read: false, shipmentId: id });
    save(); return respond(shipment);
  },
  quote: priceFor,
  initialDraft: emptyDraft,
};
