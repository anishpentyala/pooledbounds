# pooledbounds

What can pooled p95 actually be when two teams sent histograms with different
bucket edges? `pooledbounds` keeps the uncertainty instead of making up a
within-bucket distribution.

It computes tight nearest-rank quantile bounds and exact lower/upper counts at
chosen thresholds. Histograms may have different edges. No shared-edge
rebucketing, linear interpolation, or expansion into individual observations is
needed. It also supplies compressed raw-population witnesses attaining both
threshold count bounds.

This is an offline arithmetic tool, not a Prometheus query engine, confidence
interval estimator, or proof that telemetry is correct.

## Example

Install from a checked-out copy with `pip install .`, then:

```sh
pooledbounds examples/mixed-bins.json --quantile 0.95 --threshold 120
# or
python -m pooledbounds examples/mixed-bins.json --quantile 0.95
```

The example combines 100 observations in each of two disjoint regions:

| Region | Histogram intervals with nonzero counts |
| --- | --- |
| A | 90 in (0,100], 10 in (100,200] |
| B | 50 in (0,150], 50 in (150,300] |

The pooled p95 is **strictly greater than 150 and at most 300**. Between 90 and
150 of the 200 observations are at or below 120, so the exact attainable fraction
range is [9/20, 3/4]. A point estimate inside those ranges needs an extra
assumption. Keeping only common finite edges would retain just 0 here and lose
useful information.

## Input contract

```json
{
  "schema": 1,
  "populations": "disjoint-finite-observations",
  "histograms": [
    {"id": "a", "edges": ["0", "100", "200"], "counts": [0, 90, 10, 0]},
    {"id": "b", "edges": ["0", "150", "300"], "counts": [0, 50, 50, 0]}
  ]
}
```

- Counts are nonnegative **integers per bucket**, not cumulative counts,
  weights, rates, or values already divided by a sampling factor.
- Edges are finite decimal strings in strictly increasing order. Scientific
  notation is allowed. Strings avoid silently rounding decimals through binary
  floating point. JSON numbers are not accepted for edges or query values.
- With edges `[a,b]`, counts describe `(-infinity,a]`, `(a,b]`, and
  `(b,+infinity)`. All observations are finite real numbers. Empty edges with
  one count mean the whole real line. Zero-count buckets are allowed.
- Histograms must describe disjoint observations. Repeated cumulative snapshots
  of the same counter are **not** separate populations. The declaration is an
  assumption supplied by the caller; the tool cannot verify disjointness or
  distinguish a plausible cumulative count vector from per-bucket counts.
- Histogram IDs must be unique. Unknown fields, duplicate JSON keys, malformed
  counts, non-increasing edges, and empty pooled populations are invalid.
- Units must already match. There is no implicit milliseconds/seconds conversion.

The input is not an OpenTelemetry or Prometheus export. Convert and check the
measurement interval, reset behavior, temporality, units and bucket convention
first. Do not feed `rate()` results as integer counts. `+Inf` observations,
`-Inf` observations and NaNs are outside this model, even though bins can have
unbounded endpoints.

## Quantile meaning and output

`--quantile` is repeatable; its default is 0.5, 0.95, 0.99. For `0 < q <= 1`,
nearest rank is `ceil(q*N)` in the pooled sorted raw population. The lower
endpoint is an infimum, **not an attained minimum**. A finite upper endpoint is
attainable. Unbounded tails are explicit `-infinity`/`+infinity`, never replaced
with a convenient finite estimate. There is no q=0 convention and no linear
sample-quantile interpolation.

All finite output values use exact rational objects:

```json
{"numerator": "3", "denominator": "4"}
```

Each quantile includes its rank and the sorted endpoint bucket crossing that
rank, with counts before and through that bucket. These are arithmetic
certificates under the input assumptions, not a cryptographic proof or raw-data
audit. Equal endpoint ties can choose a different provenance bucket if the
histograms are reordered; numerical bounds are unchanged.

`--threshold` is repeatable and asks for the number of observations **<=** that
value. Both count extrema are attained. Each witness lists one rational value
and multiplicity for every occupied input bucket. It preserves every supplied
bucket count, so the report does not expand a count of a billion into a billion
rows. It does not claim that either synthetic population was actually observed.

`input_sha256` binds the parsed document's canonical JSON representation
(sorted keys, compact separators, ASCII escapes), not its raw file bytes. It is
not a signature. It does not validate the input assumptions.

## Why the bounds are tight

Think of each count as repeated unknown values constrained to a bucket
`(lower,upper]`. For any feasible raw population, sorting the lower endpoints
bounds its kth value strictly from below; sorting the upper endpoints bounds
it from above. The kth lower and kth upper endpoints are therefore a valid
quantile envelope. Moving each unknown value arbitrarily close to its lower
endpoint approaches the lower bound. Setting values at finite upper endpoints
attains the finite upper bound. Unbounded endpoints can be approached without
finite limits. No probabilistic assumption is involved.

At threshold t, a bucket is forced below/equal t only if its upper endpoint is
<=t. A bucket can contribute below/equal t exactly when its lower endpoint is
<t. Sum these counts independently across the declared disjoint buckets. The
emitted witnesses construct both extremes with valid finite representatives.
The strict comparison matters: values in `(t,u]` cannot be <=t.

## Python API

```python
from pooledbounds import analyze, InvalidHistogram, Limits

report = analyze(document, quantiles=["0.95"], thresholds=["120"])
# Invalid or out-of-budget inputs raise InvalidHistogram.
```

The API does not mutate the document, access the environment, import a model,
open a network connection, or install anything. The CLI reads one UTF-8 JSON
file or `-` for standard input. Exit 0 means a report was computed in the
declared model, **not that an SLO passed**. Invalid data or I/O returns INVALID
JSON and exit 2. Argument syntax errors use argparse stderr and exit 2.

## Threshold objectives without interpolation

When the question is "at least 95% of observations were <=120", use an explicit
objective instead of treating a successful arithmetic report as a passing SLO:

```sh
pooledbounds examples/mixed-bins.json --objective 120=.95
```

For this example only 90 to 150 of 200 observations can be <=120. The command
returns `objective_status: "VIOLATED"` and exit 1: even the largest admissible
fraction, 3/4, is below .95. The same fixture with `120=.7` is
`INDETERMINATE` (exit 3), and with `120=.45` is `SATISFIED` (exit 0).

Each repeatable `--objective THRESHOLD=MINIMUM_FRACTION` requests a minimum
fraction of observations **<=** its threshold. Fractions are decimal strings
between 0 and 1 inclusive, not percentages. Comparisons use exact rational
arithmetic, with no rounding, tolerance or within-bucket interpolation.
Objectives cannot be combined with `--quantile` or `--threshold`; ordinary
queries and their exit behavior are unchanged when no objective is supplied.

- `SATISFIED`: the minimum possible good fraction is >= the target. Every
  compatible population meets the objective.
- `VIOLATED`: the maximum possible good fraction is < the target. No compatible
  population meets the objective.
- `INDETERMINATE`: some compatible populations meet it and some do not. A
  fraction whose upper bound equals the target is not a proven violation.

For several objectives, all must hold: any proven violation returns 1;
otherwise any indeterminate objective returns 3; otherwise the command returns
0. These minimum-fraction objectives are jointly compatible whenever each is
individually possible: putting values sufficiently close to each bucket's lower
endpoint attains all queried maximum counts simultaneously. Invalid input,
conflicting options and output failure return 2, taking priority over a computed
verdict. A zero observation total is invalid, not a vacuous pass.

The JSON retains the ordinary model status, input digest, total count and
threshold evidence, including count/fraction extrema and compressed witnesses.
`objectives` adds each exact target and a zero-based `threshold_index` into
`thresholds`, plus its verdict. `objective_status` combines the verdicts. Witnesses
are synthetic compatible populations, not measured requests.

```python
from pooledbounds import evaluate_objectives

report = evaluate_objectives(document, [
    {"threshold": "120", "minimum_fraction": ".95"},
])
assert report["objective_status"] in {"SATISFIED", "VIOLATED", "INDETERMINATE"}
```

This is a decision **inside the declared input model**, not a production SLO
certification, statistical confidence statement, telemetry-completeness check,
or live alert. Units, windows, disjointness and correct per-bucket integer counts
remain the caller's responsibility. Prometheus cumulative snapshots, rates and
reset handling are still outside the accepted input format. Existing monitoring
tools are preferable for live SLOs; this mode answers what an already exported,
unequal-bin population can prove without inventing hidden observations.

## Admission limits

Defaults: 1,000 histograms, 100,000 total buckets including empty ones,
1,000 queries, 128 characters per decimal, exponent magnitude <=1,000,
and total count <=10^18. The CLI reads at most 8 MiB plus one byte before
refusing a larger input. API callers already hold their documents in memory.

`Limits` can adjust histogram, bucket, number-character, total-count and
query/bucket-work caps. The work cap defaults to 1,000,000 units:
`occupied_buckets * (quantile_queries + 2 * threshold_queries)`.
This also bounds the number of threshold witness rows emitted. Endpoints are
sorted once per side; cumulative integer counts then let each quantile rank
use binary search instead of rescanning every occupied bucket. Equal endpoint
ties retain input order and the same bucket certificates. The two cumulative
count lists add one integer per occupied bucket per side. Threshold witnesses
still scan buckets, and the original admission-work formula is unchanged.
Count size does not cause per-observation allocation.
These are admission limits, not hard RAM, encoded-output-size or CPU guarantees.
Large rational values and caller-chosen larger caps can still be expensive.

## Evidence and scope

See [EVIDENCE.md](EVIDENCE.md) for the practical problem and comparison with
existing histogram tools. This applies elementary order-statistic bounds to a
specific offline workflow; it does not claim a new statistical method or that
no other implementation exists. Existing native histogram/sketch tools are
usually the better choice when you control future instrumentation.

Tests include enumeration of every raw population in small integer/half-integer
fixtures, independent checks of witness bucket membership and counts, exact
large ranks, unbounded tails, invalid inputs and resource admission. Synthetic
tests are not evidence of adoption or production accuracy.

## Output failures

The module and installed command return exit 2 when stdout cannot be written or
flushed, including a closed pipe or a full device. Already-written partial bytes
cannot be retracted, so check the exit status before using a report. The process
runner redirects a failed stdout to the null device before shutdown, preventing
Python's second flush from replacing exit 2 with exit 120.

The callable `pooledbounds.cli.main(argv)` also returns 2 for these failures but
never closes or redirects a caller-owned stream. An embedding application owns
its own later flush and shutdown behavior.


Argument help and usage are plain text, without automatic terminal color probes.
This includes Python 3.14, where the parser and its help formatter each have an
independent color default. A caller may supply a minimal or closed output stream;
argument setup does not inspect that stream's terminal or file descriptor. The
existing output boundary still handles report write/flush failures with exit 2.
This does not add new handling for every possible help-output failure.
