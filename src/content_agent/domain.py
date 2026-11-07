"""Validated business contracts; money uses integer simulation units."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Brief(Contract):
    theme: str = Field(min_length=1, max_length=500)
    product_id: Literal["travel-cup"] = "travel-cup"
    markets: dict[str, int] = Field(default_factory=lambda: {"DE": 2, "US": 2})
    budget_units: int | None = Field(default=None, ge=0, le=100000)
    deadline_hours: float | None = Field(default=None, gt=0, le=720, allow_inf_nan=False)
    max_calls: int = Field(default=40, ge=1, le=1000)

    @model_validator(mode="after")
    def check_markets(self):
        if set(self.markets) != {"DE", "US"} or any(type(n) is not int or not 1 <= n <= 4 for n in self.markets.values()):
            raise ValueError("markets must contain DE and US, each with 1–4 videos")
        return self


class VideoTask(Contract):
    id: str = Field(pattern=r"^(DE|US)-[1-4]$")
    market: Literal["DE", "US"]
    angle: str = Field(min_length=4, max_length=200)
    audience: str = Field(min_length=2, max_length=200)
    strategy: str = Field(min_length=10, max_length=600)
    asset_ids: list[str] = Field(min_length=1, max_length=4)
    tier: Literal["premium", "standard", "economy"] = "standard"


class Shot(Contract):
    start: int = Field(ge=0)
    end: int = Field(gt=0, le=20)
    asset_id: str
    visual: str = Field(min_length=3)
    voiceover: str = Field(min_length=2)
    on_screen: str = Field(min_length=1)


class Script(Contract):
    task_id: str
    language: Literal["de-DE", "en-US"]
    title: str = Field(min_length=3)
    hook: str = Field(min_length=3)
    cta: str = Field(min_length=3)
    claim_ids: list[str] = Field(min_length=1)
    localization_rationale: str = Field(min_length=10)
    shots: list[Shot] = Field(min_length=3, max_length=6)


class Review(Contract):
    approved: bool
    language_score: int = Field(ge=1, le=5)
    market_fit_score: int = Field(ge=1, le=5)
    evidence_score: int = Field(ge=1, le=5)
    issues: list[str]
    rationale: str = Field(min_length=5)


def load_data(name: str):
    return json.loads((ROOT / "data" / name).read_text())


def initial_state(brief: Brief, task_id: str, mode: str, scenario: str) -> dict:
    return {
        "task_id": task_id, "brief": brief.model_dump(), "mode": mode,
        "scenario": scenario, "status": "running", "reason": "", "context": None,
        "catalog": [], "searches": [], "plan": [], "plan_version": 0,
        "artifacts": {}, "feedback": {}, "quote": None, "spent": 0, "elapsed_minutes": 0,
        "calls": 0, "model_calls": 0, "model_usage": {}, "attempts": {},
        "trace": [], "last_result": None, "decision": None,
        "saved": None, "resume_count": 0,
    }


def asset_file(asset: dict, root: Path = ROOT) -> Path:
    path = (root / asset["path"]).resolve()
    if not path.is_relative_to((root / "data" / "assets").resolve()):
        raise ValueError("asset path outside data/assets")
    return path


def validate_plan(plan: list[VideoTask], brief: Brief, catalog: list[dict]) -> None:
    expected = {f"{market}-{n}" for market, count in brief.markets.items() for n in range(1, count + 1)}
    if {v.id for v in plan} != expected or len(plan) != len(expected):
        raise ValueError("plan must preserve every requested market and video; no silent scope reduction")
    assets = {a["id"]: a for a in catalog}
    for task in plan:
        if not task.id.startswith(task.market + "-"):
            raise ValueError("task ID and market disagree")
        for aid in task.asset_ids:
            if aid not in assets or task.market not in assets[aid]["markets"]:
                raise ValueError(f"unknown/incompatible asset: {aid}")
        if len(task.asset_ids) != len(set(task.asset_ids)):
            raise ValueError("duplicate assets")
    for market in brief.markets:
        angles = [v.angle.casefold().strip() for v in plan if v.market == market]
        if len(set(angles)) != len(angles):
            raise ValueError("videos in a market need distinct angles")


def script_errors(script: Script, task: dict, product: dict) -> list[str]:
    errors = []
    if script.task_id != task["id"] or script.language != {"DE": "de-DE", "US": "en-US"}[task["market"]]:
        errors.append("task/language mismatch")
    if not set(script.claim_ids).issubset(product["claims"]):
        errors.append("unsupported claim IDs")
    end = 0
    for shot in script.shots:
        if shot.start != end or shot.end <= shot.start:
            errors.append("storyboard must be contiguous")
        if shot.asset_id not in task["asset_ids"]:
            errors.append("storyboard uses an unselected asset")
        end = shot.end
    if end != 20:
        errors.append("storyboard must cover exactly 20 seconds")
    if sum(len(shot.voiceover.split()) for shot in script.shots) > 55:
        errors.append("voiceover exceeds the 55-word demo limit for 20 seconds")
    # Demonstration rules supplement (do not replace) semantic review.
    # Check positive customer-facing copy, not a rationale that may mention a forbidden claim to reject it.
    text = " ".join([script.title, script.hook, script.cta] + [v for shot in script.shots for v in (shot.voiceover, shot.on_screen)]).lower()
    for claim in product["forbidden_claims"]:
        if claim.casefold() in text:
            errors.append(f"unsubstantiated product claim: {claim}")
    # The demo has no national market research; prevent common unsupported national generalizations.
    rationale = script.localization_rationale
    for phrase in ("德国人偏好", "美国人偏好", "德国市场对", "美国市场对", "deutsche Publikum", "German consumers prefer", "Americans prefer"):
        if phrase.casefold() in rationale.casefold():
            errors.append("localization must cite the supplied synthetic brief, not unsupported national preferences")
    return list(dict.fromkeys(errors))
