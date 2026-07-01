"""Тесты api/import_metrics_via_api.py — пакетный клиент поверх существующего
HTTP API реестра (без изменений схемы/endpoint'ов).

Никакие внешние сети/production API не вызываются: поднимаем ЛОКАЛЬНЫЙ
тестовый HTTP-сервер (stdlib http.server) на эфемерном порту, который
имитирует только два уже существующих маршрута:
  GET  /registry/publications/{code}/summary
  POST /registry/metric-snapshots

Запуск из папки telegram-bot-registry-integration/:
    python -m unittest api.tests.test_import_metrics_via_api -v
"""
import io
import os
import json
import http.server
import tempfile
import threading
import contextlib
import unittest

from api import import_metrics_via_api as M


class _Handler(http.server.BaseHTTPRequestHandler):
    """Мини-заглушка /registry/* с состоянием на классе (сбрасывается в setUp)."""

    publications = {}   # publication_code -> {"publication": {...}, "channel": {...}}
    snapshots = {}       # (publication_id, source, captured_at) -> row
    api_key = "test-key"
    next_id = 1
    post_calls = 0

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return self.headers.get("X-API-Key") == self.__class__.api_key

    def do_GET(self):
        if not self._auth_ok():
            self._json(401, {"detail": "Invalid or missing X-API-Key"})
            return
        prefix, suffix = "/registry/publications/", "/summary"
        if self.path.startswith(prefix) and self.path.endswith(suffix):
            code = self.path[len(prefix):-len(suffix)]
            entry = self.__class__.publications.get(code)
            if not entry:
                self._json(404, {"detail": "publication not found"})
                return
            self._json(200, entry)
            return
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        cls = self.__class__
        if not self._auth_ok():
            self._json(401, {"detail": "Invalid or missing X-API-Key"})
            return
        if self.path != "/registry/metric-snapshots":
            self._json(404, {"detail": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        cls.post_calls += 1
        key = (payload.get("publication_id"), payload.get("source"), payload.get("captured_at"))
        if key in cls.snapshots:
            self._json(200, {"created": False, "metric_snapshot": cls.snapshots[key]})
            return
        row = {"id": cls.next_id, **payload}
        cls.next_id += 1
        cls.snapshots[key] = row
        self._json(200, {"created": True, "metric_snapshot": row})

    def log_message(self, format, *args):
        pass  # тихо — не засорять вывод тестов


def _valid_batch(captured_at="2026-07-02T18:30:00Z"):
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "snapshots": [
            {"publication_code": "video2-forma-ad-youtube_shorts-A-v1",
             "source": "youtube_shorts", "views": 100, "likes": 10,
             "comments": 1, "shares": None, "saves": None},
        ],
    }


class ImportMetricsViaApiTests(unittest.TestCase):
    def setUp(self):
        _Handler.publications = {
            "video2-forma-ad-youtube_shorts-A-v1": {
                "publication": {"id": 1, "publication_code": "video2-forma-ad-youtube_shorts-A-v1"},
                "channel": {"code": "youtube_shorts"},
            },
            "video2-forma-ad-tiktok-A-v1": {
                "publication": {"id": 2, "publication_code": "video2-forma-ad-tiktok-A-v1"},
                "channel": {"code": "tiktok"},
            },
        }
        _Handler.snapshots = {}
        _Handler.api_key = "test-key"
        _Handler.next_id = 1
        _Handler.post_calls = 0

        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self._env_backup = os.environ.get("API_KEY")
        os.environ["API_KEY"] = "test-key"

        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self._env_backup is None:
            os.environ.pop("API_KEY", None)
        else:
            os.environ["API_KEY"] = self._env_backup

    def _write_batch(self, data, name="batch.json"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = M.main(argv)
        return rc, out.getvalue(), err.getvalue()

    # ---- dry-run ничего не отправляет ----
    def test_dry_run_sends_nothing(self):
        path = self._write_batch(_valid_batch())
        rc, out, err = self._run([path, "--base-url", self.base_url])
        self.assertEqual(rc, 0)
        self.assertEqual(_Handler.post_calls, 0)
        self.assertIn("dry-run", out)

    # ---- publication_code -> publication_id ----
    def test_publication_code_resolves_to_publication_id(self):
        data = _valid_batch()
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(errors, [])
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["publication_id"], 1)

    # ---- отрицательная метрика отклоняется ----
    def test_negative_metric_rejected(self):
        data = _valid_batch()
        data["snapshots"][0]["views"] = -5
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(planned, [])
        self.assertTrue(any("отрицательные" in e for e in errors))
        self.assertEqual(_Handler.post_calls, 0)

    # ---- source другого канала отклоняется ----
    def test_source_channel_mismatch_rejected(self):
        data = _valid_batch()
        data["snapshots"][0]["publication_code"] = "video2-forma-ad-tiktok-A-v1"
        data["snapshots"][0]["source"] = "youtube_shorts"  # публикация на самом деле tiktok
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(planned, [])
        self.assertTrue(any("не совпадает" in e for e in errors))

    # ---- null разрешён ----
    def test_null_allowed_for_unknown_metric(self):
        data = _valid_batch()
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(errors, [])
        self.assertIsNone(planned[0]["metrics"]["shares"])
        self.assertIsNone(planned[0]["metrics"]["saves"])

    # ---- невалидный captured_at отклоняется ----
    def test_invalid_captured_at_rejected(self):
        data = _valid_batch(captured_at="not-a-date")
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(planned, [])
        self.assertTrue(any("captured_at" in e for e in errors))

        data2 = _valid_batch(captured_at="2026-07-02T18:30:00+03:00")  # не UTC 'Z'
        planned2, errors2 = M.plan_batch(data2, self.base_url, "test-key")
        self.assertTrue(any("captured_at" in e for e in errors2))
        self.assertEqual(planned2, [])

    # ---- отсутствующий API_KEY при --apply отклоняется ----
    def test_missing_api_key_rejected_on_apply(self):
        os.environ.pop("API_KEY", None)
        path = self._write_batch(_valid_batch())
        rc, out, err = self._run([path, "--base-url", self.base_url, "--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("API_KEY", err)
        self.assertEqual(_Handler.post_calls, 0)

    # ---- неизвестная публикация блокирует запуск ----
    def test_unknown_publication_blocks_run(self):
        data = _valid_batch()
        data["snapshots"][0]["publication_code"] = "does-not-exist-v1"
        path = self._write_batch(data)
        rc, out, err = self._run([path, "--base-url", self.base_url, "--apply"])
        self.assertEqual(rc, 1)
        self.assertEqual(_Handler.post_calls, 0)
        self.assertIn("не найдена", out)

    # ---- повторный apply корректно обрабатывает existing ----
    def test_repeated_apply_reports_existing(self):
        path = self._write_batch(_valid_batch())
        rc1, out1, _ = self._run([path, "--base-url", self.base_url, "--apply"])
        self.assertEqual(rc1, 0)
        self.assertIn("created=1", out1)
        self.assertIn("existing=0", out1)

        rc2, out2, _ = self._run([path, "--base-url", self.base_url, "--apply"])
        self.assertEqual(rc2, 0)
        self.assertIn("created=0", out2)
        self.assertIn("existing=1", out2)
        self.assertEqual(len(_Handler.snapshots), 1)  # дубль не создан на сервере

    # ---- ключ не попадает в вывод ----
    def test_api_key_never_printed(self):
        secret = "SUPER_SECRET_KEY_XYZ"
        os.environ["API_KEY"] = secret
        _Handler.api_key = secret  # чтобы запрос реально прошёл авторизацию тестового сервера
        path = self._write_batch(_valid_batch())
        rc, out, err = self._run([path, "--base-url", self.base_url, "--apply"])
        self.assertEqual(rc, 0)
        self.assertNotIn("SUPER_SECRET_KEY_XYZ", out)
        self.assertNotIn("SUPER_SECRET_KEY_XYZ", err)

    # ---- неизвестное поле в snapshot-элементе тоже блокирует запуск ----
    def test_unknown_field_rejected(self):
        data = _valid_batch()
        data["snapshots"][0]["clicks"] = 5  # не входит в MVP-набор полей клиента
        planned, errors = M.plan_batch(data, self.base_url, "test-key")
        self.assertEqual(planned, [])
        self.assertTrue(any("неизвестные поля" in e for e in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
