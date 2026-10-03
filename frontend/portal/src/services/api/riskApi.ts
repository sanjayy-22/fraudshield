import type { ShipmentDraft, User } from '../../types';
import { buildRisk, db, respond } from './store';
export function scoreDraft(d: ShipmentDraft, user: User) {
  const newAccount = Date.now() - new Date(user.joined).getTime() < 30 * 86400000;
  const highValue = d.value >= 50000;
  // Scenario fixtures belong here, never in presentation components.
  // High value creates a demonstrative multi-signal scenario, not a real fraud judgment.
  return buildRisk(highValue ? 85 : newAccount ? 36 : 12, [newAccount || highValue, highValue, highValue, highValue]);
}
export const riskApi = { async get(id: string) { const s = db().shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.'); return respond(s.risk); } };
