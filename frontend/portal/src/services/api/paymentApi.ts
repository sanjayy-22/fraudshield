import type { PaymentReceipt, ShipmentDraft } from '../../types';
import { priceFor } from './store';
import { requireCustomer } from './workflow';

type RazorpayResult = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string };
type RazorpayOptions = {
  key: string; order_id: string; amount: number; currency: string; name: string; description: string;
  prefill: { name: string; email: string; contact: string; method: 'card' | 'upi' | 'netbanking' | 'wallet' };
  handler: (result: RazorpayResult) => void;
  modal: { ondismiss: () => void };
  theme: { color: string };
};
type RazorpayCheckout = { open: () => void; on: (event: string, callback: (error: { error?: { description?: string } }) => void) => void };
declare global { interface Window { Razorpay?: new (options: RazorpayOptions) => RazorpayCheckout } }

const api = import.meta.env.VITE_PORTAL_API_URL || '/portal-api';
let sdkLoad: Promise<void> | undefined;
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${api}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || 'The payment service is unavailable.');
  return body as T;
}
function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (!sdkLoad) sdkLoad = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script'); script.src = 'https://checkout.razorpay.com/v1/checkout.js'; script.async = true;
    script.onload = () => window.Razorpay ? resolve() : reject(new Error('Razorpay Checkout did not load.'));
    script.onerror = () => reject(new Error('Could not load Razorpay Checkout. Check your connection and retry.'));
    document.head.appendChild(script);
  }).catch(error => { sdkLoad = undefined; throw error; });
  return sdkLoad;
}

export const paymentApi = {
  async pay(draft: ShipmentDraft, userId: string, submissionId: string): Promise<PaymentReceipt> {
    const user = requireCustomer(userId);
    const config = await request<{ enabled: boolean; key_id: string | null; currency: string }>('/payments/config');
    if (!config.enabled || !config.key_id) throw new Error('Razorpay is not set up yet. An administrator must add the server payment settings.');
    const order = await request<{ key_id?: string; order_id?: string; amount?: number; currency?: string; status?: 'Paid'; receipt?: { reference: string; amount: number; paid_at: string } }>('/payments/razorpay/order', {
      method: 'POST', body: JSON.stringify({ submission_id: submissionId, weight: draft.weight, length: draft.length,
        width: draft.width, height: draft.height, collection: draft.collection, protection: draft.protection,
        declared_value: draft.declaredValue, discount: draft.discount }),
    });
    if (order.status === 'Paid' && order.receipt) return { status: 'Paid', mode: 'razorpay', reference: order.receipt.reference,
      amount: order.receipt.amount, paidAt: order.receipt.paid_at, userId, submissionId, draftKey: JSON.stringify(draft),
      avs: 'Razorpay AVS applies when supported and enabled for the card.' };
    const orderId = order.order_id; const orderAmount = order.amount; const keyId = order.key_id; if (!orderId || !orderAmount || !keyId || keyId !== config.key_id || order.currency !== 'INR' || orderAmount !== priceFor(draft).total * 100) throw new Error('The payment amount did not match this shipment. Please retry.');
    await loadCheckout();
    return new Promise<PaymentReceipt>((resolve, reject) => {
      const Razorpay = window.Razorpay; if (!Razorpay) { reject(new Error('Razorpay Checkout did not load.')); return; } const checkout = new Razorpay({ key: keyId, order_id: orderId, amount: orderAmount,
        currency: 'INR', name: 'FraudShield', description: 'Shipment booking',
        prefill: { name: draft.sender.name || user.name, email: user.email, contact: draft.sender.phone || user.phone,
          method: draft.payment === 'Net Banking' ? 'netbanking' : draft.payment.toLowerCase() as 'card' | 'upi' | 'wallet' },
        theme: { color: '#236d68' },
        handler: result => {
          request<{ status: 'Paid'; mode: 'razorpay'; reference: string; amount: number; paid_at: string }>('/payments/razorpay/verify', {
            method: 'POST', body: JSON.stringify({ order_id: result.razorpay_order_id, payment_id: result.razorpay_payment_id, signature: result.razorpay_signature }),
          }).then(receipt => {
            if (receipt.status !== 'Paid' || receipt.amount !== orderAmount / 100 || receipt.reference !== result.razorpay_payment_id) throw new Error('Razorpay could not confirm this payment. The shipment was not submitted.');
            resolve({ status: 'Paid', mode: 'razorpay', reference: receipt.reference, amount: receipt.amount, paidAt: receipt.paid_at,
              userId, submissionId, draftKey: JSON.stringify(draft), avs: 'Razorpay AVS applies when supported and enabled for the card.' });
          }).catch(reject);
        },
        modal: { ondismiss: () => reject(new Error('Payment was closed before it completed. Your shipment was not submitted.')) },
      });
      checkout.on('payment.failed', error => reject(new Error(error.error?.description || 'Razorpay could not complete this payment.')));
      checkout.open();
    });
  },
};


