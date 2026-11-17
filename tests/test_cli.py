import json
import subprocess
import sys

import pytest

from pooledbounds.cli import main
from test_core import doc, hist


def test_cli_roundtrip(tmp_path, capsys):
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    assert main([str(p), '--quantile', '1', '--threshold', '2']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'BOUNDS_IN_DECLARED_MODEL'
    assert result['quantiles'][0]['rank'] == 2
    assert result['thresholds'][0]['count_min'] == 1


@pytest.mark.parametrize('raw', [b'{', b'[]', b'\xff', b'{"schema":1,"schema":1}',
                                b'{"value":NaN}', b'\xef\xbb\xbf{}'])
def test_invalid_json_no_partial_claims(tmp_path, capsys, raw):
    p = tmp_path/'data.json'
    p.write_bytes(raw)
    assert main([str(p)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {'schema', 'status', 'error'} and result['status'] == 'INVALID'


def test_read_limit_plus_one(tmp_path, monkeypatch, capsys):
    import pooledbounds.cli as cli
    p = tmp_path/'data.json'
    p.write_bytes(b' '*100)
    monkeypatch.setattr(cli, 'MAX_INPUT_BYTES', 10)
    assert main([str(p)]) == 2
    assert 'byte limit' in json.loads(capsys.readouterr().out)['error']


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path/'missing')]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'INVALID'


def test_module_stdin():
    p = subprocess.run([sys.executable, '-m', 'pooledbounds', '-', '--quantile', '.5'],
                       input=json.dumps(doc(hist())), capture_output=True, text=True)
    assert p.returncode == 0 and not p.stderr
    assert json.loads(p.stdout)['quantiles'][0]['rank'] == 1


def test_argument_error_is_exit_2():
    p = subprocess.run([sys.executable, '-m', 'pooledbounds'], capture_output=True, text=True)
    assert p.returncode == 2 and 'usage:' in p.stderr and not p.stdout
