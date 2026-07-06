"""Product-reference-only generation runner (scene-05, "product_reference_only_v1").

Owner decision after scene-05 C1/C2/C3 (all three local deterministic
compositing attempts kept producing seams/artifacts regardless of transform
accuracy, see scene-05-generation-attempts-status.json): PRODUCT ONLY MEANS
PRODUCT ONLY. real-product-v1 is the ONLY permanent visual reference in this
project. This runner does NOT paste real-product-v1 pixels onto a generated
plate via deterministic compositing (that mechanism is what produced the
seams). Instead it uploads a real photo of the product as the model's ONLY
image reference (mode="edit", one image, no mask) and describes everything
else -- kitchen, air fryer, basket, food -- in plain text. The model
attempts its own likeness of the product guided by that reference; how well
it matches real-product-v1 is a QA question (QA_GATES_PRODUCT_REFERENCE_ONLY
below), not something this runner enforces by construction the way
product_lock_validator does for the old compositing path.

TASK 1 finding (this module only became possible because of it): the
existing OpenAIImagesProvider.generate() ALREADY supports mode="edit" with
reference_images=[<path>] and no mask (see
api/media_pipeline/openai_images_client.py -- files = [("image[]", ref,
Path(ref).read_bytes()) for ref in request.reference_images], mask_path is
optional). No new API surface was invented for this module; it reuses the
existing edit-mode request path.

No network calls happen unless run_product_reference_only_scene(...,
apply=True) is called. Fail-closed: apply=True without OPENAI_API_KEY, or
with max_calls/retries misconfigured, raises before any network call --
same contract as product_only_scene_runner.py.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .budget import SpendTracker
from .models import ImageRequest
from .openai_images_client import (IMAGE_GENERATION_TIMEOUT_ENV_VAR,
                                   OpenAIImagesProvider,
                                   resolve_image_generation_timeout_seconds)

CANDIDATE_LABEL = "product_reference_only_v1"
SCENE_VARIANT = "no_hands_result_shot"
PRODUCT_REFERENCE_MODE = "real_product_reference_only"

MODEL = "gpt-image-2"
SIZE = "720x1280"
OUTPUT_FORMAT = "png"
N = 1
RETRIES = 0
MAX_CALLS = 1
HARD_CAP_USD = 0.50
PRICE_PER_IMAGE_USD_ESTIMATE = 0.30
MODE = "edit"

# The ONLY image reference this runner ever sends to the API: a real,
# unmodified photo crop of real-product-v1 (RGB, no alpha -- avoids any
# alpha-as-implicit-mask ambiguity in the /images/edits endpoint). Never an
# isolated/cutout asset, never a C1/C2/C3 output, never a generated plate.
PRODUCT_REFERENCE_IMAGE_PATH = (
    "assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_45deg_master.png")

MODEL_PROMPT = (
    "Cozy clean white home kitchen, warm daylight from the left. Black air "
    "fryer with open square basket, high 3/4 top-down camera angle. Inside "
    "the basket is the same silicone form as the only reference image: "
    "dark grey matte square silicone air fryer liner, flat corner handle "
    "tabs, short horizontal slots in the tabs, ribbed bottom. Inside the "
    "form are exactly 3 roasted golden chicken thighs with potato wedges. "
    "The air fryer basket is clean around the form. No hands, no arms, no "
    "fingers, no person. Realistic home cooking photo, DSLR 50mm look, "
    "vertical 9:16, 720x1280. No text, no watermark, no logo."
)

NEGATIVE_PROMPT = (
    "redesigned handles, loop handles, vertical oval holes, duplicate tray, "
    "second product, black extra insert, hands, fingers, person, text, "
    "watermark, logo, CGI, illustration, 3D render."
)

FULL_MODEL_PROMPT = MODEL_PROMPT + "\n\nNegative prompt (avoid): " + NEGATIVE_PROMPT

# Documents the owner's policy (campaign_visual_policy.json:
# forbidden_global_reference_categories) at the point of use -- nothing
# here is ever passed as an image reference or resolved from a file.
FORBIDDEN_REFERENCE_SOURCES = (
    "C1", "C2", "C3",
    "generated_plates", "previous_candidate_composites",
    "kitchen", "air_fryer", "basket", "food",
    "hands", "person", "clothing", "lighting",
)

QA_GATES_PRODUCT_REFERENCE_ONLY = (
    {"id": 1, "name": "only_real_product_v1_used_as_image_reference",
     "check": "reference_images содержит РОВНО один элемент -- real-product-v1 master crop; ничего из FORBIDDEN_REFERENCE_SOURCES"},
    {"id": 2, "name": "no_generated_plate_used_as_reference",
     "check": "ни один AI-сгенерированный plate (C1/C2/C3 или любой другой) не использован как image reference"},
    {"id": 3, "name": "no_c1_c2_c3_png_referenced",
     "check": "ни один путь generated/product-only-scene/scene-05/scene-05-c[123]*.png не встречается ни в запросе, ни в отчёте как reference"},
    {"id": 4, "name": "product_visually_matches_real_product_v1",
     "check": "square dark grey matte silicone, flat corner handle tabs, short horizontal handle slots, ribbed bottom; no loop handles; no vertical oval holes"},
    {"id": 5, "name": "food_count_exact",
     "check": "ровно 3 куриных бедра + картофельные дольки"},
    {"id": 6, "name": "no_hands_no_person",
     "check": "нет рук/человека в кадре"},
    {"id": 7, "name": "basket_clean_around_product",
     "check": "корзина аэрогриля чистая вокруг товара"},
    {"id": 8, "name": "no_duplicate_tray_or_second_product",
     "check": "нет дублирующего лотка/второго товара"},
    {"id": 9, "name": "no_text_or_watermark",
     "check": "нет текста/watermark/логотипа в кадре"},
    {"id": 10, "name": "manual_review_required",
     "check": "manual_review_required: true -- accepted никогда не проставляется автоматически"},
)


# -- v2: multi-product-reference (owner clarification after v1 apply) -----
# Owner narrowed the allowed reference set further: ONLY images that show
# the silicone form itself (real-v1/product + real-v1/handles + real-v1/
# bottom) may ever be used as a reference. Anything showing the air fryer
# body, the basket, or a human hand (real-v1/airfryer/*, real-v1/motion/*)
# is forbidden as a reference, even though those files also live under
# product-lock/real-v1 -- they are scene/environment/hand content, not the
# product. v2 uses FOUR product-only reference images instead of v1's one.
CANDIDATE_LABEL_V2 = "product_reference_only_v2"
PRODUCT_REFERENCE_MODE_V2 = "multi_product_reference_only"

# symbolic asset_id -> actual file path. Every path here shows ONLY the
# silicone form (no air fryer body, no basket, no hand) -- verified by
# direct visual inspection before being added (see the product reference
# audit that preceded this module).
PRODUCT_REFERENCE_ASSET_PATHS = {
    "real-product-v1:product_45deg_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_45deg_master.png",
    "real-product-v1:product_top_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_top_master.png",
    "real-product-v1:product_full_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_full_master.png",
    "real-product-v1:left_handle_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/handles/left_handle_master.png",
    "real-product-v1:right_handle_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/handles/right_handle_master.png",
    "real-product-v1:both_handles_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/handles/both_handles_master.png",
    "real-product-v1:bottom_loop_master":
        "assets/product-lock/airfryer-silicone-form/references/real-v1/bottom/bottom_loop_master.png",
}

# Explicitly forbidden even though they live under product-lock/real-v1 --
# air fryer body, basket, or a human hand is visible in these photos.
FORBIDDEN_PRODUCT_LOCK_ASSETS = (
    "real-v1/airfryer/airfryer_front_master.png",
    "real-v1/airfryer/clean_basket_master.png",
    "real-v1/motion/product_in_basket_master.png",
    "real-v1/motion/grip_motion_master.png",
)

# v2 uses exactly these four -- the two full-body product views (3/4 and
# top) plus the two product-part close-ups (handles, bottom) that were
# explicitly approved by the owner for this revision.
PRODUCT_REFERENCE_IMAGES_V2 = (
    "real-product-v1:product_45deg_master",
    "real-product-v1:product_top_master",
    "real-product-v1:both_handles_master",
    "real-product-v1:bottom_loop_master",
)

MODEL_PROMPT_V2 = (
    "Cozy clean white home kitchen, warm daylight from the left. Black air "
    "fryer with open square basket, high 3/4 top-down camera angle. Inside "
    "the basket is the same silicone form shown in the product reference "
    "images: square dark grey matte silicone air fryer liner, flat corner "
    "handle tabs, short horizontal slots in the tabs, ribbed bottom. Keep "
    "the form shape and handle geometry faithful to the product "
    "references. Inside the form are exactly 3 roasted golden chicken "
    "thighs with potato wedges. The air fryer basket is clean around the "
    "form. No hands, no arms, no fingers, no person. Realistic home "
    "cooking photo, DSLR 50mm look, vertical 9:16, 720x1280. No text, no "
    "watermark, no logo."
)

NEGATIVE_PROMPT_V2 = (
    "redesigned handles, loop handles, vertical oval holes, duplicate tray, "
    "second product, black extra insert, hands, fingers, person, text, "
    "watermark, logo, CGI, illustration, 3D render."
)

FULL_MODEL_PROMPT_V2 = MODEL_PROMPT_V2 + "\n\nNegative prompt (avoid): " + NEGATIVE_PROMPT_V2

QA_GATES_PRODUCT_REFERENCE_ONLY_V2 = (
    {"id": 1, "name": "only_product_references_used",
     "check": "reference_images содержит ТОЛЬКО изображения из PRODUCT_REFERENCE_ASSET_PATHS (силиконовая форма), ничего из FORBIDDEN_PRODUCT_LOCK_ASSETS/FORBIDDEN_REFERENCE_SOURCES"},
    {"id": 2, "name": "reference_images_length_exactly_4",
     "check": "reference_images содержит РОВНО 4 элемента"},
    {"id": 3, "name": "every_reference_under_real_v1_product_only",
     "check": "каждый reference image находится под real-v1/(product|handles|bottom) и показывает ТОЛЬКО товар"},
    {"id": 4, "name": "no_airfryer_basket_motion_generated_refs",
     "check": "нет airfryer/basket/motion референсов (real-v1/airfryer/*, real-v1/motion/*) и нет generated/ референсов"},
    {"id": 5, "name": "no_c1_c2_c3_refs",
     "check": "нет ссылок на scene-05-c1/c2/c3 или любой previous candidate"},
    {"id": 6, "name": "product_visually_matches_references",
     "check": "square dark grey matte silicone, flat corner handle tabs, short horizontal handle slots, ribbed bottom; no loop handles; no vertical oval holes"},
    {"id": 7, "name": "food_count_exact",
     "check": "ровно 3 куриных бедра + картофельные дольки"},
    {"id": 8, "name": "no_hands_no_person",
     "check": "нет рук/человека в кадре"},
    {"id": 9, "name": "basket_clean_around_product",
     "check": "корзина аэрогриля чистая вокруг товара"},
    {"id": 10, "name": "no_duplicate_product_or_tray",
     "check": "нет дублирующего товара/лотка"},
    {"id": 11, "name": "realistic_photo",
     "check": "реалистичное фото, не CGI/иллюстрация/3D render"},
    {"id": 12, "name": "no_text_or_watermark",
     "check": "нет текста/watermark/логотипа в кадре"},
    {"id": 13, "name": "manual_review_required",
     "check": "manual_review_required: true -- accepted никогда не проставляется автоматически"},
)


class ProductReferenceOnlyRunnerError(RuntimeError):
    """Fail-closed: конфигурация --apply некорректна (нет ключа, hard cap не
    задан, max_calls/retries не по контракту, reference image отсутствует
    или не единственный) -- бросается ДО сети."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ProductReferenceOnlyContract:
    scene_id: str
    model_prompt: str
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
    reference_images: tuple


def build_request_contract(campaign_dir, scene_id: str = "scene-05",
                           repo_root: str = ".") -> tuple[ImageRequest, ProductReferenceOnlyContract]:
    """Строит ImageRequest (mode='edit', РОВНО один reference image --
    real-product-v1 master crop) + контракт для отчёта. Никогда не читает
    C1/C2/C3 generated outputs, campaign_visual_lock.json, video-continuity-
    block.md -- FULL_MODEL_PROMPT самодостаточен (не собирается из старой
    continuity-block машинерии C1/C2/C3)."""
    reference_path = str(Path(repo_root) / PRODUCT_REFERENCE_IMAGE_PATH)
    if not Path(reference_path).is_file():
        raise ProductReferenceOnlyRunnerError(
            "PRODUCT_REFERENCE_IMAGE_MISSING",
            f"{reference_path} не найден -- real-product-v1 master crop обязателен")

    prompt_sha256 = hashlib.sha256(FULL_MODEL_PROMPT.encode("utf-8")).hexdigest()

    req = ImageRequest(
        scene_id=scene_id, prompt=FULL_MODEL_PROMPT, n=N, size=SIZE,
        mode=MODE, reference_images=[reference_path], output_format=OUTPUT_FORMAT,
    )
    contract = ProductReferenceOnlyContract(
        scene_id=scene_id, model_prompt=FULL_MODEL_PROMPT, prompt_sha256=prompt_sha256,
        model=MODEL, endpoint="/images/edits", mode=MODE,
        size=SIZE, n=N, output_format=OUTPUT_FORMAT, retries=RETRIES,
        max_calls=MAX_CALLS, hard_cap_usd=HARD_CAP_USD,
        reference_images=(PRODUCT_REFERENCE_IMAGE_PATH,),
    )
    return req, contract


@dataclass(frozen=True)
class ProductReferenceOnlyContractV2:
    scene_id: str
    model_prompt: str
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
    reference_images: tuple           # symbolic asset_ids
    reference_image_paths: tuple      # resolved file paths, same order


def build_request_contract_v2(campaign_dir, scene_id: str = "scene-05",
                              repo_root: str = ".") -> tuple[ImageRequest, ProductReferenceOnlyContractV2]:
    """Строит ImageRequest (mode='edit', РОВНО 4 reference images -- только
    product/handles/bottom real-v1 crops) + контракт для отчёта. Никогда не
    резолвит airfryer/basket/motion/generated assets -- reference_images
    строится ИСКЛЮЧИТЕЛЬНО из PRODUCT_REFERENCE_IMAGES_V2 (allow-list),
    никогда из произвольного пути."""
    resolved_paths = []
    for asset_id in PRODUCT_REFERENCE_IMAGES_V2:
        rel_path = PRODUCT_REFERENCE_ASSET_PATHS[asset_id]
        full_path = str(Path(repo_root) / rel_path)
        if not Path(full_path).is_file():
            raise ProductReferenceOnlyRunnerError(
                "PRODUCT_REFERENCE_IMAGE_MISSING", f"{full_path} не найден ({asset_id})")
        resolved_paths.append(full_path)

    prompt_sha256 = hashlib.sha256(FULL_MODEL_PROMPT_V2.encode("utf-8")).hexdigest()

    req = ImageRequest(
        scene_id=scene_id, prompt=FULL_MODEL_PROMPT_V2, n=N, size=SIZE,
        mode=MODE, reference_images=resolved_paths, output_format=OUTPUT_FORMAT,
    )
    contract = ProductReferenceOnlyContractV2(
        scene_id=scene_id, model_prompt=FULL_MODEL_PROMPT_V2, prompt_sha256=prompt_sha256,
        model=MODEL, endpoint="/images/edits", mode=MODE,
        size=SIZE, n=N, output_format=OUTPUT_FORMAT, retries=RETRIES,
        max_calls=MAX_CALLS, hard_cap_usd=HARD_CAP_USD,
        reference_images=PRODUCT_REFERENCE_IMAGES_V2,
        reference_image_paths=tuple(resolved_paths),
    )
    return req, contract


def run_product_reference_only_scene_v2(campaign_dir, scene_id: str = "scene-05",
                                        apply: bool = False, out_dir=None,
                                        repo_root: str = ".") -> dict:
    """v2 entry point: РОВНО один реальный вызов (n=1, retries=0,
    max_calls=1, hard cap $0.50) через mode='edit' с 4 product-only
    reference images (product_45deg, product_top, both_handles,
    bottom_loop). Тот же fail-closed контракт, что и v1."""
    req, contract = build_request_contract_v2(campaign_dir, scene_id, repo_root)

    if apply:
        if MAX_CALLS != 1:
            raise ProductReferenceOnlyRunnerError(
                "MAX_CALLS_VIOLATION", f"max_calls={MAX_CALLS} != 1 -- apply запрещён")
        if RETRIES != 0:
            raise ProductReferenceOnlyRunnerError(
                "RETRIES_VIOLATION", f"retries={RETRIES} != 0 -- apply запрещён")
        if HARD_CAP_USD <= 0:
            raise ProductReferenceOnlyRunnerError(
                "HARD_CAP_NOT_SET", "hard_cap_usd должен быть > 0 для apply")
        if len(req.reference_images) != 4:
            raise ProductReferenceOnlyRunnerError(
                "REFERENCE_IMAGES_NOT_EXACTLY_FOUR",
                f"reference_images={req.reference_images!r} -- ожидается ровно 4")
        for p in req.reference_images:
            if "generated" in Path(p).parts or "airfryer" in Path(p).parts or "motion" in Path(p).parts:
                raise ProductReferenceOnlyRunnerError(
                    "FORBIDDEN_REFERENCE_SOURCE", f"{p} не является разрешённым product-only reference")
        # OPENAI_API_KEY проверяется ДО сети самим OpenAIImagesProvider._api_key()
        # при apply=True (MissingAPIKeyError).

    timeout_seconds, timeout_warnings = resolve_image_generation_timeout_seconds()
    tracker = SpendTracker(cap_usd=HARD_CAP_USD)
    provider = OpenAIImagesProvider(model=MODEL, tracker=tracker,
                                    price_per_image_usd=PRICE_PER_IMAGE_USD_ESTIMATE,
                                    timeout_seconds=timeout_seconds)

    out_dir = str(out_dir) if out_dir else str(
        Path(campaign_dir) / "generated" / "product-reference-only-scene-v2" / scene_id)

    try:
        results = provider.generate(req, out_dir=out_dir, apply=apply)
    except TimeoutError as e:
        report = {
            "candidate_label": CANDIDATE_LABEL_V2,
            "scene_variant": SCENE_VARIANT,
            "product_reference_mode": PRODUCT_REFERENCE_MODE_V2,
            "scene_id": scene_id,
            "mode": "apply" if apply else "dry-run",
            "error_type": "client_read_timeout",
            "error_message": str(e),
            "request_sent": True,
            "response_received": False,
            "openai_call_attempted": True,
            "retry_attempted": False,
            "actual_cost_known": False,
            "candidate_status": "no_candidate_timeout",
            "image_generation_timeout_seconds": timeout_seconds,
            "timeout_env_var": IMAGE_GENERATION_TIMEOUT_ENV_VAR,
            "auto_retry_on_timeout": False,
            "openai_calls_executed": 1,
            "higgsfield_calls_executed": 0,
            "api_spend_usd": None,
            "budget": tracker.summary(),
            "manual_review_required": True,
        }
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / f"{scene_id}-product-reference-only-v2-apply-timeout-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    report = {
        "candidate_label": CANDIDATE_LABEL_V2,
        "scene_variant": SCENE_VARIANT,
        "product_reference_mode": PRODUCT_REFERENCE_MODE_V2,
        "scene_id": scene_id,
        "mode": "apply" if apply else "dry-run",
        "no_hands_prompt": True,
        "model_prompt_clean": True,
        "uses_campaign_visual_lock": False,
        "uses_reference_library_for_appearance": False,
        "forbidden_reference_sources": list(FORBIDDEN_REFERENCE_SOURCES),
        "forbidden_product_lock_assets": list(FORBIDDEN_PRODUCT_LOCK_ASSETS),
        "request_contract": {
            "model": contract.model, "endpoint": contract.endpoint,
            "mode": contract.mode, "size": contract.size, "n": contract.n,
            "output_format": contract.output_format, "retries": contract.retries,
            "max_calls": contract.max_calls, "hard_cap_usd": contract.hard_cap_usd,
            "prompt_sha256": contract.prompt_sha256,
            "reference_images": list(contract.reference_images),
            "reference_image_paths": list(contract.reference_image_paths),
            "model_prompt": contract.model_prompt,
        },
        "results": [r.to_dict() for r in results],
        "budget": tracker.summary(),
        "openai_calls_executed": 1 if apply else 0,
        "higgsfield_calls_executed": 0,
        "api_spend_usd": tracker.total_actual() if apply else 0,
        "image_generation_timeout_seconds": timeout_seconds,
        "timeout_env_var": IMAGE_GENERATION_TIMEOUT_ENV_VAR,
        "image_generation_timeout_warnings": timeout_warnings,
        "auto_retry_on_timeout": False,
        "qa_gates": list(QA_GATES_PRODUCT_REFERENCE_ONLY_V2),
        "manual_review_required": True,
        "candidate_status_note": "future apply must set candidate_status to pending_manual_review or rejected -- never accepted automatically.",
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(out_dir) / f"{scene_id}-product-reference-only-v2-{'apply' if apply else 'dry-run'}-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def run_product_reference_only_scene(campaign_dir, scene_id: str = "scene-05",
                                     apply: bool = False, out_dir=None,
                                     repo_root: str = ".") -> dict:
    """Единственный entry point product-reference-only генерации.

    apply=False (default): ТОЛЬКО планирование, 0 сетевых вызовов,
    api_spend=0 -- работает даже без OPENAI_API_KEY.

    apply=True: РОВНО один реальный вызов (n=1, retries=0, max_calls=1,
    hard cap $0.50) через mode='edit' с real-product-v1 как единственным
    reference image. Требует OPENAI_API_KEY. Падает ДО сети
    (ProductReferenceOnlyRunnerError/MissingAPIKeyError), если что-то из
    контракта не соблюдено."""
    req, contract = build_request_contract(campaign_dir, scene_id, repo_root)

    if apply:
        if MAX_CALLS != 1:
            raise ProductReferenceOnlyRunnerError(
                "MAX_CALLS_VIOLATION", f"max_calls={MAX_CALLS} != 1 -- apply запрещён")
        if RETRIES != 0:
            raise ProductReferenceOnlyRunnerError(
                "RETRIES_VIOLATION", f"retries={RETRIES} != 0 -- apply запрещён")
        if HARD_CAP_USD <= 0:
            raise ProductReferenceOnlyRunnerError(
                "HARD_CAP_NOT_SET", "hard_cap_usd должен быть > 0 для apply")
        if len(req.reference_images) != 1:
            raise ProductReferenceOnlyRunnerError(
                "REFERENCE_IMAGES_NOT_EXACTLY_ONE",
                f"reference_images={req.reference_images!r} -- ожидается ровно 1 (real-product-v1)")
        # OPENAI_API_KEY проверяется ДО сети самим OpenAIImagesProvider._api_key()
        # при apply=True (MissingAPIKeyError).

    timeout_seconds, timeout_warnings = resolve_image_generation_timeout_seconds()
    tracker = SpendTracker(cap_usd=HARD_CAP_USD)
    provider = OpenAIImagesProvider(model=MODEL, tracker=tracker,
                                    price_per_image_usd=PRICE_PER_IMAGE_USD_ESTIMATE,
                                    timeout_seconds=timeout_seconds)

    out_dir = str(out_dir) if out_dir else str(
        Path(campaign_dir) / "generated" / "product-reference-only-scene" / scene_id)

    try:
        results = provider.generate(req, out_dir=out_dir, apply=apply)
    except TimeoutError as e:
        report = {
            "candidate_label": CANDIDATE_LABEL,
            "scene_variant": SCENE_VARIANT,
            "product_reference_mode": PRODUCT_REFERENCE_MODE,
            "scene_id": scene_id,
            "mode": "apply" if apply else "dry-run",
            "error_type": "client_read_timeout",
            "error_message": str(e),
            "request_sent": True,
            "response_received": False,
            "openai_call_attempted": True,
            "retry_attempted": False,
            "actual_cost_known": False,
            "candidate_status": "no_candidate_timeout",
            "image_generation_timeout_seconds": timeout_seconds,
            "timeout_env_var": IMAGE_GENERATION_TIMEOUT_ENV_VAR,
            "auto_retry_on_timeout": False,
            "openai_calls_executed": 1,
            "higgsfield_calls_executed": 0,
            "api_spend_usd": None,
            "budget": tracker.summary(),
            "manual_review_required": True,
        }
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / f"{scene_id}-product-reference-only-apply-timeout-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    report = {
        "candidate_label": CANDIDATE_LABEL,
        "scene_variant": SCENE_VARIANT,
        "product_reference_mode": PRODUCT_REFERENCE_MODE,
        "scene_id": scene_id,
        "mode": "apply" if apply else "dry-run",
        "no_hands_prompt": True,
        "model_prompt_clean": True,
        "uses_campaign_visual_lock": False,
        "uses_reference_library_for_appearance": False,
        "forbidden_reference_sources": list(FORBIDDEN_REFERENCE_SOURCES),
        "request_contract": {
            "model": contract.model, "endpoint": contract.endpoint,
            "mode": contract.mode, "size": contract.size, "n": contract.n,
            "output_format": contract.output_format, "retries": contract.retries,
            "max_calls": contract.max_calls, "hard_cap_usd": contract.hard_cap_usd,
            "prompt_sha256": contract.prompt_sha256,
            "reference_images": list(contract.reference_images),
            "model_prompt": contract.model_prompt,
        },
        "results": [r.to_dict() for r in results],
        "budget": tracker.summary(),
        "openai_calls_executed": 1 if apply else 0,
        "higgsfield_calls_executed": 0,
        "api_spend_usd": tracker.total_actual() if apply else 0,
        "image_generation_timeout_seconds": timeout_seconds,
        "timeout_env_var": IMAGE_GENERATION_TIMEOUT_ENV_VAR,
        "image_generation_timeout_warnings": timeout_warnings,
        "auto_retry_on_timeout": False,
        "qa_gates": list(QA_GATES_PRODUCT_REFERENCE_ONLY),
        "manual_review_required": True,
        "candidate_status_note": "future apply must set candidate_status to pending_manual_review or rejected -- never accepted automatically.",
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(out_dir) / f"{scene_id}-product-reference-only-{'apply' if apply else 'dry-run'}-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
