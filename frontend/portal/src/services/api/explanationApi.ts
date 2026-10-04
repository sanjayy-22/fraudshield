import type { ExplanationPoint, Shipment, ShipmentExplanation } from '../../types';
import { requireAdmin, isDispatched } from './workflow';

const reasons = ['Verified customer', 'Risk factors resolved', 'Additional verification completed', 'Suspicious activity confirmed', 'Other'];
export function explanationPayload(s: Shipment) {
  const decision = s.audit.find(a => a.decision === s.status);
  return { booking_id: s.id, revision: s.revision, status: s.status, payment_status: s.payment.status,
    dispatched: isDispatched(s), decision_reason: decision ? reasons.includes(decision.reason) ? decision.reason : 'Other' : null,
    risk: { overall: s.risk.overall, ai: s.risk.ai, rule_score: s.risk.ruleScore, rule_max: s.risk.ruleMax,
      source: s.risk.source, factors: s.risk.factors.map(f => ({ name: f.name, points: f.points })),
      shap: s.risk.shap.slice(0, 6).map(f => ({ name: f.name, value: f.value })), context: s.risk.context || null } };
}

// Always available, even if the explanation server or provider is offline.
export function recordedExplanation(s: Shipment, note = 'Showing the recorded evidence while Qwen prepares an explanation.'): ShipmentExplanation {
  const r = s.risk; const payload = explanationPayload(s);
  const point = (id: string, kind: ExplanationPoint['kind'], title: string, text: string, impact: string | null = null): ExplanationPoint => ({ evidence_id: id, kind, title, explanation: text, fact: text, impact });
  const status = s.status === 'Awaiting Approval'
    ? r.overall === null ? 'The risk score is unavailable, so an administrator needs to review this shipment before it can proceed.' : `The recorded risk score is ${r.overall}/100. Scores of 60 or above need administrator review before the shipment can proceed.`
    : s.status === 'Awaiting Verification'
      ? 'This shipment needs the one-time email code before it can proceed. Successful verification approves it automatically; no administrator approval is needed.'
    : `An administrator marked this booking ${s.status.toLowerCase()}. Recorded reason: ${payload.decision_reason || 'not available'}. This decision does not change its risk score or establish whether fraud occurred.`;
  const points = [point('status', 'decision', s.status === 'Awaiting Approval' ? 'Waiting for admin approval' : s.status === 'Awaiting Verification' ? 'Email verification required' : `${s.status} by an administrator`, status),
    point('score', 'calculation', r.overall === null ? 'Risk score unavailable' : 'How the score adds up', r.overall === null || r.ai === null
      ? 'The model score is unavailable, so the combined score cannot be calculated. Approval must wait for successful scoring.'
      : `40% of the normalized rule score (${r.ruleScore}/${r.ruleMax}) contributes ${(40 * r.ruleScore / r.ruleMax).toFixed(2)} points. 60% of the ML score (${r.ai}%) contributes approximately ${(r.ai * .6).toFixed(2)} points. The recorded rounded score is ${r.overall}/100 (${r.level}). Scores of 60 or above appear in Suspicious while awaiting approval or on hold.`, r.overall === null ? null : `${r.overall}/100`)];
  if (!r.factors.length) points.push(point('rules:none', 'rule', 'No configured rules matched', 'No configured rule added points. This does not mean that all possible fraud checks passed.'));
  r.factors.forEach((f, index) => points.push(point(`rule:${index}`, 'rule', f.name, `${r.source === 'simulated' ? 'Sample rule matched' : 'Rule matched'}: ${f.description} It adds ${f.points} rule points.`, `+${f.points} rule points`)));
  [...r.shap].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 2).forEach((f, index) => {
    const direction = f.value > 0 ? 'raises model risk' : f.value < 0 ? 'lowers model risk' : 'has no model impact';
    points.push(point(`model:${index}`, 'model', `Model factor: ${f.name}`, `${r.source === 'simulated' ? 'Sample contribution' : 'Recorded model contribution'}: ${f.name} ${direction}. ${f.name.includes('(unknown)') ? 'This input is unknown and is not a verified customer fact. ' : ''}Model contributions are not additional rule points.`, direction));
  });
  points.push(point('limits', 'limitation', 'What this evidence cannot confirm', `${r.source === 'simulated' ? 'This is seeded sample evidence, not observed facts about a real customer.' : 'The DataCo model is not validated for these shipping inputs. Device, identity, and bank verification checks are not collected by this portal.'} Payment is ${s.payment.status.toLowerCase()} in the demo; this does not establish a real bank payment.`));
  return { booking_id: s.id, revision: s.revision, source: 'template', model: null, prompt_version: 'portal-explanation-v1', generated_at: new Date().toISOString(), note, points };
}

const cache = new Map<string, { until: number; result: ShipmentExplanation }>();
const pending = new Map<string, Promise<ShipmentExplanation>>();
export const explanationApi = {
  async get(s: Shipment, refresh = false): Promise<ShipmentExplanation> {
    requireAdmin();
    const payload = explanationPayload(s); const key = JSON.stringify(payload);
    const saved = cache.get(key); if (!refresh && saved && saved.until > Date.now()) return saved.result;
    if (pending.has(key)) return pending.get(key)!;
    const task = (async () => {
      let result: ShipmentExplanation;
      try {
        const response = await fetch(`${import.meta.env.VITE_PORTAL_API_URL || '/portal-api'}/explain${refresh ? '?refresh=true' : ''}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: key, signal: AbortSignal.timeout(32000),
        });
        if (!response.ok) throw new Error('Explanation unavailable');
        result = await response.json();
        const kinds = ['decision', 'calculation', 'rule', 'model', 'limitation'];
        if (result.booking_id !== s.id || result.revision !== s.revision || !['ai', 'template'].includes(result.source)
          || typeof result.note !== 'string' || !Array.isArray(result.points) || !result.points.length || result.points.length > 10
          || result.points.some(p => !kinds.includes(p.kind) || typeof p.evidence_id !== 'string' || typeof p.title !== 'string' || typeof p.explanation !== 'string' || typeof p.fact !== 'string' || !(p.impact === null || typeof p.impact === 'string')))
          throw new Error('Invalid explanation response');
      } catch {
        result = recordedExplanation(s, 'The AI explanation service is unavailable. These points explain the recorded score and decision; you can retry.');
      }
      cache.set(key, { until: Date.now() + (result.source === 'ai' ? 600000 : 20000), result });
      while (cache.size > 50) cache.delete(cache.keys().next().value!);
      return result;
    })();
    pending.set(key, task);
    try { return await task; } finally { pending.delete(key); }
  },
};
