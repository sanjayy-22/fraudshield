import { createContext, useContext, useState, type ReactNode } from 'react';
import type { User } from '../types';
import { authApi } from '../services/api/authApi';
const Context = createContext<{ user: User | null; setUser: (user: User | null) => void; logout: () => void } | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) { const [user, setUser] = useState<User | null>(() => authApi.current()); return <Context.Provider value={{ user, setUser, logout: () => { authApi.logout(); setUser(null); } }}>{children}</Context.Provider>; }
export function useAuth() { const c = useContext(Context); if (!c) throw new Error('AuthProvider missing'); return c; }
