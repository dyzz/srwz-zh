"""Product wording installed in the active SP language view."""
import json
from pathlib import Path


def runtime_text():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'config/products/special-disc/runtime-text.json').read_text(encoding='utf-8'))
