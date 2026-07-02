"""Модели данных визуального конвейера. Только stdlib."""
from __future__ import annotations

import abc
import datetime as _dt
from dataclasses import dataclass, field, asdict


def utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Scene spec (content/autopilot/<campaign>/scene-specs/scene-NN.json)
# ---------------------------------------------------------------------------

@dataclass
class SceneSpec:
    scene_id: str
    title: str = ""
    prompt_action: str = ""
    prompt_camera: str = ""
    immutable_elements: list = field(default_factory=list)
    allowed_changes: list = field(default_factory=list)
    required_references: list = field(default_factory=list)
    # {"item": "chicken thigh", "count": 3} либо None, если еды в кадре нет
    exact_food_count: dict | None = None
    hand_requirements: dict = field(default_factory=dict)
    camera_requirements: dict = field(default_factory=dict)
    relationship_to_previous: str = ""
    relationship_to_next: str = ""
    animation_intent: str = ""
    hard_fail_conditions: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SceneSpec":
        known = {f for f in cls.__dataclass_fields__}  # noqa: B008
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Наблюдение по кандидату — заполняет visual-director (или mock в тестах).
# Детерминированные правила visual_qa.py работают ПОВЕРХ этого наблюдения.
# ---------------------------------------------------------------------------

@dataclass
class CandidateObservation:
    candidate_id: str
    # hard-fail сигналы
    product_matches_reference: bool = True
    handle_count: int = 2
    product_color_material_ok: bool = True
    airfryer_matches_reference: bool = True
    airfryer_in_frame: bool = True
    hands_in_frame: bool = True
    hands_gender: str = "female"          # female | male | ambiguous | none
    hand_anatomy_ok: bool = True
    product_held: bool = False
    grip_on_specified_handles: bool = True
    food_count_actual: int | None = None
    has_text_or_watermark: bool = False
    has_impossible_intersections: bool = False
    looks_cgi: bool = False
    animation_ready: bool = True
    adjacent_scene_compatible: bool = True
    # scoring 0-100 (только для кандидатов без hard fail)
    scores: dict = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateObservation":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class CandidateVerdict:
    candidate_id: str
    hard_fails: list = field(default_factory=list)   # список кодов
    scores: dict = field(default_factory=dict)
    total: float | None = None
    passed: bool = False
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SceneDecision:
    scene_id: str
    round: int
    winner_id: str | None
    verdicts: list = field(default_factory=list)     # list[CandidateVerdict.to_dict()]
    rejection_reasons: dict = field(default_factory=dict)
    regeneration_brief: str | None = None
    needs_owner: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Запрос/результат генерации
# ---------------------------------------------------------------------------

@dataclass
class ImageRequest:
    scene_id: str
    prompt: str
    n: int = 3
    size: str = "1024x1536"               # portrait, максимально близкий к 9:16
    mode: str = "generate"                # generate | edit
    reference_images: list = field(default_factory=list)
    quality: str | None = None            # например "medium" (если модель поддерживает)
    # legacy-параметр gpt-image-1; gpt-image-2 обрабатывает image inputs с высокой
    # fidelity автоматически — capability map не даст отправить его не туда
    input_fidelity: str | None = None


@dataclass
class ImageResult:
    candidate_id: str
    scene_id: str
    provider: str
    model: str
    prompt: str
    revised_prompt: str | None = None
    image_path: str | None = None
    dry_run: bool = True
    created_at: str = field(default_factory=utcnow_iso)
    estimated_cost_usd: float = 0.0
    planned_request: dict | None = None   # только в dry-run: payload БЕЗ секретов
    qa: dict | None = None                # заполняется после visual QA

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Интерфейс провайдера — конвейер не привязан к одному вендору.
# ---------------------------------------------------------------------------

class ImageProvider(abc.ABC):
    """Провайдер генерации изображений (OpenAI, mock, будущие вендоры)."""

    name: str = "abstract"
    model: str = ""

    @abc.abstractmethod
    def generate(self, request: ImageRequest, out_dir: str,
                 apply: bool = False) -> list:
        """Вернуть list[ImageResult]. При apply=False — НИКАКОЙ сети,
        только план запроса (dry-run)."""
