"""Single source-disc path for SP tools; main-game reuse keeps its own provenance."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISC_INVENTORY = ROOT / "config/products/special-disc/disc-inventory.json"
SOURCE_ISO = ROOT / json.loads(DISC_INVENTORY.read_text(encoding="utf-8"))["sp"]["path"]
