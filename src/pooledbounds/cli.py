"""Offline JSON histogram envelopes. Does not fetch, install, or query a server."""
import argparse
import json
import sys
from .core import InvalidHistogram, analyze

MAX_INPUT_BYTES = 8 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidHistogram('duplicate JSON key')
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='JSON file, or - for standard input')
    parser.add_argument('--quantile', action='append', help='decimal in (0,1]; repeatable')
    parser.add_argument('--threshold', action='append', default=[], help='finite decimal; repeatable')
    args = parser.parse_args(argv)
    try:
        if args.input == '-':
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            with open(args.input, 'rb') as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise InvalidHistogram('input byte limit exceeded')
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_object)
        result = analyze(document, quantiles=args.quantile if args.quantile is not None else
                         ['0.5', '0.95', '0.99'], thresholds=args.threshold)
        code = 0
    except (InvalidHistogram, ValueError, OSError, UnicodeError, RecursionError) as exc:
        result, code = {'schema': 1, 'status': 'INVALID', 'error': str(exc)}, 2
    try:
        sys.stdout.write(json.dumps(result, sort_keys=True) + '\n')
        sys.stdout.flush()
    except OSError:
        return 2
    return code


if __name__ == '__main__':
    sys.exit(main())
