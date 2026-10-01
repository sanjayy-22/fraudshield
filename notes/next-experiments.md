# Next experiments (post-convergence)

Ordered by expected information per hour of work.

1. **Cost-parameter sensitivity sweep.** Re-run the replay over a grid of `churn_if_blocked`
   (1–10 %), `stepup_friction`, `fraud_pass` (0.1–0.5) and report where the cost-sensitive
   policy stops dominating the threshold policies. This is the first question a fraud manager
   will ask. (`prototypes/fraudshield-pipeline/demo.py`, loop over `CostParams`.)

2. **Harder simulator.** Add: mimicry attacks that reuse the victim's own device *and* card and
   ship to a plausible new city; slow-burn episodes spread over weeks; legitimate account
   migrations (new device + new card + new address on the same day, genuinely); address text
   with typos so entity resolution is needed. Target: stealthy-scenario recall well below 0.7 so
   the graph and quarantine features have room to show.

3. **Multi-booking decisions.** A velocity burst is one decision problem, not eight. Score the
   *episode* (all open bookings of a shipper in the last N hours) and let the policy hold the whole
   batch — the expected loss L becomes the sum over the batch and step-up amortises.

4. **Decayed profiles and counters.** Exponential decay (half-life ~60 days) on profile counts
   and on component fraud counts, so legitimate behavioural drift (a business that starts
   shipping electronics) stops looking suspicious after a while and old rings fade.

5. **Stacking vs feature-level fusion.** Compare the current single GBM with a stacked
   meta-learner over four detector scores; measure whether stacking buys robustness when one
   detector's inputs are missing (feature-store outage).

6. **Conformal alpha vs analyst budget.** Sweep α (0.05–0.3) and review capacity; plot fraud
   caught by analysts per review-hour. Choose α from the curve rather than by convention.

7. **Address entity resolution.** Mule addresses in reality vary by spelling; add a normaliser
   (libpostal-style tokenisation + geohash) before the graph keys. Measure recall change.

8. **Real LLM behind the verifier.** Wire an API, measure rejection rate of the verifier on 200
   narratives, and the analyst-rated usefulness of LLM vs template text. Try a "customer message"
   generator constrained to never reveal features (verifier rule: no feature label tokens).

9. **Graph learning (tier 2).** Node2vec / GraphSAGE embeddings of the entity graph computed in
   batch and served as features; compare with the counter features. Expected: marginal gain,
   significant serving complexity — worth an appendix slide, not the main pitch.

10. **LLM-as-judge with retrieval (tier 2, high risk).** For HOLD cases only: retrieve the
    shipper's last 20 bookings + the evidence pack, ask the LLM for a structured second opinion
    with a confidence, and measure agreement with analysts. Never on the synchronous path.

11. **Adversarial loop.** Let a second script play the fraudster: it observes which of its
    bookings were blocked and mutates its next episode (fewer bookings, business hours, own card).
    Track detection over rounds — the strongest demonstration of "continuous learning" available
    without real data.
