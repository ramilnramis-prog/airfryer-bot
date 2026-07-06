"""Product-only scene generation runner: the NEW, safe generation path that
replaces the rejected CALL 1 HANDS masked-edit approach.

Approach decision (Background-first, not Product-guide) -- see
scene-05-hands-experiment-retrospective.md for the full history:

CALL 1 HANDS (V1-V4) depended on the OpenAI edit endpoint respecting an
alpha mask -- it didn't (gpt-image-2 regenerated ~90% of the frame outside
the mask). Every failure mode we spent four iterations fighting (seams,
missing fingers, torn forearm, wrist artifact) traces back to that single
false assumption: "the API will leave X untouched."

Background-first removes that assumption entirely. This runner NEVER asks
the API to preserve anything:
  - mode="generate" (plain text-to-image, NOT "edit") -- no reference
    images, no mask, nothing for the model to violate;
  - AI is free to draw kitchen/hands/sleeves/food/background however it
    wants for the ENTIRE frame;
  - real-product-v1 is then inserted deterministically via the existing,
    already-validated compositor (layer_compositor.compose +
    product_lock_validator.validate_composite) at the fixed screen
    position defined by APPROVED_TRANSFORM_B -- completely independent of
    what the AI drew there;
  - if the AI happened to draw its own product-like shape anywhere in
    frame, QA gate 5 (no_ai_redesigned_product_accepted) rejects the
    candidate outright; the canonical layer always overwrites that screen
    region regardless.

Product-guide (passing real-product-v1 as an "edit" reference/placement
guide) was considered and rejected for this pilot: it would reintroduce
mode="edit" multipart complexity and reference-image dependence for zero
benefit, since the compositor already knows exactly where to place the
product on the fixed canvas regardless of what the AI draws -- there is
nothing a placement guide would add that the deterministic transform
doesn't already provide.

No network calls happen unless run_product_only_scene(..., apply=True) is
called. Fail-closed: apply=True without OPENAI_API_KEY, or with
max_calls/retries misconfigured, raises before any network call.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .budget import SpendTracker
from .models import ImageRequest
from .openai_images_client import MissingAPIKeyError, OpenAIImagesProvider
from .product_only_policy import ProductOnlyPolicyError, plan_scene_request

GENERATION_MODE = "product_only"
COMPOSITE_APPROACH = "background_first"

MODEL = "gpt-image-2"
SIZE = "720x1280"
OUTPUT_FORMAT = "png"
N = 1
RETRIES = 0
MAX_CALLS = 1
HARD_CAP_USD = 0.50
PRICE_PER_IMAGE_USD_ESTIMATE = 0.30

QA_GATES = (
    {"id": 1, "name": "product_inserted", "check": "real-product-v1 вставлен в кадр deterministic compositing'ом (не пропущен)"},
    {"id": 2, "name": "silhouette_match", "check": "силуэт товара совпадает с real-product-v1 (product_lock_validator: silhouette)"},
    {"id": 3, "name": "handle_geometry_match", "check": "геометрия ручек — плоские угловые язычки, как в real-product-v1 (handle_geometry)"},
    {"id": 4, "name": "handle_slots_visible", "check": "короткие горизонтальные прорези ручек хотя бы частично видны"},
    {"id": 5, "name": "no_ai_redesigned_product_accepted", "check": "если AI нарисовал собственную форму-двойник где-либо в кадре — candidate reject, канонический слой не отменяет эту проверку"},
    {"id": 6, "name": "hands_interact_with_flat_tabs", "check": "руки визуально держат именно плоские боковые ручки-язычки, не борт корзины/формы"},
    {"id": 7, "name": "basket_clean", "check": "корзина аэрогриля чистая (сцена scene-05 требует чистую корзину)"},
    {"id": 8, "name": "food_count_exact", "check": "ровно 3 куриных бедра + картофельные дольки внутри формы"},
    {"id": 9, "name": "no_text_or_watermark", "check": "нет текста/watermark/логотипа в кадре"},
    {"id": 10, "name": "manual_review_required", "check": "anatomy/grip realism рук НИКОГДА не auto-PASS — требует визуальной проверки владельцем"},
)


class ProductOnlyRunnerError(RuntimeError):
    """Fail-closed: конфигурация --apply некорректна (нет ключа, hard cap не
    задан, max_calls/retries не по контракту) — бросается ДО сети."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class SceneRequestContract:
    scene_id: str
    prompt: str
    prompt_sha256: str
    model: str
    endpoint: str
    mode: str
    size: str
    n: int
    output_format: str
    retries: int
    max_calls: int
    hard_cap_usd: float


def build_full_prompt(plan: dict) -> str:
    """Собирает один текстовый prompt: continuity block + сцено-специфичный
    action + product lock instruction + negative prompt. НИКАКИХ reference
    images -- background-first, mode=generate."""
    parts = [
        plan["continuity_block_text"].strip(),
        plan["scene_action_prompt"].strip(),
        f"Product lock instruction: {plan['product_lock_instruction'].strip()}",
        f"Negative prompt (avoid): {plan['negative_prompt'].strip()}",
    ]
    return "\n\n".join(p for p in parts if p)


def build_request_contract(campaign_dir, scene_id: str) -> tuple[ImageRequest, SceneRequestContract, dict]:
    """Строит ImageRequest + контракт для отчёта. НИКОГДА не читает
    campaign_visual_lock.json и не резолвит appearance asset_id — весь
    prompt приходит из plan_scene_request() (product_only_policy.py),
    reference_images всегда пуст (background-first, mode=generate)."""
    plan = plan_scene_request(campaign_dir, scene_id)  # fail-closed само по себе
    prompt = build_full_prompt(plan)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    req = ImageRequest(
        scene_id=scene_id, prompt=prompt, n=N, size=SIZE,
        mode="generate", reference_images=[], output_format=OUTPUT_FORMAT,
    )
    contract = SceneRequestContract(
        scene_id=scene_id, prompt=prompt, prompt_sha256=prompt_sha256,
        model=MODEL, endpoint="/images/generations", mode="generate",
        size=SIZE, n=N, output_format=OUTPUT_FORMAT, retries=RETRIES,
        max_calls=MAX_CALLS, hard_cap_usd=HARD_CAP_USD,
    )
    return req, contract, plan


def run_product_only_scene(campaign_dir, scene_id: str, apply: bool = False,
                           out_dir=None) -> dict:
    """Единственный entry point генерации product-only сцены.

    apply=False (default): ТОЛЬКО планирование, 0 сетевых вызовов,
    api_spend=0 -- работает даже без OPENAI_API_KEY.

    apply=True: РОВНО один реальный вызов (n=1, retries=0, max_calls=1,
    hard cap $0.50), требует OPENAI_API_KEY в окружении. Падает ДО сети
    (ProductOnlyRunnerError/MissingAPIKeyError), если что-то из контракта
    не соблюдено.

    Runner НИКОГДА не читает campaign_visual_lock.json, никогда не
    резолвит person-b-exhausted-01/real-grip-motion-01/v2-hand-hold-01/
    v2-form-in-basket-01/food-wings-01 -- structurally гарантировано тем,
    что build_request_contract идёт ТОЛЬКО через plan_scene_request()."""
    req, contract, plan = build_request_contract(campaign_dir, scene_id)

    if apply:
        if MAX_CALLS != 1:
            raise ProductOnlyRunnerError(
                "MAX_CALLS_VIOLATION", f"max_calls={MAX_CALLS} != 1 — apply запрещён")
        if RETRIES != 0:
            raise ProductOnlyRunnerError(
                "RETRIES_VIOLATION", f"retries={RETRIES} != 0 — apply запрещён")
        if HARD_CAP_USD <= 0:
            raise ProductOnlyRunnerError(
                "HARD_CAP_NOT_SET", "hard_cap_usd должен быть > 0 для apply")
        # OPENAI_API_KEY проверяется ДО сети самим OpenAIImagesProvider._api_key()
        # при apply=True (MissingAPIKeyError) -- ничего не резолвим руками здесь,
        # чтобы не задваивать логику проверки ключа.

    tracker = SpendTracker(cap_usd=HARD_CAP_USD)
    provider = OpenAIImagesProvider(model=MODEL, tracker=tracker,
                                    price_per_image_usd=PRICE_PER_IMAGE_USD_ESTIMATE)

    out_dir = str(out_dir) if out_dir else str(
        Path(campaign_dir) / "generated" / "product-only-scene" / scene_id)

    results = provider.generate(req, out_dir=out_dir, apply=apply)

    report = {
        "generation_mode": GENERATION_MODE,
        "composite_approach": COMPOSITE_APPROACH,
        "scene_id": scene_id,
        "mode": "apply" if apply else "dry-run",
        "uses_campaign_visual_lock": False,
        "uses_reference_library_for_appearance": False,
        "global_visual_reference": plan["global_visual_reference"],
        "request_contract": {
            "model": contract.model, "endpoint": contract.endpoint,
            "mode": contract.mode, "size": contract.size, "n": contract.n,
            "output_format": contract.output_format, "retries": contract.retries,
            "max_calls": contract.max_calls, "hard_cap_usd": contract.hard_cap_usd,
            "prompt_sha256": contract.prompt_sha256,
            "reference_images": [],
        },
        "results": [r.to_dict() for r in results],
        "budget": tracker.summary(),
        "openai_calls_executed": 1 if apply else 0,
        "higgsfield_calls_executed": 0,
        "food_calls_executed": 0,
        "api_spend_usd": tracker.total_actual() if apply else 0,
        "qa_gates": list(QA_GATES),
        "manual_review_required": True,
        "next_step": ("planned_product_lock_composite: real-product-v1 через "
                     "APPROVED_TRANSFORM_B поверх этого AI-фона, затем "
                     "product_lock_validator.validate_composite — отдельный "
                     "локальный шаг без API, ещё не выполнен."),
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(out_dir) / f"{scene_id}-product-only-{'apply' if apply else 'dry-run'}-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
