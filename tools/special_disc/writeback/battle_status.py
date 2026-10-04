"""Copy the ten frozen status texts into SP without replacing its atlas/CLUT."""
from special_disc.writeback.battle_overlay_cells import MEMBER, apply_cells, verify_cells


def verify_status_labels(data):
    return verify_cells(data, ("status",), "status")


def apply_status_labels(data):
    output, report = apply_cells(data, ("status",), "status")
    report["non_status_pixels_and_arrows_exact"] = report.pop("non_target_pixels_exact")
    return output, report
