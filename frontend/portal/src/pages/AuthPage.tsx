import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Package, Check, Eye, EyeOff, LockKeyhole } from 'lucide-react';
import { Logo } from '../components/layout/AppLayout';
import { authApi } from '../services/api/authApi';
import { useAuth } from '../contexts/AuthContext';
import { Spinner } from '../components/ui/shared';

export function AuthPage({ admin = false, register = false }: { admin?: boolean; register?: boolean }) {
  const [name, setName] = useState(''); const [email, setEmail] = useState('');
  const [password, setPassword] = useState(''); const [inviteCode, setInviteCode] = useState('');
  const [deviceCode, setDeviceCode] = useState(''); const [deviceVerificationPending, setDeviceVerificationPending] = useState(false);
  const [visible, setVisible] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const { setUser } = useAuth(); const navigate = useNavigate();
  useEffect(() => { setEmail(''); setPassword(''); setError(''); setName(''); setInviteCode(''); setDeviceCode(''); setDeviceVerificationPending(false); authApi.cancelDeviceLogin(); }, [admin, register]);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      if (!register && deviceVerificationPending) {
        const user = await authApi.verifyDeviceLogin(deviceCode);
        setUser(user); navigate(admin ? '/admin/dashboard' : '/user/dashboard'); return;
      }
      if (!register) {
        const result = await authApi.beginLogin(email, password, admin ? 'ADMIN' : 'USER');
        if (result.verificationRequired) { setDeviceVerificationPending(true); setError(''); return; }
        setUser(result.user); navigate(admin ? '/admin/dashboard' : '/user/dashboard'); return;
      }
      const user = await authApi.register(name, email, password, admin ? 'ADMIN' : 'USER', inviteCode);
      setUser(user); navigate(admin ? '/admin/dashboard' : '/user/dashboard');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const accountLabel = admin ? 'admin account' : 'user account';
  const loginPath = admin ? '/admin/login' : '/login';
  const switchPath = register ? loginPath : admin ? '/login' : '/admin/login';
  const switchLabel = register ? `${admin ? 'Admin' : 'User'} login` : `${admin ? 'User' : 'Admin'} login`;
  return <div className={`auth-page ${admin ? 'admin-theme' : ''}`}>
    <div className="auth-story"><Logo/><span className="auth-kicker"><span className="live-dot"/>{admin ? 'ADMIN WORKSPACE' : 'SHIPMENT WORKSPACE'}</span>
      <h1>{admin ? <>Review each<br/>shipment with<br/><em>clear evidence.</em></> : <>Send a package.<br/>Follow it all<br/><em>the way.</em></>}</h1>
      <p>{admin ? 'Review shipment risk and manage decisions from one place.' : 'Book shipments, pay securely, and get clear updates along the way.'}</p>
      <div className="auth-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="art-package"><Package size={92} strokeWidth={1}/></div><span className="art-tag"><ShieldCheck size={18}/>Protected every step</span><span className="art-origin">CHENNAI <span>12.97° N</span></span><span className="art-destination">MUMBAI <span>19.07° N</span></span></div>
      <small>Thoughtfully connected. Securely delivered.</small>
    </div>
    <div className="auth-form-side"><div className="auth-top">{admin ? 'Sending a package?' : 'Reviewing shipments?'} <Link to={switchPath}>{switchLabel} <ArrowRight size={14}/></Link></div>
      <div className="auth-form-wrap"><span className="auth-form-icon">{admin ? <LockKeyhole/> : <Package/>}</span>
        <p className="eyebrow">{admin ? 'FRAUDSHIELD ADMIN' : 'FRAUDSHIELD SHIPPING'}</p>
        <h2>{register ? `Create ${accountLabel}` : `${admin ? 'Admin' : 'User'} login`}</h2>
        <p className="muted">{register ? `Enter your details to create a ${accountLabel}.` : admin ? 'Sign in to review shipments and manage decisions.' : 'Sign in to book and track your shipments.'}</p>
        <form onSubmit={submit} className="auth-form">
          {register && <label>Full name<input required value={name} onChange={e => setName(e.target.value)} placeholder="Your full name" autoComplete="name"/></label>}
          {!deviceVerificationPending && <label>Email address<input required type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email"/></label>}
          {register && admin && <label>Admin invite code<input required type="password" value={inviteCode} onChange={e => setInviteCode(e.target.value)} autoComplete="off"/></label>}
          {!deviceVerificationPending && <label>Password<div className="password-input"><input required minLength={6} type={visible ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} autoComplete={register ? 'new-password' : 'current-password'}/><button type="button" className="icon-btn" aria-label={visible ? 'Hide password' : 'Show password'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={17}/> : <Eye size={17}/>}</button></div></label>}
          {deviceVerificationPending && <><p className="muted">This device type is new for your account. Enter the code sent to {email} to finish signing in.</p><label>Email verification code<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={deviceCode} onChange={e => setDeviceCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code"/></label></>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button disabled={busy || (deviceVerificationPending && deviceCode.length !== 6)} className="btn primary full">{busy ? <Spinner/> : deviceVerificationPending ? 'Verify and sign in' : register ? `Create ${accountLabel}` : `${admin ? 'Admin' : 'User'} login`}{!busy && <ArrowRight size={17}/>}</button>
          {deviceVerificationPending && <button type="button" className="btn secondary full" onClick={() => { authApi.cancelDeviceLogin(); setDeviceVerificationPending(false); setDeviceCode(''); }}>Back to login</button>}
        </form>
        <div className="demo-auth-note"><Check size={17}/><span><strong>Local account storage.</strong> {register ? admin ? 'Admin accounts need an invite code from the system owner.' : 'Use an email address you can access for shipment updates.' : 'Enter the email and password for your account.'} Account data in this portal is stored in this browser.</span></div>
        <p className="auth-bottom">{register ? 'Already have an account?' : `Need to create a ${accountLabel}?`} <Link to={register ? loginPath : admin ? '/admin/register' : '/register'}>{register ? `${admin ? 'Admin' : 'User'} login` : `Create ${accountLabel}`}</Link></p>
      </div><p className="auth-fine">Interactive demonstration. Account data stays in this browser.</p>
    </div>
  </div>;
}
