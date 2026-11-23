"""Argument setup must not inspect caller stdout before report delivery."""
import io
import json
import sys

import pytest

from pooledbounds.cli import main
from test_core import doc, hist


class MinimalOutput:
    def __init__(self):
        self.parts = []
        self.flushes = 0
    def write(self, text):
        self.parts.append(text)
        return len(text)
    def flush(self):
        self.flushes += 1
    def fileno(self):
        raise AssertionError('argument setup must not probe caller descriptor')
    def isatty(self):
        raise AssertionError('argument setup must not probe caller terminal')


@pytest.mark.parametrize('color_env', ['normal', 'PYTHON_COLORS', 'FORCE_COLOR', 'NO_COLOR'])
def test_valid_report_uses_minimal_output_without_terminal_probe(tmp_path, monkeypatch, color_env):
    path = tmp_path/'data.json'
    path.write_text(json.dumps(doc(hist())), encoding='utf-8')
    for key in ['PYTHON_COLORS', 'FORCE_COLOR', 'NO_COLOR']:
        monkeypatch.delenv(key, raising=False)
    if color_env != 'normal':
        monkeypatch.setenv(color_env, '1')
    stream = MinimalOutput()
    monkeypatch.setattr(sys, 'stdout', stream)
    assert main([str(path)]) == 0
    assert json.loads(''.join(stream.parts))['status'] == 'BOUNDS_IN_DECLARED_MODEL'
    assert stream.flushes == 1 and sys.stdout is stream


@pytest.mark.parametrize('arguments,code', [(['--help'], 0), ([], 2), (['--invalid'], 2)])
def test_help_and_usage_are_plain_and_do_not_probe_report_destination(monkeypatch, arguments, code):
    monkeypatch.setenv('PYTHON_COLORS', '1')
    stream, diagnostic = MinimalOutput(), io.StringIO()
    monkeypatch.setattr(sys, 'stdout', stream)
    monkeypatch.setattr(sys, 'stderr', diagnostic)
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == code
    text = ''.join(stream.parts) + diagnostic.getvalue()
    assert 'usage:' in text
    assert '\x1b[' not in text
