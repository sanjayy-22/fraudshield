import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, ShieldCheck, Clock3, Ban, CheckCircle2, Truck, RefreshCw } from 'lucide-react';
import { adminApi } from '../services/api/adminApi';
import { userApi } from '../services/api/userApi';
import { isDispatched } from '../services/api/workflow';
import { PageHeading, useAsync, Loading, ErrorState, Badge, money, date, Modal, Spinner, useToast } from '../components/ui/shared';
import { RiskScoreCard, RiskFactorList, RiskFactorChart } from '../components/admin/RiskComponents';
import { UserHistory, AccountConnections } from '../components/admin/UserHistory';
import { DecisionModal } from '../components/admin/DecisionModal';
import { TrackingTimeline } from '../components/shipment/TrackingTimeline';
import { ShipmentExplanation } from '../components/admin/ShipmentExplanation';
import type { ReviewStatus, Shipment } from '../types';

export function PackageReview() {
  const { id } = useParams();
  const { data, loading, error, reload, setData } = useAsync(async () => {
    const shipment = await adminApi.get(id!);
    return { shipment, user: await userApi.get(shipment.userId), history: await userApi.history(shipment.userId) };
  }, [id]);
  const [action, setAction] = useState<{ action: ReviewStatus; shipment: Shipment } | null>(null);
  const [dispatchRevision, setDispatchRevision] = useState<number | null>(null);
  const [busy, setBusy] = useState(false); const [actionError, setActionError] = useState(''); const toast = useToast();
  if (loading) return <Loading/>;
  if (error || !data) return <ErrorState message={error} retry={reload}/>;
  const { shipment: s, user, history } = data; const shipped = isDispatched(s);
  const updated = (shipment: Shipment) => setData({ ...data, shipment, history: history.map(h => h.id === shipment.id ? shipment : h) });
  async function retryScore() {
    setBusy(true); setActionError('');
    try { updated(await adminApi.retryScore(s.id, s.revision)); toast('Saved model score updated. Previous evidence is retained.'); }
    catch (e) { setActionError((e as Error).message); } finally { setBusy(false); }
  }
  return <>
    <Link className="back-link" to="/admin/packages/pending"><ArrowLeft size={15}/>Back to approval queue</Link>
    <PageHeading eyebrow="PRE-SHIPMENT REVIEW" title={s.id} description={`Submitted ${date(s.created, true)} Â· ${s.draft.sender.city} â†’ ${s.draft.receiver.city}`}><Badge>{s.status}</Badge><Badge tone="approved">Payment: {s.payment.status} Â· demo</Badge></PageHeading>
    <div className="review-notice"><ShieldCheck size={18}/><span>{shipped ? 'Dispatch has been simulated. Pre-shipment decisions are now read-only.' : s.status === 'Approved' ? 'Approved to proceed after the required checks. Dispatch has not started.' : s.status === 'Awaiting Verification' ? 'Waiting for the customer to enter the emailed verification code.' : 'Shipping is paused until an administrator reviews the payment, shipment details, and risk evidence.'}</span></div>
    <ShipmentExplanation shipment={s}/>
    <div className="investigation-grid">
      <section className="panel investigation-panel"><div className="section-head"><h2>Shipment & payment</h2></div><div className="investigation-body">
        <div className="package-route"><span>{s.draft.sender.city}</span><ArrowRight size={18}/><span>{s.draft.receiver.city}</span></div>
        {[['Sender', s.draft.sender], ['Receiver', s.draft.receiver]].map(([label, contact]) => { const c = contact as typeof s.draft.sender; return <div className="contact-block" key={String(label)}><small>{String(label).toUpperCase()}</small><strong>{c.name}</strong><p>{c.address}<br/>{c.city}, {c.state}, {c.pin}, {c.country}<br/>{c.phone}<br/>{c.email}</p></div>; })}
        <dl className="definition-list">
          {[
            ['Customer', `${user.name} Â· ${user.email}`], ['Category', s.draft.category], ['Contents', s.draft.description],
            ['Packaging / quantity', `${s.draft.packaging} / ${s.draft.quantity}`], ['Dimensions / weight', `${s.draft.length} Ã— ${s.draft.width} Ã— ${s.draft.height} cm / ${s.draft.weight} kg`],
            ['Contents value', money(s.draft.value)], ['Declared value', money(s.draft.declaredValue)], ['Protection', s.draft.protection],
            ['Collection', s.draft.collection], ['Collection location', s.draft.collection === 'Pickup' ? s.draft.pickupAddress : s.draft.dropoff],
            ['Requested pickup', s.draft.collection === 'Pickup' ? `${s.draft.pickupDate} Â· ${s.draft.pickupTime}` : 'Drop-off after approval'],
            ['Instructions', s.draft.instructions || 'None'], ['Payment method', s.draft.payment], ['Paid amount', money(s.payment.amount)],
            ['Payment reference', s.payment.reference], ['Paid at', new Date(s.payment.paidAt).toLocaleString('en-IN')],
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl><p className="field-hint">Payment reference ({s.payment.mode}): {s.payment.reference}. This demo does not book a real carrier.</p>
        <h3 className="form-subheading">Shipment timeline</h3><TrackingTimeline shipment={s} compact/>
      </div></section>
      <div className="risk-analysis-column">
        <section className="panel investigation-panel"><div className="section-head"><h2>Risk analysis</h2><span className="micro-label">{s.risk.source === 'trained' ? 'SAVED MODEL' : s.risk.source === 'unavailable' ? 'UNAVAILABLE' : 'SAMPLE'}</span></div><div className="investigation-body">
          <RiskScoreCard risk={s.risk}/><p className="field-hint">{s.risk.model}{s.risk.scoredAt && ` Â· ${new Date(s.risk.scoredAt).toLocaleString('en-IN')}`}</p>
          {s.risk.error && <p role="alert" className="form-error">{s.risk.error}</p>}
          {!shipped && s.status !== 'Approved' && <button className="btn secondary" disabled={busy} onClick={retryScore}>{busy ? <Spinner/> : <RefreshCw size={15}/>} {s.risk.source === 'simulated' ? 'Score sample with saved model' : 'Retry model scoring'}</button>}
          <h3 className="form-subheading">Rule signals</h3><RiskFactorList risk={s.risk}/>
          {s.risk.assumptions && <details className="model-details"><summary>Model limitations & input coverage</summary><ul>{s.risk.assumptions.map(a => <li key={a}>{a}</li>)}</ul><p>Missing or unknown fields: {s.risk.missingFeatures?.join(', ') || 'None'}.</p></details>}
        </div></section>
        <section className="panel investigation-panel"><div className="section-head"><h2>What influenced the model?</h2></div><div className="investigation-body"><RiskFactorChart risk={s.risk}/></div></section>
      </div>
      <div><section className="panel investigation-panel"><div className="section-head"><h2>Customer history</h2></div><div className="investigation-body"><UserHistory user={user} shipments={history}/></div></section><section className="panel investigation-panel"><div className="section-head"><h2>Account context</h2></div><div className="investigation-body"><p className="field-hint">Device and payment connections below are illustrative sample data, not evidence collected from this booking.</p><AccountConnections userId={user.id}/></div></section></div>
    </div>
    <section className="panel audit-panel"><div className="section-head"><h2>Decision history</h2><span className="muted">{s.audit.length} recorded actions</span></div>{s.audit.length ? <div className="audit-list">{s.audit.map(a => <article key={a.id}><span className="audit-icon"><ShieldCheck size={17}/></span><div><div><Badge>{a.decision}</Badge><strong>{a.reason}</strong></div><p>{a.notes || 'No additional notes.'}</p><small>{a.admin} Â· {new Date(a.at).toLocaleString('en-IN')}</small>{a.riskSnapshot && <details><summary>Risk evidence at this action</summary><p>{a.riskSnapshot.model} Â· ML {a.riskSnapshot.ai ?? 'unavailable'}% Â· overall {a.riskSnapshot.overall ?? 'unavailable'}/100 Â· {a.riskSnapshot.source}</p><ul>{a.riskSnapshot.factors.map(f => <li key={f.name}>{f.name}: {f.description}</li>)}</ul></details>}</div></article>)}</div> : <p className="no-audit">No decision yet. Review the evidence before releasing this shipment.</p>}</section>
    {actionError && <p className="form-error" role="alert">{actionError}</p>}
    <div className="decision-bar"><div><ShieldCheck size={21}/><span><strong>{shipped ? 'Shipping has started in the demo.' : 'Customer email verification is required before this shipment can proceed.'}</strong><small>{s.risk.source === 'unavailable' ? 'Retry scoring to enable approval.' : 'A risk score alone does not establish fraud.'}</small></span></div><div className="button-row">
      <button className="btn secondary" disabled={busy || shipped || s.status === 'On Hold'} onClick={() => setAction({ action: 'On Hold', shipment: s })}><Clock3 size={16}/>On hold</button>
      <button className="btn danger-outline" disabled={busy || shipped || s.status === 'Blocked'} onClick={() => setAction({ action: 'Blocked', shipment: s })}><Ban size={16}/>Block</button>
      <button className="btn primary" disabled={busy || shipped || s.status === 'Approved' || s.status === 'Awaiting Verification' || s.payment.status !== 'Paid' || s.risk.source === 'unavailable'} onClick={() => setAction({ action: 'Approved', shipment: s })}><CheckCircle2 size={16}/>Approve</button>
      {s.status === 'Approved' && !shipped && <button className="btn primary" disabled={busy} onClick={() => { setActionError(''); setDispatchRevision(s.revision); }}><Truck size={16}/>Simulate dispatch</button>}
    </div></div>
    {action && <DecisionModal shipment={action.shipment} action={action.action} close={() => setAction(null)} done={result => { updated(result); setAction(null); }}/ >}
    {dispatchRevision !== null && <Modal title="Dispatch this approved shipment?" close={() => !busy && setDispatchRevision(null)}><p>This advances the demo to Picked Up. No real carrier will be contacted.</p>{actionError && <p className="form-error" role="alert">{actionError}</p>}<div className="button-row end"><button className="btn secondary" disabled={busy} onClick={() => setDispatchRevision(null)}>Cancel</button><button className="btn primary" disabled={busy} onClick={async () => { setBusy(true); setActionError(''); try { updated(await adminApi.dispatch(s.id, dispatchRevision)); setDispatchRevision(null); toast('Dispatch simulated after admin approval.'); } catch (e) { setActionError((e as Error).message); } finally { setBusy(false); } }}>{busy && <Spinner/>}Confirm dispatch</button></div></Modal>}
  </>;
}



