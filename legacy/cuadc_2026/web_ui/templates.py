"""Supported formal Action Mission template catalog."""
from __future__ import annotations

import json

from fastapi import HTTPException

from app.config import ROOT_DIR
from applications.cuadc_2026.profile import CUADC_2026_PROFILE


ACTION_MISSION_TEMPLATE_DIR = ROOT_DIR / "config" / "action_missions"
ACTION_MISSION_TEMPLATE_NAMES = {
    item.name: item.label for item in CUADC_2026_PROFILE.mission_templates
}


def load_action_mission_template(name: str) -> dict:
    if name not in ACTION_MISSION_TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail="unknown action mission template")
    path = CUADC_2026_PROFILE.template_path(name, ROOT_DIR).resolve()
    template_dir = ACTION_MISSION_TEMPLATE_DIR.resolve()
    if path.parent != template_dir or path.suffix != ".json":
        raise HTTPException(status_code=404, detail="unknown action mission template")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="action mission template not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid template JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise HTTPException(status_code=500, detail="invalid action mission template structure")
    return data
