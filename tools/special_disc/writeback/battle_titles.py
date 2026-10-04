"""Copy twelve frozen formation/attack titles into SP, preserving its other cells."""
from special_disc.writeback.battle_overlay_cells import MEMBER, apply_cells, verify_cells

PROFILES = ("large-formation", "large-action")


def verify_title_labels(data):
    return verify_cells(data, PROFILES, "title")


def apply_title_labels(data):
    return apply_cells(data, PROFILES, "title")
