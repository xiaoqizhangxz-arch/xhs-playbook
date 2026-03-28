from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import RUNTIME_ROOT

ARTIFACT_DIRS: dict[str, Path] = {
    "current_state":         RUNTIME_ROOT / "states",
    "mission_plan":          RUNTIME_ROOT / "plans",
    "execution_package":     RUNTIME_ROOT / "execution",
    "experiment_record":     RUNTIME_ROOT / "experiments" / "records",
    "experiment_result":     RUNTIME_ROOT / "experiments" / "results",
    "post_feedback_report":  RUNTIME_ROOT / "reports",
    "entity_registry":       RUNTIME_ROOT / "registries" / "entities",
    "metric_registry":       RUNTIME_ROOT / "registries" / "metrics",
    "anomaly_gate_result":   RUNTIME_ROOT / "states" / "anomaly",
}


def write_artifact(object_type: str, data: dict[str, Any], artifact_id: str | None = None) -> Path:
    base = ARTIFACT_DIRS.get(object_type, RUNTIME_ROOT / object_type)
    base.mkdir(parents=True, exist_ok=True)
    name = f"{artifact_id or data.get('id', 'latest')}.json"
    path = base / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_artifact(object_type: str, artifact_id: str) -> dict[str, Any]:
    base = ARTIFACT_DIRS.get(object_type, RUNTIME_ROOT / object_type)
    path = base / f"{artifact_id}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
