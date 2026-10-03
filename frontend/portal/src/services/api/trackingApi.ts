import { db, respond } from './store';
export const trackingApi = { async get(id: string, userId: string) { const shipment = db().shipments.find(s => s.id.toUpperCase() === id.trim().toUpperCase() && s.userId === userId); if (!shipment) throw new Error('We could not find that tracking ID in your shipments. Check the ID and try again.'); return respond(shipment); } };
