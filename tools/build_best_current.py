#!/usr/bin/env python3
"""Build BEST using native sources and a same-snapshot shared compiler result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from srwz.best_build import BestCompiler, require
from srwz.edition import load_json
from srwz.release_inputs import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--common-project', required=True, type=Path)
    parser.add_argument('--common-receipt', required=True, type=Path)
    parser.add_argument('--input-digest', required=True)
    args = parser.parse_args()
    try:
        receipt = load_json(args.common_receipt)
        common = args.common_project.resolve()
        require(receipt['edition_id'] == 'original' and receipt['input_digest'] == args.input_digest
                and receipt['status'] == 'edition_iso_static_validated_runtime_pending', 'shared frontend input/edition binding mismatch')
        readback = common / 'manifests/zh-release-full-story-iso-content-validation.json'
        require(sha256_file(readback) == receipt['readback']['sha256'], 'shared frontend readback drift')
        proof = load_json(readback)
        require(proof['status'] == 'full_story_final_iso_static_content_readback_passed'
                and proof['iso']['sha256'] == receipt['output']['sha256'], 'shared frontend ISO binding mismatch')
        compiler = BestCompiler(ROOT, common, args.input_digest)
        report = compiler.compile()
        print(json.dumps(compiler.build_iso(report), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
