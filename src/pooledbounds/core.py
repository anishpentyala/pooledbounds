"""Exact nearest-rank/CDF envelopes for disjoint, finite real observations.

Histogram buckets are (-inf, edge0], (edge0, edge1], ..., (last, inf).
Counts are observation counts, not weights, rates or cumulative counters.
"""
from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import re


class InvalidHistogram(ValueError):
    """The declared population cannot be analyzed in the supported model."""


@dataclass(frozen=True)
class Limits:
    max_histograms: int = 1000
    max_buckets: int = 100000
    max_number_chars: int = 128
    max_total_count: int = 10**18
    max_query_bucket_work: int = 1000000

    def __post_init__(self):
        for key, value in vars(self).items():
            if type(value) is not int or not 1 <= value <= 10**18:
                raise InvalidHistogram(key + ' must be a positive integer <= 10^18')


def number(value, limits):
    # Strings make the input's decimal meaning independent of binary floats.
    if not isinstance(value, str) or not value or len(value) > limits.max_number_chars:
        raise InvalidHistogram('finite decimal values must be bounded-length strings')
    if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
        raise InvalidHistogram('invalid finite decimal syntax')
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidHistogram('invalid decimal value') from exc
    if not decimal.is_finite() or abs(decimal.as_tuple().exponent) > 1000:
        raise InvalidHistogram('decimal must be finite with exponent magnitude <= 1000')
    return Fraction(decimal)


def rational(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def endpoint(value, infinity):
    return {'infinity': infinity} if value is None else {'value': rational(value)}


def _population(document, limits):
    if (not isinstance(document, dict) or
            set(document) != {'schema', 'populations', 'histograms'} or
            type(document['schema']) is not int or document['schema'] != 1 or
            document['populations'] != 'disjoint-finite-observations'):
        raise InvalidHistogram('schema 1 requires explicit disjoint-finite-observations populations')
    histograms = document['histograms']
    if not isinstance(histograms, list) or not 1 <= len(histograms) <= limits.max_histograms:
        raise InvalidHistogram('histogram count limit or empty input')
    ids, buckets, total, bucket_count = set(), [], 0, 0
    for histogram in histograms:
        if not isinstance(histogram, dict) or set(histogram) != {'id', 'edges', 'counts'}:
            raise InvalidHistogram('histogram requires exactly id, edges, counts')
        ident = histogram['id']
        if not isinstance(ident, str) or not ident or len(ident) > 256 or ident in ids:
            raise InvalidHistogram('histogram IDs must be nonempty, unique and <=256 characters')
        ids.add(ident)
        edges, counts = histogram['edges'], histogram['counts']
        if not isinstance(edges, list) or not isinstance(counts, list) or len(counts) != len(edges) + 1:
            raise InvalidHistogram('counts must have one more entry than edges')
        bucket_count += len(counts)
        if bucket_count > limits.max_buckets:
            raise InvalidHistogram('total bucket limit exceeded')
        edges = [number(e, limits) for e in edges]
        if any(a >= b for a, b in zip(edges, edges[1:])):
            raise InvalidHistogram('edges must be strictly increasing')
        for index, count in enumerate(counts):
            if type(count) is not int or count < 0:
                raise InvalidHistogram('counts must be nonnegative integers, not cumulative values or rates')
            total += count
            if total > limits.max_total_count:
                raise InvalidHistogram('total observation count limit exceeded')
            if count:
                buckets.append((ident, index, None if index == 0 else edges[index-1],
                                None if index == len(edges) else edges[index], count))
    if not total:
        raise InvalidHistogram('empty pooled population has no defined quantile or fraction')
    return buckets, total


def _endpoint_rows(buckets, side):
    # None means -inf for lower endpoints and +inf for upper endpoints.
    index = 2 if side == 'lower' else 3
    rows = sorted(buckets, key=lambda b: ((0 if side == 'lower' else 2)
                                         if b[index] is None else 1,
                                         Fraction(0) if b[index] is None else b[index]))
    return rows


def _cumulative_counts(rows):
    counts, total = [], 0
    for row in rows:
        total += row[4]
        counts.append(total)
    return counts


def _rank_endpoint(rows, cumulative, rank, side):
    index = 2 if side == 'lower' else 3
    position = bisect_left(cumulative, rank)
    if position == len(rows):
        raise AssertionError('validated rank must be present')
    row = rows[position]
    before = 0 if position == 0 else cumulative[position - 1]
    return row[index], {'histogram': row[0], 'bucket': row[1],
                        'count_before': before, 'count_through': cumulative[position]}


def analyze(document, *, quantiles=('0.5', '0.95', '0.99'), thresholds=(), limits=None):
    """Return tight envelopes under the declared, not verified, input assumptions."""
    limits = Limits() if limits is None else limits
    if not isinstance(limits, Limits):
        raise InvalidHistogram('limits must be Limits')
    if not isinstance(quantiles, (list, tuple)) or not isinstance(thresholds, (list, tuple)):
        raise InvalidHistogram('queries must be lists or tuples')
    if len(quantiles) + len(thresholds) > 1000:
        raise InvalidHistogram('at most 1000 queries')
    qs = [number(q, limits) for q in quantiles]
    ts = [number(t, limits) for t in thresholds]
    if any(not 0 < q <= 1 for q in qs):
        raise InvalidHistogram('quantiles must be >0 and <=1 (nearest-rank definition)')
    buckets, total = _population(document, limits)
    if (len(qs) + 2 * len(ts)) * len(buckets) > limits.max_query_bucket_work:
        raise InvalidHistogram('query/bucket work limit exceeded')
    lower_rows, upper_rows = _endpoint_rows(buckets, 'lower'), _endpoint_rows(buckets, 'upper')
    lower_counts, upper_counts = _cumulative_counts(lower_rows), _cumulative_counts(upper_rows)
    quantile_reports = []
    for q in qs:
        rank = (q.numerator * total + q.denominator - 1) // q.denominator
        lo, lo_proof = _rank_endpoint(lower_rows, lower_counts, rank, 'lower')
        hi, hi_proof = _rank_endpoint(upper_rows, upper_counts, rank, 'upper')
        quantile_reports.append({'q': rational(q), 'rank': rank,
                                 'lower': endpoint(lo, '-infinity'),
                                 'upper': endpoint(hi, '+infinity'),
                                 'lower_attained': False, 'upper_attained': hi is not None,
                                 'lower_certificate': lo_proof, 'upper_certificate': hi_proof})
    threshold_reports = []
    for threshold in ts:
        minimum = sum(b[4] for b in buckets if b[3] is not None and b[3] <= threshold)
        maximum = sum(b[4] for b in buckets if b[2] is None or b[2] < threshold)
        witnesses = {'minimum': [], 'maximum': []}
        for ident, index, lo, hi, count in buckets:
            for mode in witnesses:
                # Construct one finite rational representative for the entire bucket.
                if hi is not None and hi <= threshold:
                    value = hi
                elif lo is not None and lo >= threshold:
                    value = lo + 1 if hi is None else (lo + hi) / 2
                elif mode == 'maximum':
                    value = threshold
                else:
                    value = threshold + 1 if hi is None else (threshold + hi) / 2
                witnesses[mode].append({'histogram': ident, 'bucket': index,
                                        'count': count, 'value': rational(value)})
        threshold_reports.append({'threshold': rational(threshold),
                                  'count_min': minimum, 'count_max': maximum,
                                  'fraction_min': rational(Fraction(minimum, total)),
                                  'fraction_max': rational(Fraction(maximum, total)),
                                  'witnesses': witnesses})
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=True).encode()).hexdigest()
    return {'schema': 1, 'status': 'BOUNDS_IN_DECLARED_MODEL', 'input_sha256': digest,
            'total_count': total, 'quantiles': quantile_reports, 'thresholds': threshold_reports,
            'assumptions': ['disjoint populations', 'finite real observations',
                            'integer noncumulative bucket counts', 'lower-open upper-closed bins'],
            'excluded': ['statistical confidence', 'raw data validation', 'counter reset handling',
                         'weighted samples', 'NaN/infinite observations', 'Prometheus rate semantics']}
