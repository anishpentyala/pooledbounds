"""Deterministic objectives under the histogram model, not statistical tests."""
from fractions import Fraction

from .core import InvalidHistogram, Limits, analyze, number, rational


def evaluate_objectives(document, objectives, *, limits=None):
    """Check minimum fractions of observations <= thresholds.

    Each objective has exactly threshold and minimum_fraction decimal strings.
    SATISFIED means every compatible population meets it; VIOLATED means none
    does. INDETERMINATE means both are possible, not a probabilistic confidence.
    """
    limits = Limits() if limits is None else limits
    if not isinstance(limits, Limits):
        raise InvalidHistogram('limits must be Limits')
    if not isinstance(objectives, (list, tuple)) or not 1 <= len(objectives) <= 1000:
        raise InvalidHistogram('objectives must contain 1 to 1000 entries')
    thresholds, targets = [], []
    for objective in objectives:
        if not isinstance(objective, dict) or set(objective) != {'threshold', 'minimum_fraction'}:
            raise InvalidHistogram('objective requires exactly threshold and minimum_fraction')
        number(objective['threshold'], limits)
        target = number(objective['minimum_fraction'], limits)
        if not 0 <= target <= 1:
            raise InvalidHistogram('minimum_fraction must be between 0 and 1')
        thresholds.append(objective['threshold'])
        targets.append(target)
    report = analyze(document, quantiles=(), thresholds=thresholds, limits=limits)
    decisions = []
    for index, (bound, target) in enumerate(zip(report['thresholds'], targets)):
        minimum = Fraction(bound['count_min'], report['total_count'])
        maximum = Fraction(bound['count_max'], report['total_count'])
        if minimum >= target:
            status = 'SATISFIED'
        elif maximum < target:
            status = 'VIOLATED'
        else:
            status = 'INDETERMINATE'
        decisions.append({'threshold_index': index, 'minimum_fraction': rational(target),
                          'status': status})
    statuses = {decision['status'] for decision in decisions}
    if 'VIOLATED' in statuses:
        overall = 'VIOLATED'
    elif 'INDETERMINATE' in statuses:
        overall = 'INDETERMINATE'
    else:
        overall = 'SATISFIED'
    report['objectives'] = decisions
    report['objective_status'] = overall
    return report
