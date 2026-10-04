import { useEffect, useState } from 'react';
import { Badge, Spinner } from '../ui/shared';
import type { Shipment } from '../../types';
import { customerStatus, isDispatched } from '../../services/api/workflow';
import { shipmentApi } from '../../services/api/shipmentApi';
import { useAuth } from '../../contexts/AuthContext';

export function ApprovalStatus({ shipment: original }: { shipment: Shipment }) {
  const { user } = useAuth();
  const [shipment, setShipment] = useState(original);
  const [code, setCode] = useState(''); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState(''); const [error, setError] = useState('');
  const shipped = isDispatched(shipment);
  useEffect(() => {
    setShipment(original);
    if (original.status !== 'Awaiting Verification' || !user) return;
    let active = true;
    const key = `fraudshield-code-sent-${original.id}`;
    const lastSent = Number(sessionStorage.getItem(key) || 0);
    if (lastSent && Date.now() - lastSent < 600_000) { setNotice(`A verification code was sent to ${user.email}.`); return; }
    setBusy(true); setError('');
    shipmentApi.resendStepUpCode(original.id, user).then(() => {
      sessionStorage.setItem(key, String(Date.now())); if (active) setNotice(`A verification code was sent to ${user.email}.`);
    }).catch(e => { if (active) setError((e as Error).message); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [original.id, original.status, user?.id]);
  async function resend() {
    if (!user) return; setBusy(true); setError(''); setNotice('');
    try { await shipmentApi.resendStepUpCode(shipment.id, user); sessionStorage.setItem(`fraudshield-code-sent-${shipment.id}`, String(Date.now())); setNotice(`A new code was sent to ${user.email}.`); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function verify(e: React.FormEvent) {
    e.preventDefault(); if (!user) return; setBusy(true); setError('');
    try { const updated = await shipmentApi.verifyStepUpCode(shipment.id, user, code); setShipment(updated); setNotice('Email verified. Your shipment is approved to proceed.'); setCode(''); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const text = shipment.status === 'Approved' ? shipped ? 'Shipping has started in the demo.' : 'Your shipment passed the required checks and is approved to proceed. No administrator approval was needed.'
    : shipment.status === 'Awaiting Verification' ? 'One extra email check is needed. Enter the code we sent to continue; an administrator does not need to approve this shipment.'
      : shipment.status === 'On Hold' ? 'Your booking needs additional review. Check your inbox for updates. Shipping is paused.'
        : shipment.status === 'Blocked' ? 'Your booking was blocked from shipping after review. Contact support for help; this status does not mean a refund was issued.'
          : 'Your payment is complete. An administrator will review the shipment risk evidence before it can proceed.';
  return <section className="approval-status" aria-live="polite"><div className="section-head"><h2>{customerStatus(shipment)}</h2><Badge tone={shipment.payment.status === 'Paid' ? 'approved' : 'blocked'}>Payment {shipment.payment.status.toLowerCase()} · {shipment.payment.mode === 'razorpay' ? 'Razorpay' : 'demo'}</Badge></div>
    <p>{text}</p>
    {shipment.status === 'Awaiting Verification' && <form className="step-up-form" onSubmit={verify}><label>Email verification code<input aria-label="Email verification code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code"/></label><div className="button-row"><button className="btn primary" disabled={busy || code.length !== 6}>{busy ? <Spinner/> : 'Verify and continue'}</button><button type="button" className="btn secondary" disabled={busy} onClick={resend}>Send code again</button></div></form>}
    {notice && <p className="success-text" role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}</p>}
    <ol className="approval-steps"><li className="complete">1. Payment complete</li><li className={shipment.status === 'Approved' ? 'complete' : shipment.status === 'Awaiting Verification' ? 'active' : 'active'}>2. {shipment.status === 'Approved' ? 'Checks complete' : shipment.status === 'Awaiting Verification' ? 'Email check' : shipment.status === 'Awaiting Approval' || shipment.status === 'On Hold' ? 'Admin review' : 'Review complete'}</li><li className={shipped ? 'complete' : ''}>3. {shipped ? 'Shipping started' : 'Shipping pending'}</li></ol>
    <small>Razorpay AVS is applied when enabled and supported by the card issuer. Shipment status updates appear in this browser.</small>
  </section>;
}
