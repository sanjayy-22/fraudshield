# Experiment D — grounded explanations, verifier, counterfactuals

7/7 generated narratives passed the grounding verifier.

Adversarial check — a deliberately hallucinated narrative:

> Booking B020976 was flagged because the shipper booked 14 parcels to mule_9_99 in 2 hours and the card was 3 days old.

Verifier: REJECTED — number 14 not in evidence; number 9 not in evidence; identifier mule_9_99 not in evidence

## Cases

### dormant_reactivation — B020976 (true label: FRAUD)

> Booking B020976 by shipper S0176 scores a fraud probability of 1.00 (decision threshold 0.00), based on 16 prior bookings from this shipper. Main drivers — payment instrument age: 0.4 h old; behavioural drift vs own history: 6.9 (typical ≈ 4); other shippers on this device (30 d): 4; confirmed-fraud shipments to this address: 1. Policy rules triggered: R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper). Linked infrastructure: destination has 1 confirmed-fraud shipments, device 2, payment instrument 0.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "log_pay_age_min",
   "label": "payment instrument age",
   "value": 3.1654750481410856,
   "display": "0.4 h old",
   "contribution": 4.354794797582569
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 6.911700032572661,
   "display": "6.9 (typical \u2248 4)",
   "contribution": 3.050316342168535
  },
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 4.0,
   "display": "4",
   "contribution": 2.844258332388019
  },
  {
   "feature": "dest_fraud",
   "label": "confirmed-fraud shipments to this address",
   "value": 1.0,
   "display": "1",
   "contribution": 1.594845552721228
  },
  {
   "feature": "dest_fanin_all",
   "label": "dest_fanin_all",
   "value": 2.0,
   "display": "2.00",
   "contribution": 1.5843502620490528
  },
  {
   "feature": "vel24_ratio",
   "label": "24 h booking velocity vs baseline",
   "value": 7.202520898341291,
   "display": "7.2\u00d7 the usual daily rate",
   "contribution": 1.4073247593697322
  }
 ],
 "rule_hits": [
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  }
 ],
 "counterfactual": [
  {
   "feature": "log_pay_age_min",
   "set_to": 13.0,
   "p_after": 0.9997165824835259,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.9036258317951683,
   "clears_threshold": false
  },
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9996744022826737,
   "clears_threshold": false
  },
  {
   "feature": "dest_fraud",
   "set_to": 0.0,
   "p_after": 0.999770255394135,
   "clears_threshold": false
  }
 ]
}
```

### geo_drift_heavy — B016171 (true label: FRAUD)

> Booking B016171 by shipper S0144 scores a fraud probability of 1.00 (decision threshold 0.00), based on 31 prior bookings from this shipper. Main drivers — payment instrument age: 0.6 h old; behavioural drift vs own history: 16.0 (typical ≈ 4); other shippers on this device (30 d): 4; weight vs shipper's history: +4.2 σ. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper); R06_WEIGHT_OUTLIER (weight >4σ above the shipper's own history); R07_OFFHOURS_NEW_DEVICE_NEW_DEST (booked 00:00–05:00 from a new device to a new destination). Linked infrastructure: destination has 0 confirmed-fraud shipments, device 2, payment instrument 0.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "log_pay_age_min",
   "label": "payment instrument age",
   "value": 3.6375861597263857,
   "display": "0.6 h old",
   "contribution": 4.899198369782689
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 16.008591966722623,
   "display": "16.0 (typical \u2248 4)",
   "contribution": 4.277442046005348
  },
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 4.0,
   "display": "4",
   "contribution": 2.7289541441452823
  },
  {
   "feature": "w_z",
   "label": "weight vs shipper's history",
   "value": 4.222081992841146,
   "display": "+4.2 \u03c3",
   "contribution": 1.1185905476342828
  },
  {
   "feature": "dest_addr_nov",
   "label": "destination novelty for this shipper",
   "value": 10.865032044135987,
   "display": "10.9 nats",
   "contribution": 1.0796479485807975
  },
  {
   "feature": "hour",
   "label": "booking hour",
   "value": 0.5833333333333334,
   "display": "00:00",
   "contribution": 0.8855865919439938
  }
 ],
 "rule_hits": [
  {
   "code": "R01_NEW_PAY_NEW_DEST_EXPRESS",
   "text": "payment instrument added <60 min ago + never-seen destination + express/priority"
  },
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  },
  {
   "code": "R06_WEIGHT_OUTLIER",
   "text": "weight >4\u03c3 above the shipper's own history"
  },
  {
   "code": "R07_OFFHOURS_NEW_DEVICE_NEW_DEST",
   "text": "booked 00:00\u201305:00 from a new device to a new destination"
  }
 ],
 "counterfactual": [
  {
   "feature": "log_pay_age_min",
   "set_to": 13.0,
   "p_after": 0.9982624162080472,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.7164363319221181,
   "clears_threshold": false
  },
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9993698231368321,
   "clears_threshold": false
  },
  {
   "feature": "w_z",
   "set_to": 0.0,
   "p_after": 0.9976471136176226,
   "clears_threshold": false
  }
 ]
}
```

### off_hours_new_device — B018182 (true label: FRAUD)

> Booking B018182 by shipper S0065 scores a fraud probability of 1.00 (decision threshold 0.00), based on 9 prior bookings from this shipper. Main drivers — payment instrument age: 0.6 h old; other shippers on this device (30 d): 3; behavioural drift vs own history: 8.2 (typical ≈ 4); cohort_individual: 1.00. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper); R07_OFFHOURS_NEW_DEVICE_NEW_DEST (booked 00:00–05:00 from a new device to a new destination). Linked infrastructure: destination has 0 confirmed-fraud shipments, device 3, payment instrument 3.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "log_pay_age_min",
   "label": "payment instrument age",
   "value": 3.6054978451748854,
   "display": "0.6 h old",
   "contribution": 5.128462996597067
  },
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 3.0,
   "display": "3",
   "contribution": 3.1430038704832013
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 8.172042750662635,
   "display": "8.2 (typical \u2248 4)",
   "contribution": 2.9183499895803906
  },
  {
   "feature": "cohort_individual",
   "label": "cohort_individual",
   "value": 1.0,
   "display": "1.00",
   "contribution": 1.5307158303960098
  },
  {
   "feature": "dest_addr_nov",
   "label": "destination novelty for this shipper",
   "value": 7.877017895622398,
   "display": "7.9 nats",
   "contribution": 0.8446520079283616
  },
  {
   "feature": "hour",
   "label": "booking hour",
   "value": 2.5666666666666664,
   "display": "02:00",
   "contribution": 0.7940132113032993
  }
 ],
 "rule_hits": [
  {
   "code": "R01_NEW_PAY_NEW_DEST_EXPRESS",
   "text": "payment instrument added <60 min ago + never-seen destination + express/priority"
  },
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  },
  {
   "code": "R07_OFFHOURS_NEW_DEVICE_NEW_DEST",
   "text": "booked 00:00\u201305:00 from a new device to a new destination"
  }
 ],
 "counterfactual": [
  {
   "feature": "log_pay_age_min",
   "set_to": 13.0,
   "p_after": 0.9928922005434918,
   "clears_threshold": false
  },
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9979839352221277,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.6850202217119317,
   "clears_threshold": false
  }
 ]
}
```

### payment_swap — B018591 (true label: FRAUD)

> Booking B018591 by shipper S0041 scores a fraud probability of 1.00 (decision threshold 0.00), based on 24 prior bookings from this shipper. Main drivers — payment instrument age: 0.4 h old; behavioural drift vs own history: 8.4 (typical ≈ 4); other shippers on this device (30 d): 4; confirmed-fraud shipments to this address: 1. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper); R07_OFFHOURS_NEW_DEVICE_NEW_DEST (booked 00:00–05:00 from a new device to a new destination). Linked infrastructure: destination has 1 confirmed-fraud shipments, device 3, payment instrument 0.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "log_pay_age_min",
   "label": "payment instrument age",
   "value": 3.3105430133940246,
   "display": "0.4 h old",
   "contribution": 4.4708782118510015
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 8.375376937208218,
   "display": "8.4 (typical \u2248 4)",
   "contribution": 3.4023286730707056
  },
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 4.0,
   "display": "4",
   "contribution": 2.7976974100126966
  },
  {
   "feature": "dest_fraud",
   "label": "confirmed-fraud shipments to this address",
   "value": 1.0,
   "display": "1",
   "contribution": 1.5343428051966788
  },
  {
   "feature": "dest_fanin_all",
   "label": "dest_fanin_all",
   "value": 1.0,
   "display": "1.00",
   "contribution": 1.4651168210383303
  },
  {
   "feature": "dest_addr_nov",
   "label": "destination novelty for this shipper",
   "value": 10.089116135087579,
   "display": "10.1 nats",
   "contribution": 1.1140008755093407
  }
 ],
 "rule_hits": [
  {
   "code": "R01_NEW_PAY_NEW_DEST_EXPRESS",
   "text": "payment instrument added <60 min ago + never-seen destination + express/priority"
  },
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  },
  {
   "code": "R07_OFFHOURS_NEW_DEVICE_NEW_DEST",
   "text": "booked 00:00\u201305:00 from a new device to a new destination"
  }
 ],
 "counterfactual": [
  {
   "feature": "log_pay_age_min",
   "set_to": 13.0,
   "p_after": 0.9998007235530944,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.8710821328707052,
   "clears_threshold": false
  },
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9997914528896776,
   "clears_threshold": false
  },
  {
   "feature": "dest_fraud",
   "set_to": 0.0,
   "p_after": 0.9998594829266884,
   "clears_threshold": false
  }
 ]
}
```

### stealthy_mule — B019801 (true label: FRAUD)

> Booking B019801 by shipper S0155 scores a fraud probability of 1.00 (decision threshold 0.00), based on 40 prior bookings from this shipper. Main drivers — other shippers on this device (30 d): 1; behavioural drift vs own history: 8.3 (typical ≈ 4); confirmed-fraud shipments to this address: 3; dest_fanin_all: 4.00. Policy rules triggered: R04_KNOWN_MULE_DEST (destination address linked to ≥2 confirmed fraud shipments); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper). Linked infrastructure: destination has 3 confirmed-fraud shipments, device 3, payment instrument 0.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 1.0,
   "display": "1",
   "contribution": 3.5927129842338568
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 8.25212984757981,
   "display": "8.3 (typical \u2248 4)",
   "contribution": 3.0253793042504653
  },
  {
   "feature": "dest_fraud",
   "label": "confirmed-fraud shipments to this address",
   "value": 3.0,
   "display": "3",
   "contribution": 2.692800452255363
  },
  {
   "feature": "dest_fanin_all",
   "label": "dest_fanin_all",
   "value": 4.0,
   "display": "4.00",
   "contribution": 2.471247549530274
  },
  {
   "feature": "dest_addr_nov",
   "label": "destination novelty for this shipper",
   "value": 9.923110425115306,
   "display": "9.9 nats",
   "contribution": 1.3270777355591903
  },
  {
   "feature": "dest_fanin_30d",
   "label": "other shippers to this address (30 d)",
   "value": 2.0,
   "display": "2",
   "contribution": 1.2317110573619525
  }
 ],
 "rule_hits": [
  {
   "code": "R04_KNOWN_MULE_DEST",
   "text": "destination address linked to \u22652 confirmed fraud shipments"
  },
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  }
 ],
 "counterfactual": [
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9953927802897821,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.4341658878734082,
   "clears_threshold": false
  },
  {
   "feature": "dest_fraud",
   "set_to": 0.0,
   "p_after": 0.9965924269600417,
   "clears_threshold": false
  }
 ]
}
```

### velocity_burst — B015253 (true label: FRAUD)

> Booking B015253 by shipper S0059 scores a fraud probability of 1.00 (decision threshold 0.00), based on 27 prior bookings from this shipper. Main drivers — payment instrument age: 0.4 h old; behavioural drift vs own history: 10.3 (typical ≈ 4); other shippers on this device (30 d): 1; confirmed-fraud shipments to this address: 3. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority); R04_KNOWN_MULE_DEST (destination address linked to ≥2 confirmed fraud shipments); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper); R07_OFFHOURS_NEW_DEVICE_NEW_DEST (booked 00:00–05:00 from a new device to a new destination). Linked infrastructure: destination has 3 confirmed-fraud shipments, device 2, payment instrument 0.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "log_pay_age_min",
   "label": "payment instrument age",
   "value": 3.139832617527748,
   "display": "0.4 h old",
   "contribution": 4.177462472317168
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 10.255671688042025,
   "display": "10.3 (typical \u2248 4)",
   "contribution": 3.9989340444517443
  },
  {
   "feature": "dev_shared_n",
   "label": "other shippers on this device (30 d)",
   "value": 1.0,
   "display": "1",
   "contribution": 2.564082397088004
  },
  {
   "feature": "dest_fraud",
   "label": "confirmed-fraud shipments to this address",
   "value": 3.0,
   "display": "3",
   "contribution": 1.6851680568562362
  },
  {
   "feature": "dest_fanin_all",
   "label": "dest_fanin_all",
   "value": 4.0,
   "display": "4.00",
   "contribution": 1.1568666508451921
  },
  {
   "feature": "dest_addr_nov",
   "label": "destination novelty for this shipper",
   "value": 9.290075339995036,
   "display": "9.3 nats",
   "contribution": 1.0053036521556102
  }
 ],
 "rule_hits": [
  {
   "code": "R01_NEW_PAY_NEW_DEST_EXPRESS",
   "text": "payment instrument added <60 min ago + never-seen destination + express/priority"
  },
  {
   "code": "R04_KNOWN_MULE_DEST",
   "text": "destination address linked to \u22652 confirmed fraud shipments"
  },
  {
   "code": "R05_SHARED_FRAUD_DEVICE",
   "text": "device previously used on confirmed-fraud bookings, new to this shipper"
  },
  {
   "code": "R07_OFFHOURS_NEW_DEVICE_NEW_DEST",
   "text": "booked 00:00\u201305:00 from a new device to a new destination"
  }
 ],
 "counterfactual": [
  {
   "feature": "log_pay_age_min",
   "set_to": 13.0,
   "p_after": 0.9993561223151334,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.8417865998245495,
   "clears_threshold": false
  },
  {
   "feature": "dev_shared_n",
   "set_to": 0.0,
   "p_after": 0.9992633007704225,
   "clears_threshold": false
  },
  {
   "feature": "dest_fraud",
   "set_to": 0.0,
   "p_after": 0.9995350110528837,
   "clears_threshold": false
  }
 ]
}
```

### legit — B018469 (true label: legit)

> Booking B018469 by shipper S0129 scores a fraud probability of 0.82 (decision threshold 0.00), based on 5 prior bookings from this shipper. Main drivers — 24 h booking velocity vs baseline: 18.6× the usual daily rate; cohort_individual: 1.00; behavioural drift vs own history: 5.6 (typical ≈ 4); weight vs shipper's history: +0.8 σ.

Verifier: PASS

```json
{
 "attributions": [
  {
   "feature": "vel24_ratio",
   "label": "24 h booking velocity vs baseline",
   "value": 18.595084283335648,
   "display": "18.6\u00d7 the usual daily rate",
   "contribution": 5.62917267259308
  },
  {
   "feature": "cohort_individual",
   "label": "cohort_individual",
   "value": 1.0,
   "display": "1.00",
   "contribution": 3.0520730125161246
  },
  {
   "feature": "drift_score",
   "label": "behavioural drift vs own history",
   "value": 5.6050465000201175,
   "display": "5.6 (typical \u2248 4)",
   "contribution": 1.8254496383334056
  },
  {
   "feature": "w_z",
   "label": "weight vs shipper's history",
   "value": 0.77642873465056,
   "display": "+0.8 \u03c3",
   "contribution": 0.490034987028053
  },
  {
   "feature": "log_n_hist",
   "label": "log_n_hist",
   "value": 1.791759469228055,
   "display": "1.79",
   "contribution": 0.4834789518653967
  },
  {
   "feature": "origin_nov",
   "label": "origin novelty",
   "value": 0.4366379354019353,
   "display": "0.4 nats",
   "contribution": 0.46417723171978953
  }
 ],
 "rule_hits": [],
 "counterfactual": [
  {
   "feature": "vel24_ratio",
   "set_to": 1.0,
   "p_after": 0.00456437114694197,
   "clears_threshold": false
  },
  {
   "feature": "drift_score",
   "set_to": 4.0,
   "p_after": 0.03547342952423851,
   "clears_threshold": false
  },
  {
   "feature": "w_z",
   "set_to": 0.0,
   "p_after": 0.6898038647447226,
   "clears_threshold": false
  }
 ]
}
```

## Observations

- The narrative is *downstream* of the decision. Latency of the LLM never touches the booking SLA;
  the explanation is produced asynchronously and attached to the case.
- The verifier is cheap (regex over numbers/ids) and makes the GenAI output auditable: a narrative that
  cites a number or entity absent from the evidence pack is never shown.
- Counterfactuals turn attributions into an action: 'would clear if the payment instrument were not
  minutes old' tells the analyst what to verify (step-up: confirm the new card with the account owner).
- Two narratives should be rendered from the same pack: analyst-facing (this one) and customer-facing
  (never reveals features; only asks for verification). Both are logged with the decision.
