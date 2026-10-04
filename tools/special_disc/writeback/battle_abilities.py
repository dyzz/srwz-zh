"""Copy the 19 frozen ability/defense texts into SP, preserving its CLUT."""
from special_disc.writeback.battle_overlay_cells import MEMBER, apply_cells, verify_cells


def verify_ability_labels(data):
    return verify_cells(data, ("ability",), "ability")


def apply_ability_labels(data):
    return apply_cells(data, ("ability",), "ability")
