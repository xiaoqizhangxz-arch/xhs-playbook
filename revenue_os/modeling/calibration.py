from __future__ import annotations

CALIBRATION_VERSION = "p0.calibration.v1"
CALIBRATION_BUCKET = "uncalibrated_small_sample_safe"


def calibration_ref(component: str) -> str:
    return f"calibration__{component}__{CALIBRATION_VERSION}"
