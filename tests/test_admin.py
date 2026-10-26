"""后台管理 API 测试（ADR-026）：用桩上下文跑 Flask test_client。"""

from __future__ import annotations

import pytest

from qq_relay.admin import AdminContext, create_app


class StubCtx:
    """与 AdminContext 同接口的桩（create_app 只依赖方法）。"""

    def __init__(self):
        self.saved: list[dict] = []
        self.deleted: list[str] = []
        self.scanned: list[str] = []
        self.pushed: list[tuple[str, str | None]] = []

    def status(self):
        return {"ok": True, "running": True, "uptime_s": 42,
                "deliver_mode": "file,pushplus",
                "sources": [{"id": "seu-lectures", "name": "人文讲座",
                             "kind": "seu_lectures", "interval": 900,
                             "last_scan_at": 1760000000, "new": 3, "errors": 0,
                             "last_error": ""}],
                "runner": {"events": 5}}

    def items(self, limit=50):
        return [{"event_id": "e1", "cat": "lecture", "cat2": "lecture",
                 "title": "【人文讲座】唐诗的魅力", "groups": ["web-lecture"],
                 "deadline": "2026-11-10T14:00:00", "created_at": 1760000000}]

    def subs(self):
        return [{"user_qq": "100001", "groups": ["web-lecture"],
                 "cats": ["lecture"], "quiet": [], "instant_min_urg": 2,
                 "digest": True}]

    def save_sub(self, payload):
        self.saved.append(payload)
        return {"ok": True}

    def delete_sub(self, qq):
        self.deleted.append(qq)
        return {"ok": True}

    def scan(self, source_id):
        self.scanned.append(source_id)
        return {"ok": True, "new": 1}

    def test_push(self, qq, token):
        self.pushed.append((qq, token))
        return {"ok": True, "detail": "pushplus:mid-1"}

    def config_view(self):
        return {"ok": True, "files": [{"name": ".env",
                                       "content": "PUSHPLUS_TOKEN=***（已隐藏）"}]}


@pytest.fixture
def client():
    ctx = StubCtx()
    app = create_app(ctx)                       # 鸭子类型即可
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.ctx = ctx
        yield c


class TestAdminApi:
    def test_index_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "后台管理".encode() in r.data or "后台管理" in r.get_data(as_text=True)

    def test_status(self, client):
        d = client.get("/api/status").get_json()
        assert d["running"] is True
        assert d["sources"][0]["id"] == "seu-lectures"

    def test_items(self, client):
        d = client.get("/api/items?limit=5").get_json()
        assert d["items"][0]["cat"] == "lecture"

    def test_subs_crud(self, client):
        d = client.get("/api/subs").get_json()
        assert d["subs"][0]["user_qq"] == "100001"
        r = client.post("/api/subs", json={
            "user_qq": "100002", "groups": ["web-labor"], "cats": ["task"]})
        assert r.get_json()["ok"] is True
        assert client.ctx.saved[0]["user_qq"] == "100002"
        r = client.delete("/api/subs/100002")
        assert r.get_json()["ok"] is True
        assert client.ctx.deleted == ["100002"]

    def test_scan_trigger(self, client):
        r = client.post("/api/scan/labor", json={})
        assert r.get_json() == {"ok": True, "new": 1}
        assert client.ctx.scanned == ["labor"]

    def test_test_push(self, client):
        r = client.post("/api/test-push",
                        json={"qq": "tester1", "token": "tk"})
        assert r.get_json()["ok"] is True
        assert client.ctx.pushed == [("tester1", "tk")]

    def test_config_masked(self, client):
        d = client.get("/api/config").get_json()
        assert d["files"][0]["content"].startswith("PUSHPLUS_TOKEN=***")

    def test_error_guard(self, client):
        client.ctx.scan = lambda sid: (_ for _ in ()).throw(ValueError("没有源 x"))
        r = client.post("/api/scan/nope", json={})
        assert r.status_code == 400
        assert "没有源" in r.get_json()["error"]
