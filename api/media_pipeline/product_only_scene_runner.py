"""Product-only scene generation runner: the NEW, safe generation path that
replaces the rejected CALL 1 HANDS masked-edit approach.

Approach: PRODUCT PLACEMENT PLATE (revised from an earlier "background-first"
framing that still asked the model to draw the final silicone liner --
that was a real conflict: the dry-run said the product gets inserted
after generation from real-product-v1, yet the prompt asked the AI to
render a complete, finished liner. That invites exactly the ghost/double-
product risk this revision removes: AI draws its own liner, real-product-v1
lands on top of it, and the AI's version can still show through at the
edges, or hands end up gripping the AI liner instead of where the real
handle tabs will be.

Root cause we're avoiding (same lesson as CALL 1 HANDS V1-V4, see
scene-05-hands-experiment-retrospective.md): don't ask the API to get a
product-shaped thing right when a deterministic compositor already knows
the exact answer. Product-placement-plate applies that lesson to
mode=generate too, not just mode=edit:
  - mode="generate" (plain text-to-image, NOT "edit") -- still no
    reference images, no mask, nothing for the model to violate;
  - the model_prompt sent to the API asks for a PLATE: kitchen, air
    fryer, clean basket, hands positioned as if about to lift something,
    an explicitly EMPTY placement area -- and explicitly instructs the
    model NOT to draw a completed silicone liner, redesigned handles, or
    a duplicate tray/insert;
  - real-product-v1 is inserted afterward via the existing compositor
    (layer_compositor.compose + product_lock_validator.validate_composite)
    at the fixed screen position defined by APPROVED_TRANSFORM_B;
  - if the AI drew a product-like shape anyway despite the instruction not
    to, QA gate "no_duplicate_ai_product_visible" rejects the candidate;
    the canonical layer overwriting that region does NOT waive this check,
    because a visible AI double/ghost at the edges is itself a defect.

model_prompt vs pipeline_product_lock_instruction (kept structurally
separate, never merged into one string):
  - model_prompt: the ONLY thing sent to the API. Frames the product
    purely as a negative instruction ("leave this area clean, don't draw
    a liner here") -- never a request to render the product faithfully,
    because the model cannot render real-product-v1 faithfully and
    shouldn't be asked to try.
  - pipeline_product_lock_instruction: internal documentation for the
    compositor/QA gates (exact geometry that the REAL inserted layer must
    match). Never sent to the API. Exposed separately in every report so
    the two are never confused with each other again.

Product-guide (passing real-product-v1 as an "edit" reference/placement
guide) remains rejected: it would reintroduce mode="edit" multipart
complexity and reference-image dependence for zero benefit, since the
compositor already knows exactly where to place the product regardless of
any guide image.

Honesty about what's NOT implemented yet: front_hand extraction (pulling
just the AI-drawn fingers/sleeve pixels that should sit ON TOP of the
real handle tabs, the way scene-05-hands-experiment-retrospective.md's V3
tried and partially got working) is NOT implemented in this runner. Every
report says so explicitly (front_hand_extraction: "not_implemented") --
this is never silently assumed to work.

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
COMPOSITE_APPROACH = "product_placement_plate"

MODEL = "gpt-image-2"
SIZE = "720x1280"
OUTPUT_FORMAT = "png"
N = 1
RETRIES = 0
MAX_CALLS = 1
HARD_CAP_USD = 0.50
PRICE_PER_IMAGE_USD_ESTIMATE = 0.30

# Явный, честный статус: пока НЕ реализовано в этом runner'е (см. docstring
# модуля). Никогда не обещается по умолчанию.
FRONT_HAND_EXTRACTION_STATUS = "not_implemented"

PLACEMENT_NOTE = (
    "The final silicone form is inserted after generation from "
    "real-product-v1. Do not invent or redesign the product. Leave the "
    "product placement area clean."
)

# Порядок шагов composite mechanics ПОСЛЕ будущей генерации (ничего из этого
# ещё не выполнено -- ни один API-вызов этим runner'ом не делался).
COMPOSITE_MECHANICS_STEPS = (
    "1. raw AI plate (kitchen/hands/basket/placement area) сохраняется как есть",
    "2. real-product-v1 вставляется через APPROVED_TRANSFORM_B (deterministic compositing, layer_compositor.compose)",
    "3. front_hand extraction (палец/рукав поверх handle tabs) НЕ реализована в этом runner'е -- см. front_hand_extraction ниже",
    "4. если руки закрыты продуктом целиком или не взаимодействуют с handle tabs -- candidate reject",
    "5. если AI нарисовал собственную форму/лоток/вставку несмотря на PLACEMENT_NOTE -- candidate reject (no_duplicate_ai_product_visible)",
)

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
    {"id": 11, "name": "no_duplicate_ai_product_visible", "check": "AI не нарисовал собственную силиконовую форму/вставку в placement area несмотря на PLACEMENT_NOTE — если нарисовал, candidate reject даже после наложения real-product-v1"},
    {"id": 12, "name": "no_ai_tray_under_real_product", "check": "под/вокруг вставленного real-product-v1 не виден край AI-сгенерированного лотка/подложки-двойника"},
    {"id": 13, "name": "no_fake_handles_visible", "check": "AI не нарисовал собственные (redesigned/fake) ручки — видны только реальные ручки real-product-v1 после compositing"},
    {"id": 14, "name": "hands_positioned_near_real_handle_tabs", "check": "руки на AI-plate расположены достаточно близко к позиции реальных flat corner handle tabs (APPROVED_TRANSFORM_B), чтобы после вставки товара выглядеть держащими именно ручки"},
    {"id": 15, "name": "candidate_rejected_if_product_overlay_breaks_hands", "check": "если наложение real-product-v1 перекрывает руки так, что хват выглядит неестественно/оторванно (палец в воздухе, рука без видимой точки опоры) — candidate reject"},
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
    model_prompt: str
    prompt_sha256: str
    pipeline_product_lock_instruction: str
    model: str
    endpoint: str
    mode: str
    size: str
    n: int
    output_format: str
    retries: int
    max_calls: int
    hard_cap_usd: float


def build_model_prompt(plan: dict) -> str:
    """Собирает ТОЛЬКО то, что реально отправляется в OpenAI: continuity
    block + сцено-специфичный action (уже описывающий placement plate, не
    финальный товар) + PLACEMENT_NOTE (негативная инструкция "не рисуй
    товар, оставь место чистым" -- НЕ просьба нарисовать его достоверно) +
    negative prompt. plan['product_lock_instruction'] СОЗНАТЕЛЬНО сюда НЕ
    входит -- см. build_pipeline_product_lock_instruction()."""
    parts = [
        plan["continuity_block_text"].strip(),
        plan["scene_action_prompt"].strip(),
        PLACEMENT_NOTE,
        f"Negative prompt (avoid): {plan['negative_prompt'].strip()}",
    ]
    return "\n\n".join(p for p in parts if p)


def build_pipeline_product_lock_instruction(plan: dict) -> str:
    """Возвращает pipeline-only инструкцию (геометрия/материал товара для
    компоситора и QA). НИКОГДА не отправляется модели -- используется
    только runner'ом/QA/compositor'ом после генерации."""
    return plan["product_lock_instruction"].strip()


def build_request_contract(campaign_dir, scene_id: str) -> tuple[ImageRequest, SceneRequestContract, dict]:
    """Строит ImageRequest + контракт для отчёта. НИКОГДА не читает
    campaign_visual_lock.json и не резолвит appearance asset_id — весь
    prompt приходит из plan_scene_request() (product_only_policy.py),
    reference_images всегда пуст (product-placement-plate, mode=generate).

    model_prompt (то, что уходит в API) и pipeline_product_lock_instruction
    (то, что использует только наш компоситор/QA) строятся и хранятся
    РАЗДЕЛЬНО -- pipeline-инструкция никогда не попадает в текст, который
    видит модель."""
    plan = plan_scene_request(campaign_dir, scene_id)  # fail-closed само по себе
    model_prompt = build_model_prompt(plan)
    pipeline_instruction = build_pipeline_product_lock_instruction(plan)
    prompt_sha256 = hashlib.sha256(model_prompt.encode("utf-8")).hexdigest()

    req = ImageRequest(
        scene_id=scene_id, prompt=model_prompt, n=N, size=SIZE,
        mode="generate", reference_images=[], output_format=OUTPUT_FORMAT,
    )
    contract = SceneRequestContract(
        scene_id=scene_id, model_prompt=model_prompt, prompt_sha256=prompt_sha256,
        pipeline_product_lock_instruction=pipeline_instruction,
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
            "model_prompt": contract.model_prompt,
        },
        "pipeline_product_lock_instruction": contract.pipeline_product_lock_instruction,
        "pipeline_product_lock_instruction_note": ("НЕ отправляется модели как просьба рисовать "
                                                    "товар -- используется только compositor/QA "
                                                    "ПОСЛЕ генерации. Модель видит только "
                                                    "PLACEMENT_NOTE внутри model_prompt (см. выше)."),
        "results": [r.to_dict() for r in results],
        "budget": tracker.summary(),
        "openai_calls_executed": 1 if apply else 0,
        "higgsfield_calls_executed": 0,
        "food_calls_executed": 0,
        "api_spend_usd": tracker.total_actual() if apply else 0,
        "qa_gates": list(QA_GATES),
        "manual_review_required": True,
        "front_hand_extraction": FRONT_HAND_EXTRACTION_STATUS,
        "front_hand_extraction_risk": ("hands may be partially covered by product layer -- "
                                      "front_hand extraction (палец/рукав поверх handle tabs) "
                                      "НЕ реализована в этом runner'е; вставка real-product-v1 "
                                      "может визуально перекрыть руки на AI-plate без коррекции."),
        "composite_mechanics": {
            "steps": list(COMPOSITE_MECHANICS_STEPS),
            "compositor": "api/media_pipeline/compositor/layer_compositor.py:compose",
            "validator": "api/media_pipeline/compositor/product_lock_validator.py:validate_composite",
            "product_transform": "api/media_pipeline/compositor/scene05_baseplate.py:APPROVED_TRANSFORM_B",
            "not_yet_executed": True,
        },
        "next_step": ("planned_product_lock_composite: real-product-v1 через "
                     "APPROVED_TRANSFORM_B поверх этого AI-plate, затем "
                     "product_lock_validator.validate_composite — отдельный "
                     "локальный шаг без API, ещё не выполнен."),
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(out_dir) / f"{scene_id}-product-only-{'apply' if apply else 'dry-run'}-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
