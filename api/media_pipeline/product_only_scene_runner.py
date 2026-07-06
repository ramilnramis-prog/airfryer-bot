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

# Food extraction РЕАЛИЗОВАНА (extract_food_cluster() ниже) -- механизм
# детерминирован и покрыт тестами на синтетическом plate (реального
# AI-plate ещё не существует, т.к. --apply ни разу не выполнялся). Если
# этот статус когда-нибудь понижается обратно до "not_implemented",
# run_product_only_scene() блокирует --apply тем же способом, что и
# MAX_CALLS/RETRIES -- см. FOOD_EXTRACTION_NOT_IMPLEMENTED ниже.
FOOD_EXTRACTION_STATUS = "implemented"

PLACEMENT_NOTE = (
    "The final silicone form is inserted after generation from "
    "real-product-v1. Do not invent or redesign the product. Leave the "
    "product placement area clean."
)

# -- no-hands scene variant (C3, see scene-05 C1/C2 rejection) --------------
# The shared video-continuity-block.md text is written for scenes that DO
# show hands (it positively instructs "Same woman's natural hands
# throughout... Same grey ribbed sweater sleeves visible at the wrists").
# For a no_hands_result_shot scene, sending that text to the model and then
# separately saying "no hands, no person" is a self-contradictory prompt
# (positive hands/sleeves instruction immediately followed by its own
# negation). NO_HANDS_CONTINUITY_PROMPT is the same continuity text with
# every hands/person/sleeve-positive line removed -- used INSTEAD of
# plan['clean_continuity_prompt'] for this scene variant, never appended to
# it, so no "override" sentence is ever needed in the scene-specific prompt.
NO_HANDS_CONTINUITY_PROMPT = (
    "Cozy clean white home kitchen, warm daylight coming from the left. "
    "Same black air fryer with an open square basket in every shot. "
    "Realistic home cooking photo, DSLR 50mm look, shallow depth of field. "
    "No CGI, no illustration, no 3D render. No text, no watermark, no logo. "
    "Vertical 9:16, 720×1280."
)

# Порядок шагов composite mechanics ПОСЛЕ будущей генерации (ничего из этого
# ещё не выполнено -- ни один API-вызов этим runner'ом не делался).
COMPOSITE_MECHANICS_STEPS = (
    "1. raw AI plate (kitchen/hands/basket/placement area/rough food cluster) сохраняется как есть",
    "2. real-product-v1 base/exterior вставляется через APPROVED_TRANSFORM_B (deterministic compositing, layer_compositor.compose)",
    "3. food cluster извлекается из AI plate СТРОГО внутри product_interior_food_mask (extract_food_cluster(), детерминированная геометрия из real-product-v1, не из AI) и композитится внутрь товара",
    "4. product front occluder / rim / handle pixels из real-product-v1 перерисовываются поверх еды (закрывают края, без новых пикселей товара)",
    "5. front_hand extraction (палец/рукав поверх handle tabs) НЕ реализована в этом runner'е -- см. front_hand_extraction ниже",
    "6. если руки закрыты продуктом целиком или не взаимодействуют с handle tabs -- candidate reject",
    "7. если AI нарисовал собственную форму/лоток/вставку несмотря на PLACEMENT_NOTE -- candidate reject (no_duplicate_ai_product_visible)",
    "8. QA: food_count_exact -- если AI не нарисовал ровно 3 бедра, candidate reject/manual_review_required (extraction сам не считает еду, это отдельная visual QA проверка)",
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


# -- C2: plate-specific geometry compatibility (see scene-05 C1/V2 rejection) -
# C1's AI plate used a frontal basket with level left/right hand tabs;
# real-product-v1/product_45deg is a 3/4-angle photo with asymmetric handle
# heights (left higher, right lower). No rigid transform (uniform scale +
# small rotation + translation, no warp) can reconcile a level-handle plate
# with that asset -- fitting one handle always throws the other far off (see
# scene-05-qa-report-v2.json). C2 asks the AI plate itself to match
# product_45deg's perspective/handle asymmetry up front, so APPROVED_TRANSFORM_B
# (or a small rigid nudge within its limits) applies directly instead of
# requiring a bespoke per-plate transform.
CANDIDATE_LABEL_C2 = "C2"
PER_PLATE_TRANSFORM_ALLOWED = True
ALLOWED_TRANSFORM_TYPE = "rigid_only"


def get_expected_plate_geometry_c2(repo_root: str = ".") -> dict:
    """Geometry compatibility targets for a C2 AI plate, derived from the
    REAL product mask/handle masks + APPROVED_TRANSFORM_B (never invented by
    hand) -- the same deterministic path scene05_layer_masks already uses for
    QA/compositing. A future AI plate is compatible with product_45deg when
    its own basket/hand geometry roughly matches these regions."""
    from .compositor.product_assets import DEFAULT_VIEW
    from .compositor.scene05_baseplate import APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B
    from .compositor.scene05_layer_masks import build_all_layer_masks

    masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                  APPROVED_CANVAS_SIZE, repo_root)
    return {
        "camera_angle": "high_3_4_top_down",
        "expected_product_axis": "upper_left_to_lower_right",
        "left_future_handle_region": list(masks["left_handle_bbox"]),
        "right_future_handle_region": list(masks["right_handle_bbox"]),
        "basket_region_target": list(masks["product_full_bbox"]),
        "product_interior_food_mask_bbox": list(masks["product_interior_food_mask"].getbbox() or ()),
        "source": ("api/media_pipeline/compositor/scene05_layer_masks.py:build_all_layer_masks "
                  "with DEFAULT_VIEW (product_45deg) + APPROVED_TRANSFORM_B -- regions are "
                  "computed from the real product asset, not invented"),
        "reject_if_handles_level": True,
        "reject_if_basket_frontal": True,
        "reject_if_black_insert_drawn": True,
    }


# -- C2 pre-composite geometry QA (STEP 3): evaluated on the raw AI plate
# BEFORE attempting any local transform/compositing. Distinct from QA_GATES
# above (which judge the finished composite) -- these fail fast so a
# geometrically incompatible plate is rejected without spending time on a
# transform salvage attempt that (per C1/V2) cannot succeed against a
# mismatched plate.
QA_GATES_C2_GEOMETRY_PRECHECK = (
    {"id": "c2-1", "name": "basket_perspective_matches_product_45deg",
     "stage": "precheck_before_transform_salvage",
     "check": "AI plate camera angle reads as high 3/4 top-down (not frontal), compatible with the product_45deg photo angle"},
    {"id": "c2-2", "name": "future_handle_regions_asymmetric",
     "stage": "precheck_before_transform_salvage",
     "check": "left future handle position is visibly higher in frame than the right (matches left_future_handle_region vs right_future_handle_region)"},
    {"id": "c2-3", "name": "no_level_left_right_tabs",
     "stage": "precheck_before_transform_salvage",
     "check": "left/right hand or tab positions are NOT at the same height -- a level pair is the exact C1 failure mode, reject immediately"},
    {"id": "c2-4", "name": "no_black_insert_or_liner_in_basket",
     "stage": "precheck_before_transform_salvage",
     "check": "no AI-drawn black container/liner/tray shape occupies the basket interior (same defect that caused C1 duplicate_ai_product_visible)"},
    {"id": "c2-5", "name": "ai_plate_has_clean_empty_product_area",
     "stage": "precheck_before_transform_salvage",
     "check": "central placement area is empty/clean aside from the rough food cluster -- no pre-drawn product silhouette"},
    {"id": "c2-6", "name": "hands_near_expected_asymmetric_handle_regions",
     "stage": "precheck_before_transform_salvage",
     "check": "left/right hands sit close to left_future_handle_region / right_future_handle_region from get_expected_plate_geometry_c2()"},
)


# -- C3: no-hands result shot (see scene-05 C1/C2 rejection) ---------------
# C1 (frontal/level tabs) and C2 (high 3/4/asymmetric tabs) both showed that
# generated hands do not reliably align with real-product-v1 after
# deterministic overlay -- correct front/back occlusion around a hand
# gripping a handle tab is an occlusion-compositing problem, not something a
# prompt revision alone can fix. C3 drops the hands-lifting-by-handles
# concept entirely: scene-05 becomes a no-hands product result shot (food
# cooked in the form, clean basket), so no front-hand extraction and no
# handle-grip alignment QA are needed for this scene variant.
CANDIDATE_LABEL_C3 = "C3"
SCENE_VARIANT_C3 = "no_hands_result_shot"
FRONT_HAND_EXTRACTION_STATUS_C3 = "not_needed"
HANDS_GRIP_QA_C3 = "not_applicable"

# C3 QA gates (STEP 5): hands_interact_with_flat_tabs,
# hands_positioned_near_real_handle_tabs and
# candidate_rejected_if_product_overlay_breaks_hands from the general
# QA_GATES above do not apply to this no-hands scene variant -- they are
# simply absent here rather than kept and marked not_applicable, since this
# is a separate, scene-variant-specific gate list (QA_GATES itself, used by
# other scenes/candidates, is unchanged).
QA_GATES_C3_NO_HANDS = (
    {"id": "c3-1", "name": "no_hands_visible",
     "check": "нет рук в кадре — сцена больше не показывает захват ручек"},
    {"id": "c3-2", "name": "no_person_visible",
     "check": "нет человека/частей тела в кадре — чистый product result shot"},
    {"id": "c3-3", "name": "no_duplicate_ai_product_visible",
     "check": "AI не нарисовал собственную силиконовую форму/вставку в placement area — если нарисовал, candidate reject даже после наложения real-product-v1"},
    {"id": "c3-4", "name": "no_black_insert_or_black_liner",
     "check": "AI не нарисовал чёрный insert/liner/container внутри корзины"},
    {"id": "c3-5", "name": "no_fake_handles_visible",
     "check": "AI не нарисовал собственные (redesigned/fake) ручки — видны только реальные ручки real-product-v1 после compositing"},
    {"id": "c3-6", "name": "basket_perspective_compatible_with_product_45deg",
     "check": "ракурс корзины совместим с product_45deg (high 3/4 top-down, корзина в верхней/средней части кадра)"},
    {"id": "c3-7", "name": "product_inserted_from_real_product_v1",
     "check": "real-product-v1 вставлен через APPROVED_TRANSFORM_B (или rigid per-plate transform в тех же пределах), не пропущен"},
    {"id": "c3-8", "name": "product_lock_passed",
     "check": "product_lock_validator.validate_composite: silhouette, handle_geometry, aspect_ratio, pixel_similarity, no_local_warp"},
    {"id": "c3-9", "name": "food_extracted_only_inside_interior_mask",
     "check": "food cluster извлечён из AI plate ТОЛЬКО внутри product_interior_food_mask"},
    {"id": "c3-10", "name": "food_count_exact",
     "check": "визуально ровно 3 куриных бедра + картофельные дольки"},
    {"id": "c3-11", "name": "basket_clean_around_product",
     "check": "корзина аэрогриля чистая вокруг/под вставленным real-product-v1"},
    {"id": "c3-12", "name": "no_text_or_watermark",
     "check": "нет текста/watermark/логотипа в кадре"},
    {"id": "c3-13", "name": "manual_review_required",
     "check": "manual_review_required: true — accepted никогда не проставляется автоматически"},
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
    """Собирает ТОЛЬКО то, что реально отправляется в OpenAI: ЧИСТЫЙ
    continuity prompt (plan['clean_continuity_prompt'] -- уже распарсен
    product_only_policy.parse_clean_continuity_prompt() из blockquote в
    video-continuity-block.md, БЕЗ markdown-заголовков/русской
    документации/file paths -- ИСПРАВЛЕНО: раньше сюда по ошибке попадал
    plan['continuity_block_text'], весь исходный .md целиком) + сцено-
    специфичный action (описывающий placement plate, не финальный товар) +
    PLACEMENT_NOTE (негативная инструкция "не рисуй товар, оставь место
    чистым" -- НЕ просьба нарисовать его достоверно) + negative prompt.
    plan['product_lock_instruction'] СОЗНАТЕЛЬНО сюда НЕ входит -- см.
    build_pipeline_product_lock_instruction().

    scene_variant == 'no_hands_result_shot' (C3): shared continuity text
    positively instructs hands/sleeves ("Same woman's natural hands
    throughout... Same grey ribbed sweater sleeves visible at the wrists"),
    which would contradict a scene that must show no hands/person at all --
    NO_HANDS_CONTINUITY_PROMPT (hands/sleeves lines removed) is used INSTEAD
    of plan['clean_continuity_prompt'] for this variant, so the scene action
    text never needs to "override" an earlier positive hands instruction."""
    continuity = (NO_HANDS_CONTINUITY_PROMPT
                 if plan.get("scene_variant") == SCENE_VARIANT_C3
                 else plan["clean_continuity_prompt"])
    parts = [
        continuity.strip(),
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


def get_product_interior_food_mask_info(repo_root: str = ".") -> dict:
    """Геометрия product_interior_food_mask -- ДЕТЕРМИНИРОВАННАЯ (эрозия
    реального силуэта real-product-v1 через APPROVED_TRANSFORM_B), НЕ
    зависит от того, что нарисовал AI. Та же функция, что уже используется
    scene05_layer_masks для остальных слоёв сцены-05 -- ничего нового не
    изобретается для food extraction."""
    from .compositor.product_assets import DEFAULT_VIEW
    from .compositor.scene05_baseplate import APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B
    from .compositor.scene05_layer_masks import build_all_layer_masks

    masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                  APPROVED_CANVAS_SIZE, repo_root)
    interior_mask = masks["product_interior_food_mask"]
    bbox = interior_mask.getbbox()
    return {
        "canvas_size": list(APPROVED_CANVAS_SIZE),
        "bbox": list(bbox) if bbox else None,
        "mask_source": ("api/media_pipeline/compositor/scene05_layer_masks.py:"
                        "product_interior_food_mask (deterministic, from "
                        "real-product-v1 geometry via APPROVED_TRANSFORM_B, "
                        "NOT from the AI plate)"),
    }


def extract_food_cluster(ai_plate_path, repo_root: str = ".", out_path=None):
    """Извлекает ТОЛЬКО пиксели AI plate внутри product_interior_food_mask
    (реальная геометрия товара из real-product-v1, не AI-угаданная и не
    зависящая от того, что AI фактически нарисовал). Силикон/ручки/стенки/
    фон НИКОГДА не попадают в результат -- маска строго ограничивает
    вырезку внутренней областью формы, тем же путём, что уже используется
    для остальных слоёв сцены-05 (scene05_layer_masks).

    Возвращает RGBA PIL.Image (alpha=255 внутри interior mask, 0 снаружи).
    Не считает и не проверяет количество еды -- это отдельная visual QA
    (food_count_exact gate), а не часть extraction."""
    from PIL import Image
    import numpy as np

    from .compositor.product_assets import DEFAULT_VIEW
    from .compositor.scene05_baseplate import APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B
    from .compositor.scene05_layer_masks import build_all_layer_masks

    masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                  APPROVED_CANVAS_SIZE, repo_root)
    interior_mask = masks["product_interior_food_mask"]

    plate = Image.open(ai_plate_path).convert("RGB")
    if plate.size != tuple(APPROVED_CANVAS_SIZE):
        raise ProductOnlyRunnerError(
            "FOOD_EXTRACTION_SIZE_MISMATCH",
            f"AI plate size {plate.size} != {tuple(APPROVED_CANVAS_SIZE)}")

    plate_arr = np.asarray(plate)
    mask_arr = np.asarray(interior_mask)
    inside = mask_arr > 128

    rgba = np.zeros((*plate_arr.shape[:2], 4), dtype=np.uint8)
    rgba[..., :3][inside] = plate_arr[inside]
    rgba[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
    food_layer = Image.fromarray(rgba, "RGBA")
    if out_path:
        food_layer.save(out_path)
    return food_layer


def _build_food_composite_strategy(repo_root: str = ".") -> dict:
    return {
        "food_extraction": FOOD_EXTRACTION_STATUS,
        "method": ("extract_food_cluster(): AI plate pixels restricted to "
                  "product_interior_food_mask (deterministic geometry from "
                  "real-product-v1 + APPROVED_TRANSFORM_B, NOT AI-guessed) -- "
                  "silicone/handles/walls/background NEVER taken from AI"),
        "mask_function": "api/media_pipeline/compositor/scene05_layer_masks.py:product_interior_food_mask",
        "product_interior_food_mask": get_product_interior_food_mask_info(repo_root),
        "final_composite_order": [
            "1. AI plate background/hands/basket (raw; everything outside the interior mask is discarded for food purposes)",
            "2. real-product-v1 base/exterior inserted via APPROVED_TRANSFORM_B",
            "3. extracted food cluster (AI plate pixels masked to product_interior_food_mask) composited inside the product",
            "4. product front occluder / rim / handle pixels from real-product-v1 redrawn on top (covers food edges, same real pixels, no new product pixels)",
            "5. QA: food_count_exact (exactly 3 chicken thighs) -- if AI did not draw exactly 3, candidate reject / manual_review_required",
        ],
        "if_ai_did_not_draw_exactly_3_thighs": ("candidate_status=manual_review_required / "
                                                "rejected -- QA gate food_count_exact catches "
                                                "this; the extraction mechanism itself does "
                                                "not count or validate food count (that's a "
                                                "vision QA step, not implemented here)"),
    }


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
        if FOOD_EXTRACTION_STATUS != "implemented":
            raise ProductOnlyRunnerError(
                "FOOD_EXTRACTION_NOT_IMPLEMENTED",
                "food_extraction не реализован -- apply заблокирован, "
                "QA gate food_count_exact невозможно выполнить без "
                "извлечения food cluster из будущего AI plate")
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
        "food_extraction": FOOD_EXTRACTION_STATUS,
        # repo_root="." -- product-lock assets резолвятся от корня репозитория,
        # НЕ от campaign_dir (тот же default, что и у compositor-функций).
        "food_composite_strategy": _build_food_composite_strategy(),
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
