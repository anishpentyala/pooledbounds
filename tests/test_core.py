from copy import deepcopy
from fractions import Fraction
from itertools import product

import pytest

from pooledbounds import InvalidHistogram, Limits, analyze


def doc(*histograms):
    return {'schema': 1, 'populations': 'disjoint-finite-observations',
            'histograms': list(histograms)}


def hist(edges=('0', '2', '4'), counts=(0, 1, 1, 0), ident='a'):
    return {'id': ident, 'edges': list(edges), 'counts': list(counts)}


def frac(value):
    return Fraction(int(value['numerator']), int(value['denominator']))


def end(value):
    return None if 'infinity' in value else frac(value['value'])


def check_witness(source, threshold_report):
    threshold = frac(threshold_report['threshold'])
    for mode in ('minimum', 'maximum'):
        seen, below = {}, 0
        for item in threshold_report['witnesses'][mode]:
            ident, index, n, value = item['histogram'], item['bucket'], item['count'], frac(item['value'])
            original = next(h for h in source['histograms'] if h['id'] == ident)
            assert n == original['counts'][index] > 0
            edges = list(map(Fraction, original['edges']))
            assert index == 0 or value > edges[index-1]
            assert index == len(edges) or value <= edges[index]
            assert (ident, index) not in seen
            seen[ident, index] = n
            below += n if value <= threshold else 0
        assert seen == {(h['id'], i): n for h in source['histograms']
                        for i, n in enumerate(h['counts']) if n}
        assert below == threshold_report['count_min' if mode == 'minimum' else 'count_max']


def test_mixed_bins_example():
    source = doc(hist(('0', '100', '200'), (0, 90, 10, 0)),
                 hist(('0', '150', '300'), (0, 50, 50, 0), 'b'))
    result = analyze(source, quantiles=['.95'], thresholds=['120'])
    q, t = result['quantiles'][0], result['thresholds'][0]
    assert result['total_count'] == 200
    assert (end(q['lower']), end(q['upper']), q['rank']) == (150, 300, 190)
    assert q['lower_attained'] is False and q['upper_attained'] is True
    assert (t['count_min'], t['count_max']) == (90, 150)
    assert (frac(t['fraction_min']), frac(t['fraction_max'])) == (Fraction(9, 20), Fraction(3, 4))
    check_witness(source, t)


@pytest.mark.parametrize('threshold', ['-10', '0', '.5', '2', '3', '4', '10'])
@pytest.mark.parametrize('counts', [(0, 1, 1, 0), (1, 0, 0, 1), (0, 2, 0, 0), (2, 2, 2, 2)])
def test_threshold_endpoint_rules_and_witnesses(threshold, counts):
    source = doc(hist(counts=counts))
    result = analyze(source, thresholds=[threshold])
    check_witness(source, result['thresholds'][0])
    t = Fraction(threshold)
    # Independent direct possible/forced membership in a <=t set.
    edges = [None, Fraction(0), Fraction(2), Fraction(4), None]
    expected_min = sum(n for i, n in enumerate(counts) if edges[i+1] is not None and edges[i+1] <= t)
    expected_max = sum(n for i, n in enumerate(counts) if edges[i] is None or edges[i] < t)
    got = result['thresholds'][0]
    assert (got['count_min'], got['count_max']) == (expected_min, expected_max)


def test_exhaustive_small_integer_populations():
    """Enumerate every raw population, not the production endpoint algorithm."""
    checked = 0
    for a, b in product(range(1, 3), repeat=2):
        for a_edge, b_edge in product((2, 4), repeat=2):
            source = doc(hist(('0', str(a_edge)), (0, a, 0)),
                         hist(('0', str(b_edge)), (0, b, 0), 'b'))
            samples = [sorted(x + y) for x in product(range(1, a_edge+1), repeat=a)
                       for y in product(range(1, b_edge+1), repeat=b)]
            # Use terminating decimals plus exact rank derived independently.
            queries = ['.25', '.5', '.75', '1']
            report = analyze(source, quantiles=queries, thresholds=['0', '1', '2', '3', '4'])
            for query, result in zip(queries, report['quantiles']):
                q = Fraction(query)
                rank = (q.numerator * (a+b) + q.denominator-1)//q.denominator
                values = [sample[rank-1] for sample in samples]
                # Smallest finite integer is one above the open lower endpoint.
                assert min(values) == end(result['lower']) + 1
                assert max(values) == end(result['upper'])
                assert result['rank'] == rank
            for t in report['thresholds']:
                cutoff = frac(t['threshold'])
                possibilities = [sum(v <= cutoff for v in sample) for sample in samples]
                assert (t['count_min'], t['count_max']) == (min(possibilities), max(possibilities))
                check_witness(source, t)
            checked += len(samples)
    assert checked == 676


def test_lower_infimum_can_be_approached_not_attained():
    source = doc(hist(('1.2', '1.3'), (0, 3, 0)))
    q = analyze(source, quantiles=['1'])['quantiles'][0]
    assert end(q['lower']) == Fraction(6, 5)
    for epsilon in (Fraction(1, 100), Fraction(1, 10000), Fraction(1, 10**30)):
        sample = [Fraction(6, 5) + epsilon] * 3
        assert all(Fraction('1.2') < x <= Fraction('1.3') for x in sample)
        assert max(sample) - end(q['lower']) == epsilon
    assert q['lower_attained'] is False


def test_finite_observations_unbounded_tails():
    source = doc(hist(('0',), (1, 1)))
    qlo, qhi = analyze(source, quantiles=['.5', '1'])['quantiles']
    assert qlo['lower'] == {'infinity': '-infinity'}
    assert end(qlo['upper']) == 0
    assert end(qhi['lower']) == 0
    assert qhi['upper'] == {'infinity': '+infinity'}
    assert qhi['upper_attained'] is False
    for t in analyze(source, thresholds=['-100000', '0', '100000'])['thresholds']:
        check_witness(source, t)


def test_no_edges_means_whole_real_line():
    result = analyze(doc(hist((), (10,))), thresholds=['0'])
    assert result['quantiles'][0]['lower'] == {'infinity': '-infinity'}
    assert result['quantiles'][0]['upper'] == {'infinity': '+infinity'}
    assert (result['thresholds'][0]['count_min'], result['thresholds'][0]['count_max']) == (0, 10)


def test_exact_huge_counts_and_decimal_rank_not_binary_float():
    n = 10**18
    result = analyze(doc(hist(('0', '1', '2'), (0, n//10, n-n//10, 0))), quantiles=['0.100000000000000001'])
    q = result['quantiles'][0]
    assert q['rank'] == n//10+1 and end(q['lower']) == 1


def test_input_not_mutated_and_order_changes_only_provenance():
    source = doc(hist(), hist(('1', '3'), (0, 2, 0), 'b'))
    saved = deepcopy(source)
    a = analyze(source, thresholds=['1.5'])
    assert source == saved
    source['histograms'].reverse()
    b = analyze(source, thresholds=['1.5'])
    assert a['input_sha256'] != b['input_sha256']
    for qa, qb in zip(a['quantiles'], b['quantiles']):
        assert (qa['lower'], qa['upper']) == (qb['lower'], qb['upper'])
    assert analyze(saved) == analyze(saved)


@pytest.mark.parametrize('value', [None, True, 1, 1.5, '', ' ', 'nan', 'NaN', 'Infinity', '-inf', '1_0', '1/3', '0x10', '1e1001', '1e-1001', '1'*129])
def test_bad_decimal_edges(value):
    with pytest.raises(InvalidHistogram):
        analyze(doc(hist((value,), (1, 1))))


@pytest.mark.parametrize('counts', [[True, 1], [-1, 2], [0, 0], [1.0, 2], ['1', 2], [1], [10**18, 1]])
def test_bad_counts(counts):
    with pytest.raises(InvalidHistogram):
        analyze(doc(hist(('1',), counts)))


@pytest.mark.parametrize('q', ['0', '-.1', '1.1', 'NaN', 0.5, None])
def test_invalid_quantiles(q):
    with pytest.raises(InvalidHistogram):
        analyze(doc(hist()), quantiles=[q])


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(schema=True), lambda x: x.update(populations='cumulative'),
    lambda x: x.update(histograms=[]), lambda x: x.update(extra=1),
    lambda x: x['histograms'][0].update(edges=['2', '1']),
    lambda x: x['histograms'][0].update(edges=['1', '1']),
    lambda x: x['histograms'][0].update(id=''),
    lambda x: x['histograms'].append(deepcopy(x['histograms'][0])),
])
def test_bad_document(mutation):
    source = doc(hist())
    mutation(source)
    with pytest.raises(InvalidHistogram):
        analyze(source)


@pytest.mark.parametrize('value', [0, -1, True, 1.5, None, 10**18+1])
def test_bad_limits(value):
    with pytest.raises(InvalidHistogram):
        Limits(max_buckets=value)


def test_admission_limits_before_query_work():
    source = doc(hist(), hist(ident='b'))
    with pytest.raises(InvalidHistogram, match='histogram count'):
        analyze(source, limits=Limits(max_histograms=1))
    with pytest.raises(InvalidHistogram, match='bucket limit'):
        analyze(source, limits=Limits(max_buckets=7))
    with pytest.raises(InvalidHistogram, match='work limit'):
        analyze(source, quantiles=['.5'], thresholds=['1'], limits=Limits(max_query_bucket_work=11))
    assert analyze(source, quantiles=['.5'], thresholds=['1'], limits=Limits(max_query_bucket_work=12))
    with pytest.raises(InvalidHistogram):
        analyze(source, quantiles=['.5']*1001)


def test_exhaustive_mixed_interior_buckets():
    intervals = [(0, 2), (2, 4), (0, 4), (4, 6), (-2, 0)]
    checked = 0
    for selected in product(intervals, repeat=3):
        source = doc(*(hist((str(lo), str(hi)), (0, 1, 0), str(i))
                       for i, (lo, hi) in enumerate(selected)))
        supports = [[Fraction(k, 2) for k in range(lo*2+1, hi*2+1)] for lo, hi in selected]
        samples = [sorted(x) for x in product(*supports)]
        report = analyze(source, quantiles=['.1', '.5', '1'], thresholds=['-1', '0', '1', '2', '3', '4', '5'])
        for rank, q in enumerate(report['quantiles'], start=1):
            values = [sample[rank-1] for sample in samples]
            assert min(values) == end(q['lower']) + Fraction(1, 2)
            assert max(values) == end(q['upper'])
        for t in report['thresholds']:
            possible = [sum(x <= frac(t['threshold']) for x in sample) for sample in samples]
            assert (t['count_min'], t['count_max']) == (min(possible), max(possible))
            check_witness(source, t)
        checked += len(samples)
    assert checked == 13824


def test_extreme_decimal_exponents_and_empty_query():
    source = doc(hist(('1e-1000', '1e1000'), (0, 1, 0)))
    q = analyze(source, quantiles=['1'])['quantiles'][0]
    assert end(q['lower']) == Fraction(1, 10**1000)
    assert end(q['upper']) == 10**1000
    assert analyze(source, quantiles=[], thresholds=[])['quantiles'] == []


def test_noninteger_real_samples_and_all_threshold_witnesses():
    source = doc(hist(('-1.123', '.00000001', '999999'), (1, 5, 3, 2)))
    result = analyze(source, thresholds=['-10000', '-1.123', '0', '.00000001', '1e20'])
    for t in result['thresholds']:
        check_witness(source, t)


@pytest.mark.parametrize('kwargs', [{'quantiles': None}, {'thresholds': {}}, {'limits': {}},
                                    {'thresholds': ['NaN']}, {'quantiles': [' 0.5']}])
def test_invalid_api_arguments(kwargs):
    with pytest.raises(InvalidHistogram):
        analyze(doc(hist()), **kwargs)


def test_work_rejection_before_endpoint_sorting(monkeypatch):
    import pooledbounds.core as core
    def forbidden(*args):
        raise AssertionError('sort began before admission')
    monkeypatch.setattr(core, '_endpoint_rows', forbidden)
    with pytest.raises(InvalidHistogram, match='work limit'):
        analyze(doc(hist()), limits=Limits(max_query_bucket_work=1))


def test_count_independent_compressed_witness_size():
    source = doc(hist(('0', '1'), (0, 10**18, 0)))
    result = analyze(source, thresholds=['.5'])
    t = result['thresholds'][0]
    assert len(t['witnesses']['minimum']) == len(t['witnesses']['maximum']) == 1
    assert t['count_max'] == 10**18 and t['count_min'] == 0
    check_witness(source, t)
