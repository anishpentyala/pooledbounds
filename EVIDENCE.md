# Why unequal-bin bounds

Primary pages inspected November 16, 2026. Quotes describe documentation or user
requests; they are not independent correctness or adoption measurements.

1. Practical mismatch question:
   https://groups.google.com/g/prometheus-users/c/voksfGDJfYc
   A user asks about aggregating different bucket boundaries. The dated reply:
   "Generally, Prometheus cannot handle this. You could play some tricks and
   only add or remove buckets while keeping enough buckets the same".
   This is a historical discussion, not a statement of current version limits.

2. Desired uncertainty output:
   https://github.com/prometheus/prometheus/issues/5706
   "To give users a better idea of the quantile error margin of
   `histogram_quantile()`, it would be useful to expose the target bucket's
   lower and upper bounds as two extra series".
   A request is evidence of the problem, not a request to this project or proof
   that the request remains unresolved in every current tool.

3. Current native histogram model:
   https://prometheus.io/docs/specs/native_histograms/
   "Histograms with different custom bucket boundaries are generally not
   mergeable with each other."
   Native histogram support and reconciliation continue to evolve. This tool
   does not replace PromQL or claim Prometheus cannot aggregate any unequal
   layout. It instead answers an interval question over independently supplied
   per-bucket counts without requiring common boundaries.

4. Closest directly inspected bounds implementation:
   https://docs.rs/bitrep/latest/src/bitrep/hist.rs.html
   "Merging requires identical edges - a mismatch poisons the state and is
   reported, never silently blended." (dash typography normalized)
   That is a sensible contract. pooledbounds has a different contract: compute
   the set of possible pooled outcomes without constructing a single exact
   rebucketed histogram. No claim about bitrep's other modules is made.

Research was bounded, not an exhaustive survey. No competitor benchmark or
claim of mathematical novelty is made. Bounds need correctly declared,
disjoint populations, units and lower-open/upper-closed finite-observation bins.
