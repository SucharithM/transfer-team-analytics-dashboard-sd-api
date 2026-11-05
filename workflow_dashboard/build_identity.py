"""Build-time code identity; excludes all runtime settings and source data."""
import argparse
import json
from pathlib import Path

from .diagnostics import SCHEMA, code_fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fingerprint = code_fingerprint()
    if fingerprint == 'unavailable':
        raise SystemExit('Could not calculate application code identity.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schema': SCHEMA, 'fingerprint': fingerprint}), encoding='utf-8')


if __name__ == '__main__':
    main()
