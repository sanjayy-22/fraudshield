import { Check, Package, Truck, Building2, MapPin, Home, ShieldCheck, Clock3 } from 'lucide-react';
import type { Shipment } from '../../types';
import { date } from '../ui/shared';
const shipping = [{ name: 'Picked Up', detail: 'Collected from the sender', icon: Package }, { name: 'In Transit', detail: 'Moving through the demo network', icon: Truck }, { name: 'Distribution Center', detail: 'At the destination facility', icon: Building2 }, { name: 'Out for Delivery', detail: 'On the final stretch', icon: MapPin }, { name: 'Delivered', detail: 'At its destination', icon: Home }];
export function TrackingTimeline({ shipment: s, compact = false }: { shipment: Shipment; compact?: boolean }) {
  const stages = [
    { name: 'Payment complete', detail: 'Razorpay payment received and booking submitted', icon: Package },
    { name: s.status === 'Approved' ? 'Checks complete' : s.status, detail: s.status === 'Approved' ? 'Approved to proceed' : s.status === 'Awaiting Verification' ? 'Enter the one-time code sent to your email' : 'Admin review is needed before shipping can proceed', icon: s.status === 'Approved' ? ShieldCheck : Clock3 },
    ...shipping,
  ];
  const delivery = s.delivery === 'Delayed' ? 1 : shipping.findIndex(t => t.name === s.delivery);
  const current = delivery < 0 ? 1 : delivery + 2;
  return <ol className={`tracking-timeline ${compact ? 'compact' : ''}`}>{stages.map((stage, i) => <li key={stage.name} className={i < current ? 'done' : i === current ? 'current' : 'future'}><span className="timeline-icon">{i < current ? <Check size={16}/> : <stage.icon size={17}/>}</span><div><strong>{stage.name}</strong><p>{stage.detail}</p>{i === 0 && <small>{date(s.created, true)}</small>}{i === 1 && s.approvedAt && <small>{date(s.approvedAt, true)}</small>}{i === current && i > 1 && <small>{s.location}</small>}</div>{i === current && <span className="timeline-now">Current</span>}</li>)}</ol>;
}
