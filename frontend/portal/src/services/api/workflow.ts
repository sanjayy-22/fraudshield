import type { ReviewFilter, Shipment } from '../../types';
import { authApi } from './authApi';

export function requireAdmin() { const user = authApi.current(); if (user?.role !== 'ADMIN') throw new Error('Sign in as an administrator to take this action.'); return user; }
export function requireCustomer(id: string) { const user = authApi.current(); if (!user || user.id !== id || user.role !== 'USER') throw new Error('Sign in to your customer account to submit this booking.'); return user; }
export function matchesReview(s: Shipment, tab: ReviewFilter | string) { return tab === 'All' || (tab === 'Suspicious' ? (s.risk.overall ?? 0) >= 60 && ['Awaiting Approval', 'On Hold'].includes(s.status) : s.status === tab); }
export function customerStatus(s: Shipment) { return s.status === 'Approved' ? s.delivery === 'Created' ? 'Approved to proceed' : s.delivery : s.status === 'Awaiting Verification' ? 'Email verification needed' : s.status; }
export function isDispatched(s: Shipment) { return Boolean(s.dispatchedAt) || s.delivery !== 'Created'; }
export function assertReviewable(s: Shipment, revision: number) {
  if (isDispatched(s)) throw new Error('Shipping has already started. The pre-shipment decision is now read-only.');
  if (s.revision !== revision) throw new Error('This booking changed while you were reviewing it. Refresh and review the latest details.');
}
export function assertCanDispatch(s: Shipment) {
  if (s.status !== 'Approved' || !s.approvedAt) throw new Error('An administrator must approve this booking before shipping.');
  if (s.payment.status !== 'Paid') throw new Error('Payment must be complete before shipping.');
  if (s.risk.source === 'unavailable') throw new Error('Risk scoring must be available before shipping.');
}
