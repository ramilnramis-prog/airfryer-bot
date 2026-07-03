"""Автоматизированный визуальный конвейер кампаний (см. VISUAL_AUTOMATION_PIPELINE.md).

Идея → storyboard → 3 кандидата на сцену (OpenAI Images API) → hard-fail QA →
scoring → один победитель или regeneration brief → sequence QA → гейт Higgsfield.

Безопасность: dry-run по умолчанию, реальные API-вызовы только с --apply,
OPENAI_API_KEY только из environment и никогда не логируется/не сохраняется.
Только stdlib (паттерн api/import_metrics_via_api.py) — новых зависимостей нет.
"""
