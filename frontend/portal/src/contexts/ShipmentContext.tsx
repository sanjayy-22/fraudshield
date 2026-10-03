import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import type { ShipmentDraft } from '../types';
import { shipmentApi } from '../services/api/shipmentApi';
import { useAuth } from './AuthContext';
const Context = createContext<{ draft: ShipmentDraft; update: (changes: Partial<ShipmentDraft>) => void; reset: () => void } | null>(null);
export function ShipmentProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth(); const key = `fraudshield-draft-${user!.id}`;
  const [draft, setDraft] = useState<ShipmentDraft>(() => { try { const saved = sessionStorage.getItem(key); if (saved) return { ...shipmentApi.initialDraft(user!), ...JSON.parse(saved) }; } catch {} return shipmentApi.initialDraft(user!); });
  useEffect(() => { sessionStorage.setItem(key, JSON.stringify(draft)); }, [draft, key]);
  return <Context.Provider value={{ draft, update: changes => setDraft(d => ({ ...d, ...changes })), reset: () => setDraft(shipmentApi.initialDraft(user!)) }}>{children}</Context.Provider>;
}
export function useShipment() { const c = useContext(Context); if (!c) throw new Error('ShipmentProvider missing'); return c; }
