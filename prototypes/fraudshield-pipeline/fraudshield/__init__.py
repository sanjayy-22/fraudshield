"""FraudShield pipeline prototype — end-to-end booking-time fraud screening.

    features (point-in-time store) → rules ⊕ calibrated GBM ⊕ drift ⊕ graph
    → conformal uncertainty → cost-sensitive decision → audit ledger → explanation
"""
__version__ = "0.1.0"
