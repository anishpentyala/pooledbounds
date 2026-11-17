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


@pytest.mark.parametrize('failure', ['write', 'flush', 'closed'])
def test_main_preserves_caller_stream(tmp_path, monkeypatch, failure):
    class CallerStream:
        closed = failure == 'closed'
        redirects = 0

        def write(self, text):
            if failure == 'write':
                raise OSError('simulated write failure')
            if self.closed:
                raise ValueError('closed output')
            return len(text)

        def flush(self):
            raise OSError('simulated flush failure')

        def fileno(self):
            self.redirects += 1
            raise AssertionError('main must not inspect caller descriptors')

        def close(self):
            raise AssertionError('main must not close a caller stream')

    stream = CallerStream()
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    monkeypatch.setattr(sys, 'stdout', stream)
    assert main([str(p)]) == 2
    assert sys.stdout is stream and stream.redirects == 0


def _commands():
    from pathlib import Path
    console = Path(sys.executable).parent/'pooledbounds'
    return [[sys.executable, '-m', 'pooledbounds'],
            [sys.executable, '-m', 'pooledbounds.cli'], [str(console)]]


@pytest.mark.parametrize('command', _commands())
def test_process_full_device_exit_2(tmp_path, command):
    from pathlib import Path
    if not Path('/dev/full').exists():
        pytest.skip('requires /dev/full')
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    with open('/dev/full', 'wb') as target:
        result = subprocess.run(command + [str(p)], stdout=target, stderr=subprocess.PIPE)
    assert result.returncode == 2
    assert result.stderr == b''


@pytest.mark.parametrize('command', _commands())
def test_process_closed_pipe_exit_2(tmp_path, command):
    import os
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        result = subprocess.run(command + [str(p)], stdout=write_fd, stderr=subprocess.PIPE)
    finally:
        os.close(write_fd)
    assert result.returncode == 2
    assert result.stderr == b''


def test_process_custom_closed_stream_exit_2(tmp_path):
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    result = subprocess.run([
        sys.executable, '-c',
        'import io, sys; from pooledbounds.cli import entrypoint; '
        'sys.stdout = io.StringIO(); sys.stdout.close(); '
        'raise SystemExit(entrypoint())', str(p)
    ], capture_output=True)
    assert result.returncode == 2 and result.stdout == result.stderr == b''


def test_process_closed_stdout_descriptor_exit_2(tmp_path):
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    result = subprocess.run([
        sys.executable, '-c',
        'import os; from pooledbounds.cli import entrypoint; '
        'os.close(1); raise SystemExit(entrypoint())', str(p)
    ], capture_output=True)
    assert result.returncode == 2 and result.stdout == result.stderr == b''


def _close_stdout_at_exec():
    import os
    os.close(1)


@pytest.mark.skipif(sys.platform == 'win32', reason='requires POSIX fd inheritance')
@pytest.mark.parametrize('command', _commands())
def test_process_no_stdout_at_interpreter_start(tmp_path, command):
    # Closing fd 1 after startup leaves a wrapper, unlike this real exec case.
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    result = subprocess.run(command + [str(p)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, preexec_fn=_close_stdout_at_exec)
    assert result.returncode == 2 and result.stdout == result.stderr == b''


def test_callable_none_stdout_returns_2_without_replacing_it(tmp_path, monkeypatch):
    p = tmp_path/'data.json'
    p.write_text(json.dumps(doc(hist())))
    monkeypatch.setattr(sys, 'stdout', None)
    assert main([str(p)]) == 2
    assert sys.stdout is None


def _close_stdin_at_exec():
    import os
    os.close(0)


@pytest.mark.skipif(sys.platform == 'win32', reason='requires POSIX fd inheritance')
@pytest.mark.parametrize('command', _commands())
def test_process_no_stdin_at_interpreter_start(command):
    result = subprocess.run(command + ['-'], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            preexec_fn=_close_stdin_at_exec)
    assert result.returncode == 2 and result.stderr == b''
    assert json.loads(result.stdout) == {
        'schema': 1, 'status': 'INVALID', 'error': 'standard input is unavailable'}


def test_callable_none_stdin_invalid_without_replacing_it(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', None)
    assert main(['-']) == 2 and sys.stdin is None
    assert json.loads(capsys.readouterr().out) == {
        'schema': 1, 'status': 'INVALID', 'error': 'standard input is unavailable'}
