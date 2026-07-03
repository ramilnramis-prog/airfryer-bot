"""Учёт расходов конвейера: estimate до вызова, hard cap, фактический usage.

Правила:
- перед КАЖДЫМ платным вызовом — check(category, estimate): если cap уже
  достигнут или estimate его превысит, вызов не выполняется (BudgetStop);
- оценки (estimated_spend_usd) копятся только при реальных вызовах (apply);
- actual_spend_usd копится, когда usage ответа позволяет посчитать
  (задана таблица цен токенов); иначе usage сохраняется сырым;
- image generation и vision evaluation учитываются раздельно;
- никаких автоматических retries: этот модуль не повторяет вызовы, и
  провайдеры конвейера не должны (первый пилот — max_retries=0 by design).
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetStop(RuntimeError):
    """Достигнут/будет превышен hard cap — немедленная остановка до следующего запроса."""


CATEGORIES = ("image_generation", "vision_evaluation")


@dataclass
class SpendTracker:
    cap_usd: float
    # {category: usd}
    estimated: dict = field(default_factory=lambda: {c: 0.0 for c in CATEGORIES})
    actual: dict = field(default_factory=lambda: {c: 0.0 for c in CATEGORIES})
    # True, пока ВСЕ реальные вызовы категории дали считаемый actual
    actual_complete: dict = field(default_factory=lambda: {c: True for c in CATEGORIES})
    usage_log: list = field(default_factory=list)

    # -- контроль ---------------------------------------------------------

    def total_estimated(self) -> float:
        return round(sum(self.estimated.values()), 4)

    def total_actual(self) -> float:
        return round(sum(self.actual.values()), 4)

    def check(self, category: str, estimate_usd: float) -> None:
        """Вызвать ПЕРЕД платным запросом. Бросает BudgetStop при нарушении cap."""
        if category not in self.estimated:
            raise ValueError(f"unknown spend category: {category}")
        spent = self.total_estimated()
        if spent >= self.cap_usd:
            raise BudgetStop(
                f"hard cap ${self.cap_usd} уже достигнут (estimated ${spent}) — "
                "следующий запрос запрещён")
        if spent + estimate_usd > self.cap_usd:
            raise BudgetStop(
                f"запрос ~${round(estimate_usd, 4)} превысит hard cap "
                f"${self.cap_usd} (estimated ${spent})")

    # -- учёт ---------------------------------------------------------------

    def record(self, category: str, estimate_usd: float,
               usage: dict | None = None,
               actual_usd: float | None = None) -> None:
        """Вызвать ПОСЛЕ реального (apply) вызова."""
        self.estimated[category] = round(self.estimated[category] + estimate_usd, 4)
        if usage is not None or actual_usd is not None:
            self.usage_log.append(
                {"category": category, "estimate_usd": round(estimate_usd, 4),
                 "usage": usage, "actual_usd": actual_usd})
        if actual_usd is not None:
            self.actual[category] = round(self.actual[category] + actual_usd, 4)
        else:
            self.actual_complete[category] = False

    def summary(self) -> dict:
        return {
            "cap_usd": self.cap_usd,
            "estimated_spend_usd": {**self.estimated, "total": self.total_estimated()},
            "actual_spend_usd": {
                **self.actual, "total": self.total_actual(),
                "complete": all(self.actual_complete.values()),
            },
            "calls_logged": len(self.usage_log),
        }


def actual_from_usage(usage: dict | None, token_prices: dict | None) -> float | None:
    """usage → USD, если заданы цены. token_prices: {"input_per_1m": x,
    "output_per_1m": y, "image_output_per_1m": z} (USD за 1M токенов)."""
    if not usage or not token_prices:
        return None
    total = 0.0
    known = False
    pairs = [("input_tokens", "input_per_1m"),
             ("output_tokens", "output_per_1m"),
             ("image_output_tokens", "image_output_per_1m")]
    for ukey, pkey in pairs:
        if ukey in usage and pkey in token_prices:
            total += usage[ukey] / 1_000_000 * token_prices[pkey]
            known = True
    return round(total, 6) if known else None
