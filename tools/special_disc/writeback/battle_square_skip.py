"""Special Disc native-tail square skip with edition-specific locked addresses."""
import hashlib
import json
from pathlib import Path
from srwz.battle_square_skip import apply_battle_square_skip, verify_battle_square_skip

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/battle-square-skip.json'


def load_contract():
    return json.loads(CONTRACT.read_text())


def apply_skip(executable):
    contract = load_contract()
    patched, report = apply_battle_square_skip(executable, contract, 'sp')
    report['contract_sha256'] = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    return patched, report


def verify_skip(executable):
    report = verify_battle_square_skip(executable, load_contract(), 'sp')
    report['contract_sha256'] = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    return report
