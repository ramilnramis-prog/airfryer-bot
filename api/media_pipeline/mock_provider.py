"""Mock-провайдер для локальной проверки конвейера без сети и без трат.

Сценарий задаётся заранее: для каждой сцены и раунда — список наблюдений
кандидатов (как будто их уже посмотрел visual-director). Используется в тестах
и в `cli.py generate --provider mock`.
"""
from __future__ import annotations

from .models import ImageProvider, ImageRequest, ImageResult


class MockImageProvider(ImageProvider):
    name = "mock"
    model = "mock-image-1"

    def __init__(self, scenario: dict | None = None):
        """scenario: {scene_id: [round1_observations, round2_observations, ...]},
        где roundN_observations — list[dict] наблюдений кандидатов."""
        self.scenario = scenario or {}
        self._round_by_scene = {}
        self.calls = []

    def generate(self, request: ImageRequest, out_dir: str,
                 apply: bool = False) -> list:
        self.calls.append({"scene_id": request.scene_id, "n": request.n,
                           "apply": apply, "prompt": request.prompt})
        rnd = self._round_by_scene.get(request.scene_id, 0)
        self._round_by_scene[request.scene_id] = rnd + 1
        rounds = self.scenario.get(request.scene_id, [])
        observations = rounds[rnd] if rnd < len(rounds) else []
        results = []
        for i in range(request.n):
            cid = f"{request.scene_id}-r{rnd + 1}-c{i + 1}"
            obs = dict(observations[i]) if i < len(observations) else {}
            obs.setdefault("candidate_id", cid)
            results.append(ImageResult(
                candidate_id=cid, scene_id=request.scene_id,
                provider=self.name, model=self.model,
                prompt=request.prompt, dry_run=not apply,
                image_path=None,
                planned_request={"mock_observation": obs},
            ))
        return results
