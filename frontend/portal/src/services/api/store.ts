import type { User, Shipment, ShipmentDraft, Notice, Price, Risk, RiskLevel, ReviewStatus } from '../../types';

export const today = () => new Date().toISOString().slice(0, 10);
export const dateAfter = (days: number, from = new Date()) => { const date = new Date(from); date.setDate(date.getDate() + days); return date.toISOString(); };
const contact = (city: string, name: string) => ({ country: 'India', name, phone: '9000000000', email: `${name.split(' ')[0].toLowerCase()}@example.com`, address: '24, Lakeview Road', city, state: city === 'Chennai' ? 'Tamil Nadu' : city === 'Mumbai' ? 'Maharashtra' : 'Karnataka', pin: city === 'Chennai' ? '600028' : '400001' });
export const emptyDraft = (user?: User): ShipmentDraft => ({ sender: { ...contact(user?.city || 'Chennai', user?.name || 'Aarav Mehta'), email: user?.email || 'aarav@example.com', phone: user?.phone || '9000000000' }, receiver: { country: 'India', name: '', phone: '', email: '', address: '', city: '', state: '', pin: '' }, packaging: 'Box', length: 30, width: 20, height: 15, weight: 2.5, collection: 'Pickup', pickupAddress: '', pickupDate: today(), pickupTime: '10:00 AM – 12:00 PM', instructions: '', dropoff: '', category: 'Electronics', description: '', value: 2500, quantity: 1, protection: 'Basic', declaredValue: 2500, payment: 'UPI', discount: false });
export function priceFor(d: ShipmentDraft): Price {
  const shipping = Math.round(149 + Math.max(d.weight, d.length * d.width * d.height / 5000) * 70);
  const pickup = d.collection === 'Pickup' ? 79 : 0;
  const protection = d.protection === 'Additional' ? Math.round(Math.max(49, d.declaredValue * 0.01)) : 0;
  const discount = d.discount ? Math.min(100, Math.round(shipping * 0.1)) : 0;
  return { shipping, pickup, protection, discount, total: shipping + pickup + protection - discount };
}
export const riskLevel = (score: number): RiskLevel => score < 30 ? 'LOW' : score < 60 ? 'MEDIUM' : score < 80 ? 'HIGH' : 'CRITICAL';
// Demo-only, deterministic scoring. This is not the trained Python model.
// One centralized formula: 40% normalized rule score + 60% simulated model probability.
export function buildRisk(ai: number, flags: boolean[]): Risk {
  const catalog = [
    { name: 'New account', points: 10, description: 'Limited established shipping history.' },
    { name: 'Unusual shipment value', points: 15, description: 'Declared value is above this account’s usual range.' },
    { name: 'New device', points: 10, description: 'This device has not been verified on this account.' },
    { name: 'Multiple addresses', points: 5, description: 'Several recently added destinations need context.' },
  ];
  const factors = catalog.filter((_, i) => flags[i]);
  const ruleScore = factors.reduce((sum, f) => sum + f.points, 0);
  const overall = Math.round(0.4 * (ruleScore / 40 * 100) + 0.6 * ai);
  const shap = [...factors.map((f, i) => ({ name: f.name, value: [0.31, 0.22, 0.16, 0.09][i] })), { name: 'Established history', value: -0.05 }];
  return { overall, level: riskLevel(overall), ruleScore, ruleMax: 40, ai, factors, shap, model: 'LightGBM · simulated output' };
}
export const locations = ['Chennai', 'Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Pune', 'Kolkata', 'Coimbatore'];
export const dropoffs = [{ name: 'Adyar shipping studio', address: '12, LB Road, Adyar, Chennai', hours: '9 AM – 8 PM' }, { name: 'T. Nagar service point', address: '45, North Usman Road, Chennai', hours: '9 AM – 7 PM' }, { name: 'Velachery collection hub', address: '8, Main Road, Velachery, Chennai', hours: '8 AM – 9 PM' }];
type Store = { users: User[]; shipments: Shipment[]; notices: Notice[] };
const KEY = 'fraudshield-portal-v1';
function seed(): Store {
  const names = ['Aarav Mehta', 'Diya Nair', 'Rohan Kapoor', 'Ananya Rao', 'Vihaan Shah', 'Ishaan Das', 'Kavya Iyer', 'Arjun Menon', 'Meera Patel', 'Aditya Sen', 'Sana Ali', 'Dev Khanna', 'Nisha Joshi', 'Rehan Khan', 'Tara Bose', 'Kabir Sethi', 'Zoya Mirza', 'Neel Verma', 'Aditi Jain', 'Riya Bhat', 'Kunal Roy', 'Avni Gupta', 'Nikhil Suri', 'Leela Nair'];
  const users: User[] = names.map((name, i) => ({ id: `USR${String(i + 1).padStart(3, '0')}`, name, email: `${name.toLowerCase().replaceAll(' ', '.')}@example.com`, phone: `900000${String(i).padStart(4, '0')}`, city: locations[i % 8], company: i === 0 ? 'Studio Mehta' : `${name.split(' ')[0]} Studio`, joined: dateAfter(-400 + i * 15), role: 'USER' }));
  users[0].email = 'aarav@example.com';
  users.push({ id: 'ADM001', name: 'Priya Sharma', email: 'admin@example.com', phone: '9000009999', city: 'Chennai', company: 'FraudShield Operations', joined: dateAfter(-600), role: 'ADMIN' });
  const statuses: ReviewStatus[] = ['Suspicious', 'Under Review', 'On Hold', 'Approved', 'Approved', 'Blocked', 'Approved', 'Under Review'];
  const deliveries = ['In Transit', 'Created', 'Picked Up', 'Delivered', 'Out for Delivery', 'Created', 'Delivered', 'Delayed'] as const;
  const shipments: Shipment[] = Array.from({ length: 64 }, (_, i) => {
    const owner = users[i < 12 ? 0 : (i % 23) + 1];
    const band = i % 8;
    const d: ShipmentDraft = { ...emptyDraft(owner), sender: contact(locations[i % 8], owner.name), receiver: contact(locations[(i + 1) % 8], names[(i + 4) % 24]), description: ['Design samples and stationery', 'Camera equipment', 'Cotton apparel', 'Home decor'][i % 4], category: ['Documents', 'Electronics', 'Apparel', 'Home & Living'][i % 4], value: band === 0 ? 85000 : 1500 + i * 650, declaredValue: band === 0 ? 85000 : 1500 + i * 650, weight: 1.5 + (i % 6), protection: i % 3 === 0 ? 'Additional' : 'Basic', pickupDate: today() };
    const risk = band === 0 ? buildRisk(85, [true, true, true, true]) : band === 1 ? buildRisk(72, [true, true, true, false]) : band === 2 ? buildRisk(55, [false, true, true, false]) : band === 5 ? buildRisk(94, [true, true, true, true]) : band === 7 ? buildRisk(38, [false, true, false, false]) : buildRisk(9 + i % 12, [false, false, false, false]);
    const created = dateAfter(-Math.floor(i / 4));
    const id = `FS${84729103 + i}`;
    return { id, userId: owner.id, created, expected: dateAfter(3 - i % 6), location: `${d.receiver.city} sorting facility`, delivery: deliveries[band], status: statuses[band], draft: d, price: priceFor(d), risk, audit: ['Approved', 'Blocked', 'On Hold'].includes(statuses[band]) ? [{ id: `AUD${i}`, shipmentId: id, decision: statuses[band], admin: 'Priya Sharma', reason: statuses[band] === 'Approved' ? 'Verified customer' : statuses[band] === 'Blocked' ? 'Suspicious activity confirmed' : 'Other', notes: 'Demonstration review record. Evidence retained for follow-up.', at: dateAfter(-Math.floor(i / 4) + 0.01) }] : [] };
  });
  const notices: Notice[] = [
    { title: 'Your shipment is on its way', body: 'Your Chennai → Mumbai shipment has left the origin facility. Follow every step of its journey.', type: 'shipment', shipmentId: shipments[0].id },
    { title: 'A quick verification is needed', body: 'Please review the details of your latest shipment. Our team will contact you through your registered details.', type: 'verification', shipmentId: shipments[1].id },
    { title: 'Delivery taking a little longer', body: 'A local transit delay has affected your shipment. We will keep you updated.', type: 'delay', shipmentId: shipments[7].id },
    { title: 'Pickup reminder', body: 'Have your package sealed and ready for collection between 10 AM and 12 PM.', type: 'reminder', shipmentId: shipments[2].id },
    { title: 'Payment confirmed', body: 'Your demo payment has been received. Your receipt is available in shipment details.', type: 'payment', shipmentId: shipments[3].id },
    { title: 'Delivered, with care', body: 'Your parcel has arrived at its destination. Thank you for shipping with FraudShield.', type: 'shipment', shipmentId: shipments[3].id },
  ].map((n, i) => ({ ...n, type: n.type as Notice['type'], id: `MSG${i}`, userId: users[0].id, at: dateAfter(-i), read: i > 2 }));
  return { users, shipments, notices };
}
let memory: Store | undefined;
export function db(): Store {
  if (memory) return memory;
  try { const raw = localStorage.getItem(KEY); if (raw) memory = JSON.parse(raw); } catch { /* private browsing or old data */ }
  if (!memory?.users || !memory?.shipments || !memory?.notices) memory = seed();
  return memory;
}
export function save() { localStorage.setItem(KEY, JSON.stringify(db())); }
export async function respond<T>(value: T): Promise<T> { await new Promise(resolve => setTimeout(resolve, 160)); return structuredClone(value); }
