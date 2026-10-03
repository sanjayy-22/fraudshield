# E5 — label-shuffle null (within TRANSFER)

Same features and model as E2 (with payment_type, single seed). 20 permutations of the training and
validation labels inside TRANSFER; test scored on true labels.

| | TRANSFER-scope test ROC-AUC |
|---|---:|
| real labels (seed 1) | 0.522 |
| shuffled labels: mean ± sd | 0.501 ± 0.013 |
| shuffled labels: min – max | 0.480 – 0.519 |
| empirical p-value (real ≤ null) | 0.048 |

A p-value well above 0.05 means the real-label model is indistinguishable from one trained on noise
inside TRANSFER.
