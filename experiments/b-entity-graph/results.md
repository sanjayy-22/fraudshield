# Experiment B — entity graph / ring detection

## 1. Feature-group ablation (test period, time split)

| model                     |   auc |    ap |   recall_fpr1 |   recall_fpr05 |   thr_fpr1 |
|:--------------------------|------:|------:|--------------:|---------------:|-----------:|
| graph features only       | 0.947 | 0.922 |         0.920 |          0.920 |      0.014 |
| behavioural features only | 0.989 | 0.870 |         0.867 |          0.805 |      0.004 |
| behavioural + graph       | 0.997 | 0.974 |         0.965 |          0.965 |      0.001 |

Per-scenario recall at 1 % FPR:

| scenario             |   graph features only |   behavioural features only |   behavioural + graph |
|:---------------------|----------------------:|----------------------------:|----------------------:|
| dormant_reactivation |                  0.93 |                        1.00 |                  1.00 |
| geo_drift_heavy      |                  1.00 |                        1.00 |                  1.00 |
| off_hours_new_device |                  1.00 |                        1.00 |                  1.00 |
| payment_swap         |                  1.00 |                        1.00 |                  1.00 |
| stealthy_mule        |                  0.75 |                        0.38 |                  0.75 |
| velocity_burst       |                  0.92 |                        0.87 |                  1.00 |

## 2. Unsupervised mule-address discovery

51 true mule addresses among 2027 destination addresses.

| ranking                            |   precision@51 |   precision@10 |
|:-----------------------------------|---------------:|---------------:|
| naive fan-in (distinct shippers)   |           0.82 |           0.50 |
| novelty-mass (unsupervised)        |           0.82 |           1.00 |
| novelty-mass × (1+confirmed fraud) |           0.82 |           1.00 |

Top-5 addresses by naive fan-in (the super-node problem — these are fulfilment hubs, not mules):

| dest_address_id   |   n_shippers |   n |
|:------------------|-------------:|----:|
| hub_fc_0          |           39 | 516 |
| hub_fc_1          |           38 | 567 |
| hub_fc_2          |           38 | 442 |
| hub_fc_4          |           37 | 547 |
| hub_fc_3          |           33 | 391 |

## 3. Known vs fresh ring infrastructure (test-period fraud)

- 83% of test-period fraud bookings touch an address, device or payment instrument that was
  already confirmed fraudulent (labels arrive with a 10-day delay). These are near-certain catches for the graph.
- For the stealthy scenario the share is 69%; the remainder is fresh infrastructure where only
  'many unrelated shippers, first-time destination, new device' style novelty can help — which is why the
  graph counters and the behavioural novelty features must be fed to the same model rather than run as
  separate rules.

## 4. One ring

![ring](visuals\ring_graph.png)

## Observations

- Raw fan-in is a trap: hubs dominate. Degree-capping unions (super-node guard) and weighting fan-in by
  *first-time-for-that-shipper* novelty is what separates mules from hubs without any labels.
- Graph features are cheap to serve online: three hash-map lookups (entity → recent shippers) and one
  union-find root lookup per booking — no GNN inference on the synchronous path.
- Label propagation is the feedback loop the problem statement already has (post-delivery detection); the
  graph turns yesterday's confirmed cases into today's blocks on shared infrastructure.
