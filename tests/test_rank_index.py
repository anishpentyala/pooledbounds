"""Cumulative rank lookup preserves exact certificates without query rescans."""
import random

import pytest

from pooledbounds import InvalidHistogram, Limits, analyze
from pooledbounds import core
from test_core import doc, hist


def linear(rows, rank, side):
    count = 0
    for row in rows:
        before = count
        count += row[4]
        if count >= rank:
            return row[2 if side == 'lower' else 3], {
                'histogram': row[0], 'bucket': row[1],
                'count_before': before, 'count_through': count,
            }
    raise AssertionError('rank absent')


def test_every_rank_matches_linear_reference_with_ties_and_tails():
    rng = random.Random(16219)
    for case in range(80):
        source = doc(*[hist(('-2', '0', '2'),
                           [rng.randrange(4) for _ in range(4)], str(i))
                       for i in range(4)])
        buckets, total = core._population(source, Limits())
        for side in ['lower', 'upper']:
            rows = core._endpoint_rows(buckets, side)
            cumulative = core._cumulative_counts(rows)
            for rank in range(1, total + 1):
                assert core._rank_endpoint(rows, cumulative, rank, side) == linear(rows, rank, side)


def test_query_order_duplicates_and_exact_boundaries_keep_certificates():
    source = doc(hist(('0', '1', '2'), (1, 2, 3, 4)),
                 hist(('0', '1', '2'), (1, 2, 3, 4), 'b'))
    qs = ['1', '.1', '.5', '.1', '.3', '.30001']
    report = analyze(source, quantiles=qs)
    buckets, total = core._population(source, Limits())
    assert [r['rank'] for r in report['quantiles']] == [20, 2, 10, 2, 6, 7]
    for item in report['quantiles']:
        for side in ['lower', 'upper']:
            _, proof = linear(core._endpoint_rows(buckets, side), item['rank'], side)
            assert item[side+'_certificate'] == proof
    assert report['quantiles'][1] == report['quantiles'][3]
    assert report['quantiles'][0]['upper'] == {'infinity': '+infinity'}


def test_lookup_reads_logarithmic_count_positions_not_rows():
    class IndexedCounts:
        def __init__(self, n):
            self.n, self.reads = n, 0
        def __len__(self):
            return self.n
        def __getitem__(self, i):
            self.reads += 1
            return i+1
    class IndexedRows:
        def __init__(self, n):
            self.n, self.reads = n, 0
        def __len__(self):
            return self.n
        def __getitem__(self, i):
            self.reads += 1
            return ('a', i, i, i+1, 1)
    rows, counts = IndexedRows(100000), IndexedCounts(100000)
    for rank in [1, 50000, 100000, 100000]:
        _, proof = core._rank_endpoint(rows, counts, rank, 'upper')
        assert proof['count_through'] == rank
    assert rows.reads == 4
    assert counts.reads <= 4 * 20


def test_admission_still_uses_original_work_contract_before_index(monkeypatch):
    def forbidden(*args):
        raise AssertionError('index created before admission')
    monkeypatch.setattr(core, '_cumulative_counts', forbidden)
    with pytest.raises(InvalidHistogram, match='work limit'):
        analyze(doc(hist()), quantiles=['.5', '.9'],
                limits=Limits(max_query_bucket_work=3))


def test_large_integer_counts_exactly_cross_rank_boundaries():
    source = doc(hist(('0', '1'), (0, 10**18-1, 1)))
    report = analyze(source, quantiles=['.999999999999999999', '1'])
    assert report['quantiles'][0]['rank'] == 10**18-1
    assert report['quantiles'][0]['upper_certificate']['bucket'] == 1
    assert report['quantiles'][1]['upper_certificate']['bucket'] == 2


def test_many_tail_queries_do_not_rescan_sorted_rows(monkeypatch):
    original = core._endpoint_rows
    visits = []
    class CountedRows(list):
        def __iter__(self):
            for row in super().__iter__():
                visits.append(1)
                yield row
    def counted(*args):
        return CountedRows(original(*args))
    monkeypatch.setattr(core, '_endpoint_rows', counted)
    source = doc(hist(tuple(map(str, range(99))), [1]*100))
    report = analyze(source, quantiles=['1']*1000)
    assert len(report['quantiles']) == 1000
    assert len(visits) == 200
