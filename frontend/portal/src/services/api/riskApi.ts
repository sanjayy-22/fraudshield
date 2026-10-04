import type { ShipmentDraft, User, Shipment, Risk } from '../../types';
import { buildRisk, db, respond } from './store';

type ModelResponse = { booking_id: string; source: string; probability: number; model_version: string; scored_at: string; shap: { name: string; value: number }[]; assumptions: string[]; missing_features: string[]; unknown_categories: string[] };

export async function scoreDraft(d: ShipmentDraft, user: User, id: string, created: string, history: Shipment[]): Promise<Risk> {
  const prior = history.filter(s => s.userId === user.id && s.id !== id && s.created < created);
  const newAccount = new Date(created).getTime() - new Date(user.joined).getTime() < 30 * 86400000;
  const averageValue = prior.length ? prior.reduce((sum, s) => sum + s.draft.value, 0) / prior.length : 0;
  const highValue = d.value >= 50000 && (!averageValue || d.value > 3 * averageValue);
  const recentDestinations = new Set(prior.filter(s => new Date(created).getTime() - new Date(s.created).getTime() <= 7 * 86400000).map(s => s.draft.receiver.city.toLowerCase()));
  recentDestinations.add(d.receiver.city.toLowerCase());
  const flags = [newAccount, highValue, false, recentDestinations.size >= 4];
  const context = { account_age_days: Math.max(0, (new Date(created).getTime() - new Date(user.joined).getTime()) / 86400000), contents_value: d.value, prior_average_value: averageValue, prior_bookings: prior.length, recent_destination_count: recentDestinations.size };
  const base = { ...buildRisk(0, flags), context };
  // Never invent a new-device signal or translate UPI into DataCo's TRANSFER category.
  try {
    const response = await fetch(`${import.meta.env.VITE_PORTAL_API_URL || '/portal-api'}/score`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(12000),
      body: JSON.stringify({ booking_id: id, created, value: d.value, quantity: d.quantity, category: d.category,
        sender_country: d.sender.country, receiver_country: d.receiver.country, receiver_city: d.receiver.city,
        history: prior.slice(0, 1000).map(s => ({ created: s.created, value: s.draft.value, city: s.draft.receiver.city, country: s.draft.receiver.country })) }),
    });
    if (!response.ok) throw new Error('The trained model is not available. Keep the booking pending and retry scoring.');
    const result: ModelResponse = await response.json();
    if (result.booking_id !== id || result.source !== 'trained' || !Number.isFinite(result.probability) || result.probability < 0 || result.probability > 1 || !result.model_version || !Array.isArray(result.shap) || result.shap.some(s => !Number.isFinite(s.value) || typeof s.name !== 'string') || !Array.isArray(result.assumptions) || !Array.isArray(result.missing_features) || !Array.isArray(result.unknown_categories)) throw new Error('The model returned an invalid score. Keep the booking pending.');
    const scored = buildRisk(result.probability * 100, flags);
    return { ...scored, context, ai: Math.round(result.probability * 10000) / 100, source: 'trained', model: result.model_version, shap: result.shap, scoredAt: result.scored_at, assumptions: result.assumptions, missingFeatures: [...result.missing_features, ...result.unknown_categories] };
  } catch (e) {
    return { ...base, overall: null, ai: null, level: 'UNAVAILABLE', shap: [], source: 'unavailable', model: 'Score unavailable', error: e instanceof Error && e.name === 'TimeoutError' ? 'Model scoring timed out. Keep the booking pending and retry.' : (e as Error).message || 'Model scoring unavailable.' };
  }
}
export const riskApi = { async get(id: string) { const s = db().shipments.find(s => s.id === id); if (!s) throw new Error('Shipment not found.'); return respond(s.risk); } };
