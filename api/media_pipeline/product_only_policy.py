"""Product-only visual reference policy: typed loader/validator + planner.

После scene-05-hands-experiment-retrospective.md (CALL 1 HANDS V1-V4
rejected) кампания coating-protect-2026-07 перешла на policy, где
ЕДИНСТВЕННЫЙ обязательный image lock — real-product-v1
(campaign_visual_policy.json, policy_version "product-only-v1"). Всё
остальное (руки/персонаж/кухня/аэрогриль/одежда/свет) — текстовый
continuity block, не image reference.

Этот модуль — единственный код, который читает campaign_visual_policy.json
и решает, действует ли product-only режим для кампании. Он ничего не
резолвит через reference library и ничего не генерирует — только читает
локальные файлы и валидирует/планирует.

Fail-closed: любая попытка прочитать невалидный policy-файл, или найти
запрещённый appearance asset_id как mandatory reference в scene prompts,
бросает ProductOnlyPolicyError ДО того, как что-либо может быть передано
в generation planner.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

POLICY_FILENAME = "campaign_visual_policy.json"
CONTINUITY_FILENAME = "video-continuity-block.md"
SCENE_PROMPTS_FILENAME = "video-scene-prompts-product-only.md"

# Заголовок, под которым в video-continuity-block.md лежит ЕДИНСТВЕННЫЙ
# кусок текста, который реально годится для отправки в image API (чистый
# английский prompt, blockquote). Всё остальное в этом .md -- русская
# документация/заголовки/file paths -- НИКОГДА не должно попасть в API.
CONTINUITY_PROMPT_HEADING_MARKER = "## Текст блока"

REQUIRED_POLICY_VERSION = "product-only-v1"
REQUIRED_PRODUCT_CANON = "real-product-v1"
REQUIRED_CONTINUITY_SOURCE = "text_prompt_block"

# Запрещённые appearance/mechanics/style asset_id из отклонённого
# reference-based эксперимента (campaign_visual_lock.json). Ни один из них
# не должен резолвиться и не должен встречаться как mandatory reference в
# product-only planning/prompts.
FORBIDDEN_APPEARANCE_ASSET_IDS = (
    "person-b-exhausted-01",
    "real-grip-motion-01",
    "v2-hand-hold-01",
    "v2-form-in-basket-01",
    "food-wings-01",
)

REQUIRED_NOT_IMAGE_LOCKED_CATEGORIES = (
    "hands", "person", "kitchen", "airfryer", "clothing", "lighting",
)

SCENE_SECTION_RE = re.compile(r"\n## (scene-\d\d)\n")
SCENE_FIELD_RE = re.compile(
    r"-\s+\*\*([a-zA-Z_]+)\*\*:\s*(.+?)(?=\n-\s+\*\*[a-zA-Z_]+\*\*:|\Z)", re.DOTALL)


class ProductOnlyPolicyError(RuntimeError):
    """Fail-closed: policy отсутствует/некорректна, ИЛИ запрещённый appearance
    asset_id найден как mandatory reference. code — одно из:
    POLICY_NOT_FOUND, POLICY_VERSION_MISMATCH, PRODUCT_CANON_MISMATCH,
    CONTINUITY_SOURCE_MISMATCH, MISSING_CONTINUITY_FILE,
    MISSING_SCENE_PROMPTS_FILE, FORBIDDEN_APPEARANCE_REF_FOUND,
    BLOCKED_BY_PRODUCT_ONLY_POLICY, SCENE_NOT_FOUND,
    CONTINUITY_PROMPT_BLOCK_NOT_FOUND, CONTINUITY_PROMPT_BLOCK_EMPTY,
    CONTINUITY_PROMPT_BLOCK_NOT_CLEAN."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ProductOnlyPolicy:
    campaign_code: str
    content_code: str
    product_canon: str
    product_manifest: str
    not_image_locked: tuple
    continuity_source: str
    continuity_block_text: str
    clean_continuity_prompt: str
    scene_prompts_text: str
    policy_path: Path
    raw: dict = field(repr=False)


def parse_clean_continuity_prompt(continuity_block_text: str) -> str:
    """Извлекает ТОЛЬКО чистый английский prompt (blockquote) из
    video-continuity-block.md -- строго между заголовком
    CONTINUITY_PROMPT_HEADING_MARKER и следующим '##' заголовком. Никакой
    русской документации/заголовков/file paths в результате быть не должно
    -- это и есть то немногое, что реально годится для отправки в image API.

    Формат источника (см. video-continuity-block.md):
        ## Текст блока (вставляется в каждый scene prompt дословно)

        > Cozy clean white home kitchen, ...
        > ... Vertical 9:16, 720×1280.

        ## Правила применения
        ...
    """
    lines = continuity_block_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(CONTINUITY_PROMPT_HEADING_MARKER):
            start = i + 1
            break
    if start is None:
        raise ProductOnlyPolicyError(
            "CONTINUITY_PROMPT_BLOCK_NOT_FOUND",
            f"не найден заголовок {CONTINUITY_PROMPT_HEADING_MARKER!r} "
            "в video-continuity-block.md")

    quote_lines = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped.startswith(">"):
            quote_lines.append(stripped.lstrip(">").strip())

    clean = " ".join(quote_lines).strip()
    if not clean:
        raise ProductOnlyPolicyError(
            "CONTINUITY_PROMPT_BLOCK_EMPTY",
            "clean continuity prompt пуст после парсинга blockquote")
    if "#" in clean or "```" in clean:
        raise ProductOnlyPolicyError(
            "CONTINUITY_PROMPT_BLOCK_NOT_CLEAN",
            "clean continuity prompt содержит markdown-артефакты после парсинга")
    return clean


def _policy_path(campaign_dir) -> Path:
    return Path(campaign_dir) / POLICY_FILENAME


def is_product_only_campaign(campaign_dir) -> bool:
    """Дешёвая проверка без полной валидации: есть ли policy-файл вообще."""
    return _policy_path(campaign_dir).is_file()


def assert_no_forbidden_appearance_refs(text: str, source_label: str) -> None:
    """Fail-closed пункт 9: ни один запрещённый appearance asset_id не может
    встречаться как mandatory reference в тексте (continuity block, scene
    prompts, request contract)."""
    for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
        if asset_id in text:
            raise ProductOnlyPolicyError(
                "FORBIDDEN_APPEARANCE_REF_FOUND",
                f"{source_label} ссылается на запрещённый appearance asset_id "
                f"{asset_id!r} — product-only policy запрещает это как mandatory reference")


def load_product_only_policy(campaign_dir, required: bool = False) -> ProductOnlyPolicy | None:
    """Читает + валидирует campaign_visual_policy.json. Возвращает None, если
    файла нет и required=False (значит кампания НЕ на product-only policy —
    вызывающий код должен использовать старый путь). Если required=True и
    файла нет — fail-closed (ProductOnlyPolicyError).

    Валидация (fail-closed на каждом шаге, пункты 2,3,5,8,9 из ТЗ):
    - policy_version == 'product-only-v1'
    - global_visual_reference.product_canon == 'real-product-v1'
    - continuity_source == 'text_prompt_block'
    - continuity block и scene prompts файлы существуют и читаются
    - scene prompts НЕ содержат запрещённые appearance asset_id
    """
    campaign_dir = Path(campaign_dir)
    policy_path = _policy_path(campaign_dir)
    if not policy_path.is_file():
        if required:
            raise ProductOnlyPolicyError(
                "POLICY_NOT_FOUND", f"{policy_path} не найден")
        return None

    raw = json.loads(policy_path.read_text(encoding="utf-8"))

    if raw.get("policy_version") != REQUIRED_POLICY_VERSION:
        raise ProductOnlyPolicyError(
            "POLICY_VERSION_MISMATCH",
            f"{policy_path}: policy_version={raw.get('policy_version')!r} != "
            f"{REQUIRED_POLICY_VERSION!r}")

    product_canon = raw.get("global_visual_reference", {}).get("product_canon")
    if product_canon != REQUIRED_PRODUCT_CANON:
        raise ProductOnlyPolicyError(
            "PRODUCT_CANON_MISMATCH",
            f"{policy_path}: global_visual_reference.product_canon={product_canon!r} != "
            f"{REQUIRED_PRODUCT_CANON!r}")

    if raw.get("continuity_source") != REQUIRED_CONTINUITY_SOURCE:
        raise ProductOnlyPolicyError(
            "CONTINUITY_SOURCE_MISMATCH",
            f"{policy_path}: continuity_source={raw.get('continuity_source')!r} != "
            f"{REQUIRED_CONTINUITY_SOURCE!r}")

    continuity_path = campaign_dir / CONTINUITY_FILENAME
    if not continuity_path.is_file():
        raise ProductOnlyPolicyError(
            "MISSING_CONTINUITY_FILE", f"{continuity_path} не найден")
    continuity_text = continuity_path.read_text(encoding="utf-8")

    scene_prompts_path = campaign_dir / SCENE_PROMPTS_FILENAME
    if not scene_prompts_path.is_file():
        raise ProductOnlyPolicyError(
            "MISSING_SCENE_PROMPTS_FILE", f"{scene_prompts_path} не найден")
    scene_prompts_text = scene_prompts_path.read_text(encoding="utf-8")

    assert_no_forbidden_appearance_refs(continuity_text, str(continuity_path))
    assert_no_forbidden_appearance_refs(scene_prompts_text, str(scene_prompts_path))

    clean_continuity_prompt = parse_clean_continuity_prompt(continuity_text)
    assert_no_forbidden_appearance_refs(clean_continuity_prompt, f"{continuity_path} (clean prompt)")

    not_image_locked = tuple(raw.get("not_image_locked", ()))
    for category in REQUIRED_NOT_IMAGE_LOCKED_CATEGORIES:
        if category not in not_image_locked:
            raise ProductOnlyPolicyError(
                "PRODUCT_CANON_MISMATCH",
                f"{policy_path}: not_image_locked не содержит обязательную "
                f"категорию {category!r}")

    return ProductOnlyPolicy(
        campaign_code=raw["campaign_code"],
        content_code=raw["content_code"],
        product_canon=product_canon,
        product_manifest=raw["global_visual_reference"]["product_manifest"],
        not_image_locked=not_image_locked,
        continuity_source=raw["continuity_source"],
        continuity_block_text=continuity_text,
        clean_continuity_prompt=clean_continuity_prompt,
        scene_prompts_text=scene_prompts_text,
        policy_path=policy_path,
        raw=raw,
    )


def assert_legacy_generation_allowed(campaign_dir) -> None:
    """Гейт для СТАРОГО image-based generation пути (cli.py cmd_pilot/
    cmd_generate — тот же код, что запускал бы CALL 1 HANDS-стиль вызовы
    через scene-specs required_references). Если для campaign_dir активна
    product-only policy — этот путь ЗАБЛОКИРОВАН безусловно (dry-run и
    apply одинаково), т.к. scene-specs/*.json для этой кампании всё ещё
    ссылаются на старые image refs (hands/kitchen), которые product-only
    policy запрещает как mandatory references."""
    if is_product_only_campaign(campaign_dir):
        policy = load_product_only_policy(campaign_dir, required=True)
        raise ProductOnlyPolicyError(
            "BLOCKED_BY_PRODUCT_ONLY_POLICY",
            f"campaign {policy.campaign_code!r} использует product-only-v1 "
            f"({policy.policy_path}) — старый image-based generation путь "
            "(scene-specs required_references, appearance image refs) "
            "заблокирован для этой кампании. Используй product-only planning "
            f"({SCENE_PROMPTS_FILENAME} + real-product-v1 compositing) вместо этого.")


def parse_scene_prompts(scene_prompts_text: str) -> dict:
    """Парсит video-scene-prompts-product-only.md в {scene_id: {field: value}}.
    Чисто текстовый парсинг (никакого AI/сети) по формату '## scene-NN' +
    '- **field**: value' — тот же формат, что уже проверяют тесты."""
    parts = SCENE_SECTION_RE.split("\n" + scene_prompts_text)
    scenes = {}
    for scene_id, body in zip(parts[1::2], parts[2::2]):
        fields = {}
        for m in SCENE_FIELD_RE.finditer(body):
            key, value = m.group(1), m.group(2).strip()
            fields[key] = value
        scenes[scene_id] = fields
    return scenes


def plan_scene_request(campaign_dir, scene_id: str) -> dict:
    """Единственный планировщик generation-запроса для product-only режима.

    Возвращает request-contract dict: product_canon вставляется
    deterministically (never AI), appearance/hands/kitchen/airfryer image
    refs — ВСЕГДА пустые списки, continuity текст подставлен из
    video-continuity-block.md, product_lock_instruction обязателен.
    Fail-closed, если policy отсутствует/невалидна или сцена не найдена.
    Ничего не генерирует и не вызывает сеть — чистое планирование."""
    policy = load_product_only_policy(campaign_dir, required=True)
    scenes = parse_scene_prompts(policy.scene_prompts_text)
    if scene_id not in scenes:
        raise ProductOnlyPolicyError(
            "SCENE_NOT_FOUND",
            f"{scene_id} не найден в {SCENE_PROMPTS_FILENAME} "
            f"(доступны: {sorted(scenes)})")
    scene = scenes[scene_id]
    if "product_lock_instruction" not in scene:
        raise ProductOnlyPolicyError(
            "FORBIDDEN_APPEARANCE_REF_FOUND",  # схема требует поле для КАЖДОЙ сцены
            f"{scene_id}: отсутствует обязательное поле product_lock_instruction")
    assert_no_forbidden_appearance_refs(json.dumps(scene, ensure_ascii=False), scene_id)

    return {
        "generation_mode": "product_only",
        "scene_id": scene_id,
        "campaign_code": policy.campaign_code,
        "content_code": policy.content_code,
        "uses_campaign_visual_lock": False,
        "uses_reference_library_for_appearance": False,
        "global_visual_reference": policy.product_canon,
        "refs_passed_in_order": [
            {"role": "product_canon", "source": policy.product_canon,
             "manifest": policy.product_manifest,
             "resolution": "repository_only (never reference library)"},
        ],
        "appearance_image_refs": [],
        "hands_image_refs": [],
        "kitchen_image_refs": [],
        "airfryer_image_refs": [],
        "continuity_block_text": policy.continuity_block_text,
        "clean_continuity_prompt": policy.clean_continuity_prompt,
        "scene_goal": scene.get("scene_goal", ""),
        "scene_variant": scene.get("scene_variant", ""),
        "scene_action_prompt": scene.get("image_prompt", ""),
        "product_lock_instruction": scene.get("product_lock_instruction", ""),
        "negative_prompt": scene.get("negative_prompt", ""),
        "hooks_usage": scene.get("hooks_usage", ""),
        "openai_calls_executed": 0,
        "higgsfield_calls_executed": 0,
        "food_calls_executed": 0,
        "api_spend_usd": 0,
    }
