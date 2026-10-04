import { useEffect, useState } from 'react';
import { Sparkles, RefreshCw, Info, ListChecks, Calculator, ShieldCheck, BrainCircuit } from 'lucide-react';
import type { Shipment } from '../../types';
import { explanationApi, recordedExplanation, explanationPayload } from '../../services/api/explanationApi';
import { Spinner } from '../ui/shared';

const icons = { rule: ListChecks, calculation: Calculator, decision: ShieldCheck, model: BrainCircuit, limitation: Info };
const labels = { rule: 'Rule evidence', calculation: 'Score calculation', decision: 'Admin decision', model: 'Model evidence', limitation: 'Limitations' };

export function ShipmentExplanation({ shipment }: { shipment: Shipment }) {
  // A change of decision or evidence remounts the result, preventing old AI text flashing for a new revision.
  const fingerprint = JSON.stringify(explanationPayload(shipment));
  return <ExplanationResult key={fingerprint} shipment={shipment}/>;
}

function ExplanationResult({ shipment }: { shipment: Shipment }) {
  const [result, setResult] = useState(() => recordedExplanation(shipment));
  const [busy, setBusy] = useState(true); const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true; setBusy(true);
    explanationApi.get(shipment, attempt > 0).then(value => { if (active) setResult(value); })
      .catch(() => { if (active) setResult(recordedExplanation(shipment, 'Sign in as an administrator to request an AI explanation.')); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [attempt]);
  return <section className="panel explanation-panel" aria-labelledby="shipment-explanation-title">
    <div className="section-head"><div><p className="eyebrow"><Sparkles size={14}/>EXPLAINABLE AI</p><h2 id="shipment-explanation-title">Why this shipment received this score</h2><p className="muted">The reasons behind the score, and the recorded review decision.</p></div><button className="btn secondary small" disabled={busy} onClick={() => setAttempt(a => a + 1)}>{busy ? <Spinner/> : <RefreshCw size={15}/>} {busy ? 'Writing explanation…' : 'Refresh explanation'}</button></div>
    <div className="explanation-source" role="status"><span className={`explanation-source-label ${result.source === 'ai' && !busy ? 'ai' : ''}`}><Sparkles size={14}/>{busy ? 'Preparing Qwen explanation' : result.source === 'ai' ? 'Qwen explanation' : 'Recorded evidence summary'}</span><p>{busy ? 'The recorded evidence is available below while the AI writes its explanation.' : result.note}</p></div>
    <ol className="explanation-points">{result.points.map(point => { const Icon = icons[point.kind]; return <li key={point.evidence_id} className={`explanation-point ${point.kind}`}><span className="explanation-point-icon"><Icon size={18}/></span><div className="explanation-point-body"><div className="explanation-point-label"><small>{labels[point.kind]}</small>{point.impact && <span>{point.impact}</span>}</div><h3>{point.title}</h3><p>{point.explanation}</p>{result.source === 'ai' && point.fact !== point.explanation && <details><summary>View recorded evidence</summary><p>{point.fact}</p></details>}</div></li>; })}</ol>
    <div className="explanation-footer"><ShieldCheck size={15}/><span>A review aid based on the current record. Risk signals do not prove fraud.</span>{result.source === 'ai' && <small>{result.model}</small>}</div>
  </section>;
}
