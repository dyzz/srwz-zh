"""Copy ten frozen prompts/reasons into SP, preserving original EN and status."""
from special_disc.writeback.battle_overlay_cells import MEMBER, apply_cells, verify_cells

PROFILES = ("prompt", "prompt-long", "reason")


def verify_prompt_labels(data):
    return verify_cells(data, PROFILES, "prompt")


def apply_prompt_labels(data):
    return apply_cells(data, PROFILES, "prompt")
