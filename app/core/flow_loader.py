from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class FlowLoader:
    def load_directory(self, flows_dir: Path) -> dict[str, dict[str, Any]]:
        flows: dict[str, dict[str, Any]] = {}

        if not flows_dir.exists():
            return flows

        for path in sorted(flows_dir.glob("*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw_flows = data.get("flows") or {}

            for flow_id, flow_data in raw_flows.items():
                steps_out: list[dict[str, Any]] = []

                for raw_step in flow_data.get("steps", []) or []:
                    step_id = str(raw_step.get("id", ""))

                    if "action" in raw_step:
                        steps_out.append({
                            "id": step_id,
                            "step_type": "action",
                            "action": str(raw_step.get("action")),
                        })
                    elif "collect" in raw_step:
                        steps_out.append({
                            "id": step_id,
                            "step_type": "collect",
                            "collect": str(raw_step.get("collect")),
                        })
                    elif "end" in raw_step:
                        steps_out.append({
                            "id": step_id,
                            "step_type": "end",
                        })

                flows[flow_id] = {
                    "name": flow_data.get("name", flow_id),
                    "description": flow_data.get("description", ""),
                    "steps": steps_out,
                }

        return flows