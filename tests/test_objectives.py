import copy
import itertools
import json
from fractions import Fraction

import pytest

from pooledbounds import InvalidHistogram, Limits, analyze, evaluate_objectives
from pooledbounds.cli import main


def document(counts=(2, 3, 5)):
    return {'schema': 1, 'populations': 'disjoint-finite-observations',
            'histograms': [{'id': 'a', 'edges': ['0', '10'], 'counts': list(counts)}]}


def objective(threshold='5', minimum_fraction='.5'):
    return {'threshold': threshold, 'minimum_fraction': minimum_fraction}


@pytest.mark.parametrize('threshold,target,want', [
    ('5', '.2', 'SATISFIED'), ('5', '.5', 'INDETERMINATE'),
    ('5', '.500000000000000000001', 'VIOLATED'),
    ('5', '0', 'SATISFIED'), ('5', '1', 'VIOLATED'),
    ('0', '.2', 'SATISFIED'), ('0', '.200000000000000000001', 'VIOLATED'),
    ('10', '.5', 'SATISFIED'), ('10', '.6', 'VIOLATED')])
def test_exact_decisions(threshold, target, want):
    result = evaluate_objectives(document(), [objective(threshold, target)])
    assert result['objective_status'] == want
    assert result['objectives'][0]['status'] == want
    assert result['quantiles'] == []
    assert result['objectives'][0]['threshold_index'] == 0
    assert result['total_count'] == 10


def test_no_mutation_or_arithmetic_change():
    data = document()
    objectives = [objective(), objective('10', '.5')]
    saved = copy.deepcopy((data, objectives))
    result = evaluate_objectives(data, objectives)
    plain = analyze(data, quantiles=(), thresholds=['5', '10'])
    assert {k: v for k, v in result.items() if k not in ('objectives', 'objective_status')} == plain
    assert (data, objectives) == saved
    assert result['objective_status'] == 'INDETERMINATE'
    result['thresholds'][0]['witnesses']['minimum'].clear()
    assert evaluate_objectives(data, objectives)['thresholds'][0]['witnesses']['minimum']


def test_overall_violation_dominates():
    result = evaluate_objectives(document(), [objective(), objective('0', '.9')])
    assert result['objective_status'] == 'VIOLATED'
    assert [d['status'] for d in result['objectives']] == ['INDETERMINATE', 'VIOLATED']


def test_all_satisfied_and_duplicate_objectives():
    result = evaluate_objectives(document(), [objective('0', '.2')] * 2)
    assert result['objective_status'] == 'SATISFIED'
    assert [d['threshold_index'] for d in result['objectives']] == [0, 1]


def test_independent_population_enumeration():
    # Every bucket contains representatives on both sides of every interior
    # threshold used below. Enumerating all assignments realizes both extrema.
    values_by_bucket = [(-2, -1, 0), (Fraction(1, 2), 1, 2),
                        (Fraction(5, 2), 3, 4)]
    for counts in itertools.product(range(3), repeat=3):
        if not sum(counts):
            continue
        data = document(counts)
        data['histograms'][0]['edges'] = ['0', '2']
        slots = [values for count, values in zip(counts, values_by_bucket) for _ in range(count)]
        populations = list(itertools.product(*slots))
        for threshold in ('0', '.5', '1', '2', '2.5', '3'):
            for target in ('0', '.25', '.5', '.75', '1'):
                results = [sum(v <= Fraction(threshold) for v in p) * Fraction(1, len(p)) >= Fraction(target)
                           for p in populations]
                want = 'SATISFIED' if all(results) else 'VIOLATED' if not any(results) else 'INDETERMINATE'
                assert evaluate_objectives(data, [objective(threshold, target)])['objective_status'] == want


@pytest.mark.parametrize('bad', [None, {}, [], [None], [{}],
    [{'threshold': '1', 'minimum_fraction': '.5', 'extra': 0}],
    [objective('NaN')], [objective('1', '-.1')], [objective('1', '1.1')],
    [objective('1', True)], [objective('1', 0.5)], [objective()] * 1001])
def test_invalid_objectives(bad):
    with pytest.raises(InvalidHistogram):
        evaluate_objectives(document(), bad)


def test_limits_remain_enforced():
    with pytest.raises(InvalidHistogram, match='work limit'):
        evaluate_objectives(document(), [objective()], limits=Limits(max_query_bucket_work=1))
    with pytest.raises(InvalidHistogram, match='limits must'):
        evaluate_objectives(document(), [objective()], limits={})
    with pytest.raises(InvalidHistogram, match='empty pooled'):
        evaluate_objectives(document((0, 0, 0)), [objective()])


@pytest.mark.parametrize('args,code,status', [
    (['--objective', '5=.2'], 0, 'SATISFIED'),
    (['--objective', '5=.5'], 3, 'INDETERMINATE'),
    (['--objective', '5=.6'], 1, 'VIOLATED'),
    (['--objective', '5=.5', '--objective', '0=.9'], 1, 'VIOLATED')])
def test_cli_objectives(tmp_path, capsys, args, code, status):
    path = tmp_path / 'data.json'
    path.write_text(json.dumps(document()))
    assert main([str(path)] + args) == code
    report = json.loads(capsys.readouterr().out)
    assert report['objective_status'] == status
    assert report['status'] == 'BOUNDS_IN_DECLARED_MODEL'


@pytest.mark.parametrize('args', [
    ['--objective', '5'], ['--objective', '5==.5'], ['--objective', '='],
    ['--objective', '5=.5', '--quantile', '.5'],
    ['--objective', '5=.5', '--threshold', '5'], ['--objective', '5=NaN']])
def test_cli_invalid_has_no_decision(tmp_path, capsys, args):
    path = tmp_path / 'data.json'
    path.write_text(json.dumps(document()))
    assert main([str(path)] + args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'INVALID'
    assert 'objectives' not in report and 'thresholds' not in report


def test_mixed_histogram_joint_decisions_enumerated():
    data = document((1, 0, 1))
    data['histograms'].append({'id': 'b', 'edges': ['2'], 'counts': [1, 1]})
    populations = list(itertools.product((-1, 0), (11, 12), (-1, 1, 2), (3, 11)))
    for first, second in itertools.product(('0', '.25', '.5', '.75', '1'), repeat=2):
        targets = [objective('1', first), objective('5', second)]
        truth = [all(sum(v <= Fraction(o['threshold']) for v in p) >= Fraction(o['minimum_fraction']) * len(p)
                     for o in targets) for p in populations]
        expected = 'SATISFIED' if all(truth) else 'VIOLATED' if not any(truth) else 'INDETERMINATE'
        assert evaluate_objectives(data, targets)['objective_status'] == expected


@pytest.mark.parametrize('failure', ['write', 'flush'])
@pytest.mark.parametrize('target', ['.2', '.5', '.6'])
def test_objective_output_failure_has_priority(tmp_path, monkeypatch, failure, target):
    class Output:
        def write(self, value):
            if failure == 'write':
                raise OSError('write failed')
            return len(value)
        def flush(self):
            raise OSError('flush failed')
    import sys
    path = tmp_path / 'data.json'
    path.write_text(json.dumps(document()))
    stream = Output()
    monkeypatch.setattr(sys, 'stdout', stream)
    assert main([str(path), '--objective', '5=' + target]) == 2
    assert sys.stdout is stream
