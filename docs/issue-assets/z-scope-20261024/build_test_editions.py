"""Build the three editions into build/iso/test/<tag>-<edition>.iso.

The regular batch (tools/build_editions.build) runs unchanged; only the
promoted ISO path and the edition receipt are redirected, so the current ISOs
and manifests/editions/*/current.json stay untouched. Tracked validation
manifests that the component builders regenerate do change.

  python3 build_test_editions.py --tag z-scope-20261024
"""
from pathlib import Path
import argparse
import json
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path[:0] = [str(ROOT / 'tools')]
import build_editions as be  # noqa: E402
from srwz.edition import BuildContext, project_path  # noqa: E402


def redirect(tag: str) -> Path:
    receipts = OUT / 'build' / tag
    receipts.mkdir(parents=True, exist_ok=True)
    BuildContext.output_iso = property(lambda self: project_path(
        self.root, f'build/iso/test/{tag}-{self.profile.edition_id}.iso', 'build/iso'))
    BuildContext.receipt = property(lambda self: receipts / f'{self.profile.edition_id}.json')
    return receipts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--editions', default='original,best,sp')
    parser.add_argument('--force-rebuild', action='store_true')
    args = parser.parse_args()
    receipts = redirect(args.tag)
    result = be.build(ROOT, be.DEFAULT_CONFIG, tuple(args.editions.split(',')),
                      force_rebuild=args.force_rebuild)
    (receipts / 'batch.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
