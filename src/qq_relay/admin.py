"""后台管理界面（ADR-026）：Flask API + 自包含单页（无构建、无外部静态文件）。

面向对象：校内运营人员（校内使用者）。焦点能力：人文讲座/劳动教育等源的监控状态、
订阅管理（群 × 类别）、手动触发扫描、PushPlus 测试推送、配置概览（脱敏）。
"只打基础"：可改的配置仍在 config/*.yml 与 .env；本页负责运行态操作。

    python -m qq_relay.admin          # 开发运行
    qq-relay.exe                      # 便携版（PyInstaller one-dir）
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, jsonify, request, send_file

from .config import (
    CATS,
    Settings,
    load_subscriptions,
    load_web_sources,
    runtime_root,
)
from .deliver.pushplus import DeliverError, PushPlusDeliverer
from .yamlio import atomic_write_yaml

_SECRET_RE = re.compile(r"((?:sk_|token|password|secret|api_key)\S*)\s*[:=]\s*\S+",
                        re.IGNORECASE)


def _mask(text: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}: ***（已隐藏）", text)


# ---------------------------------------------------------------- HTML 页面

_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQ消息集散 · 后台管理</title>
<style>
:root{--bg:#f6f7f9;--panel:#ffffff;--border:#e5e7eb;--text:#111827;--muted:#6b7280;
--accent:#2563eb;--accent-text:#ffffff;--ok:#059669;--warn:#d97706;--err:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#151517;--panel:#1f1f23;--border:#3a3a41;
--text:#f3f4f6;--muted:#9ca3af;--accent:#3b82f6;--ok:#34d399;--warn:#fbbf24;--err:#f87171}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:12px;padding:14px 20px;background:var(--panel);
border-bottom:1px solid var(--border);position:sticky;top:0;z-index:9}
header h1{font-size:16px;font-weight:600;margin:0}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);display:inline-block}
main{max-width:1080px;margin:0 auto;padding:20px;display:grid;gap:16px}
section{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px}
h2{font-size:14px;font-weight:600;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--border)}
td{padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:none}
button{background:var(--accent);color:var(--accent-text);border:none;border-radius:6px;
padding:6px 12px;font-size:13px;cursor:pointer}
button.ghost{background:transparent;color:var(--text);border:1px solid var(--border)}
button:disabled{opacity:.5;cursor:default}
input,select{background:var(--bg);color:var(--text);border:1px solid var(--border);
border-radius:6px;padding:6px 8px;font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}}
.muted{color:var(--muted);font-size:12px}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;
border:1px solid var(--border);color:var(--muted);margin-right:4px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.err{color:var(--err)}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:var(--panel);
border:1px solid var(--border);border-radius:8px;padding:8px 16px;font-size:13px;
box-shadow:0 4px 16px rgba(0,0,0,.18);display:none;z-index:99}
pre{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;
font-size:12px;overflow:auto;max-height:280px;white-space:pre-wrap;word-break:break-all}
</style>
</head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <h1>QQ消息集散 · 后台管理</h1>
  <span class="muted" id="uptime"></span>
  <span style="flex:1"></span>
  <button class="ghost" onclick="refreshAll()">刷新</button>
</header>
<main>
  <section>
    <h2>监控源</h2>
    <table><thead><tr><th>源</th><th>类型</th><th>上次扫描</th><th>累计新增</th><th>错误</th><th></th></tr></thead>
    <tbody id="sources"></tbody></table>
    <p class="muted" id="srcHint"></p>
  </section>
  <section>
    <h2>最近信息流</h2>
    <table><thead><tr><th>时间</th><th>类别</th><th>题目</th><th>来源群</th><th>截止</th></tr></thead>
    <tbody id="items"></tbody></table>
  </section>
  <section>
    <h2>订阅管理（群 × 类别）</h2>
    <table><thead><tr><th>用户</th><th>群</th><th>类别</th><th>免打扰</th><th>即时</th><th></th></tr></thead>
    <tbody id="subs"></tbody></table>
    <div class="row" style="margin-top:12px">
      <input id="fQq" placeholder="用户QQ" style="width:130px">
      <input id="fGroups" placeholder="群名/群号，逗号分隔" style="width:220px">
      <input id="fCats" placeholder="类别，逗号分隔（如 讲座,任务）" style="width:220px">
      <button onclick="saveSub()">添加/修改订阅</button>
    </div>
    <p class="muted">类别可选：作业 考试 竞赛 科研 交流 讲座 任务 通知；群名须与「配置概览」中画像群一致。保存后重启软件生效。</p>
  </section>
  <section>
    <h2>PushPlus 测试推送</h2>
    <div class="row">
      <input id="tQq" placeholder="接收人 QQ（备注用）" style="width:150px">
      <input id="tToken" placeholder="PushPlus token（留空则用 .env 里的）" style="width:260px">
      <button onclick="testPush()">发送测试</button>
    </div>
    <p class="muted">当前分发模式：<span id="deliverMode"></span>。未配置 token 时推送会落盘到 outbox 文件夹（不外发）。</p>
  </section>
  <section>
    <h2>配置概览（只读，密钥已隐藏）</h2>
    <pre id="cfg"></pre>
    <p class="muted">要改配置：编辑软件目录下的 config/*.yml 与 .env，保存后重启。</p>
  </section>
</main>
<div id="toast"></div>
<script>
const $=id=>document.getElementById(id);
const CATMAP={"作业":"homework","考试":"exam","竞赛":"competition","科研":"research",
"交流":"exchange","讲座":"lecture","任务":"task","通知":"notice"};
const ZH={homework:"作业",exam:"考试",competition:"竞赛",research:"科研",exchange:"交流",
lecture:"讲座",task:"任务",notice:"notice",chat:"闲聊"};
function toast(t){const e=$("toast");e.textContent=t;e.style.display="block";
clearTimeout(e._t);e._t=setTimeout(()=>e.style.display="none",2600)}
async function api(p,opt){const r=await fetch(p,Object.assign({headers:{"Content-Type":"application/json"}},opt));
return r.json().catch(()=>({ok:false,error:"响应异常"}))}
function fmtTs(ts){return ts?new Date(ts*1000).toLocaleString("zh-CN",{hour12:false}):"—"}
async function refreshAll(){
  const st=await api("/api/status");
  $("dot").style.background=st.running?"var(--ok)":"var(--err)";
  $("uptime").textContent="已运行 "+Math.floor((st.uptime_s||0)/60)+" 分钟 · 分发模式 "+st.deliver_mode;
  $("deliverMode").textContent=st.deliver_mode;
  $("sources").innerHTML=(st.sources||[]).map(s=>`<tr>
    <td>${s.name}</td><td class="muted">${s.kind}</td><td>${fmtTs(s.last_scan_at)}</td>
    <td>${s.new||0}</td><td class="${s.last_error?"err":"muted"}">${s.last_error||"—"}</td>
    <td><button class="ghost" onclick="scan('${s.id}')">立即扫描</button></td></tr>`).join("")
    ||'<tr><td colspan="6" class="muted">暂无监控源</td></tr>';
  const its=await api("/api/items?limit=30");
  $("items").innerHTML=(its.items||[]).map(i=>`<tr><td class="muted">${fmtTs(i.created_at)}</td>
    <td>${ZH[i.cat]||i.cat}${i.cat2&&i.cat2!==i.cat?"+"+ZH[i.cat2]:""}</td>
    <td>${(i.title||"").slice(0,42)}</td><td class="muted">${i.groups.join("、")}</td>
    <td>${(i.deadline||"—").slice(0,16)}</td></tr>`).join("")
    ||'<tr><td colspan="5" class="muted">暂无信息（等源扫描或点「立即扫描」）</td></tr>';
  const sb=await api("/api/subs");
  $("subs").innerHTML=(sb.subs||[]).map(s=>`<tr><td>${s.user_qq}</td>
    <td>${s.groups.join("、")}</td><td>${s.cats.map(c=>ZH[c]||c).join("、")}</td>
    <td>${s.quiet.join(",")||"—"}</td><td>urg≥${s.instant_min_urg}</td>
    <td><button class="ghost" onclick="delSub('${s.user_qq}')">删除</button></td></tr>`).join("")
    ||'<tr><td colspan="6" class="muted">暂无订阅</td></tr>';
  const cfg=await api("/api/config");
  $("cfg").textContent=(cfg.files||[]).map(f=>"# ==== "+f.name+" ====\\n"+f.content).join("\\n\\n");
}
async function scan(id){toast("扫描中…");const r=await api("/api/scan/"+id,{method:"POST",body:"{}"});
  toast(r.ok?("新增 "+r.new+" 条"):("失败："+(r.error||"")));refreshAll()}
async function saveSub(){
  const qq=$("fQq").value.trim(),groups=$("fGroups").value.trim(),
        cats=$("fCats").value.split(/[,，]/).map(s=>CATMAP[s.trim()]||s.trim()).filter(Boolean);
  if(!qq||!groups||!cats.length)return toast("请填全：用户QQ / 群 / 类别");
  const r=await api("/api/subs",{method:"POST",body:JSON.stringify({user_qq:qq,
    groups:groups.split(/[,，]/).map(s=>s.trim()).filter(Boolean),cats})});
  toast(r.ok?"已保存（重启后生效）":"失败："+(r.error||""));refreshAll()}
async function delSub(qq){if(!confirm("删除 "+qq+" 的订阅？"))return;
  const r=await api("/api/subs/"+qq,{method:"DELETE"});toast(r.ok?"已删除":"失败");refreshAll()}
async function testPush(){
  const r=await api("/api/test-push",{method:"POST",body:JSON.stringify(
    {qq:$("tQq").value.trim()||"tester",token:$("tToken").value.trim()||null})});
  toast(r.ok?("已发送："+r.detail):("失败："+(r.error||"")))}
refreshAll();setInterval(refreshAll,15000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------- 上下文（可注入，便于测试）

class AdminContext:
    """真实运行期上下文：包装 Runtime + 轮询器注册表。

    注意：items() 用**独立 SQLite 连接**读取，不与监控 loop 抢事件循环
    （学院源一轮扫描要几分钟，走 loop 会把页面查库堵死）。
    """

    def __init__(self, runtime, pollers: dict, loop: asyncio.AbstractEventLoop) -> None:
        self.runtime = runtime
        self.pollers = pollers
        self.loop = loop
        self.started_at = time.time()
        self._read_conn = None

    def status(self) -> dict:
        s = self.runtime.settings
        sources = []
        for src in load_web_sources(s.config_dir / "web-sources.yml").sources:
            p = self.pollers.get(src.id)
            st = dict(p.stats) if p else {}
            sources.append({
                "id": src.id, "name": src.name, "kind": src.kind,
                "interval": src.interval,
                "last_scan_at": st.get("last_scan_at", 0),
                "new": st.get("new", 0),
                "errors": st.get("errors", 0),
                "last_error": st.get("last_error", ""),
            })
        return {
            "ok": True, "running": True,
            "uptime_s": int(time.time() - self.started_at),
            "deliver_mode": s.deliver_mode,
            "sources": sources,
            "runner": self.runtime.runner.stats,
        }

    async def _reader(self):
        if self._read_conn is None:
            from .store import db as store_db
            self._read_conn = await store_db.connect(self.runtime.settings)
        return self._read_conn

    def items(self, limit: int = 50) -> list[dict]:
        """独立连接同步读取（run_coroutine_threadsafe 到本线程的私有 loop 上跑，
        绝不占用监控 loop）。"""
        import json

        async def _q():
            conn = await self._reader()
            rows = await (await conn.execute(
                "SELECT * FROM items ORDER BY created_at DESC LIMIT ?",
                (limit,))).fetchall()
            return [{
                "event_id": r["event_id"], "cat": r["cat"], "cat2": r["cat2"],
                "title": r["raw_text"].split("\n", 1)[0][:80],
                "groups": json.loads(r["groups_json"]),
                "deadline": r["deadline"], "created_at": r["created_at"],
            } for r in rows]

        # 用独立线程跑一次性 loop，避免与监控 loop 争抢
        import threading
        box: dict = {}

        def _worker():
            box["result"] = asyncio.run(_q())

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=15)
        return box.get("result", [])

    def subs(self) -> list[dict]:
        s = self.runtime.settings
        cfg = load_subscriptions(s.config_dir / "subscriptions.yml")
        return [{
            "user_qq": x.user_qq, "groups": list(x.groups), "cats": list(x.cats),
            "quiet": list(x.quiet), "instant_min_urg": x.instant_min_urg,
            "digest": x.digest,
        } for x in cfg.subs.values()]

    def save_sub(self, payload: dict) -> dict:
        qq = str(payload.get("user_qq") or "").strip()
        groups = [str(g).strip() for g in (payload.get("groups") or []) if str(g).strip()]
        cats = [str(c).strip() for c in (payload.get("cats") or []) if str(c).strip()]
        if not qq or not groups or not cats:
            raise ValueError("user_qq / groups / cats 均不能为空")
        bad = [c for c in cats if c not in CATS]
        if bad:
            raise ValueError(f"未知类别: {bad}（可选 {list(CATS)}）")
        s = self.runtime.settings
        path = s.config_dir / "subscriptions.yml"
        cfg = load_subscriptions(path)
        data = {"subscriptions": {}}
        for old in cfg.subs.values():
            data["subscriptions"][old.user_qq] = {
                "groups": list(old.groups), "cats": list(old.cats),
                "keywords": {"inc": list(old.inc), "exc": list(old.exc)},
                "quiet": list(old.quiet),
                "instant_min_urg": old.instant_min_urg, "digest": old.digest}
        data["subscriptions"][qq] = {
            "groups": groups, "cats": cats,
            "keywords": {"inc": [], "exc": []},
            "quiet": ["23:00-07:00"], "instant_min_urg": 2, "digest": True}
        atomic_write_yaml(path, data)
        return {"ok": True}

    def delete_sub(self, qq: str) -> dict:
        s = self.runtime.settings
        path = s.config_dir / "subscriptions.yml"
        cfg = load_subscriptions(path)
        if qq not in cfg.subs:
            raise ValueError(f"没有用户 {qq} 的订阅")
        data = {"subscriptions": {}}
        for old in cfg.subs.values():
            if old.user_qq == qq:
                continue
            data["subscriptions"][old.user_qq] = {
                "groups": list(old.groups), "cats": list(old.cats),
                "keywords": {"inc": list(old.inc), "exc": list(old.exc)},
                "quiet": list(old.quiet),
                "instant_min_urg": old.instant_min_urg, "digest": old.digest}
        atomic_write_yaml(path, data)
        return {"ok": True}

    def scan(self, source_id: str) -> dict:
        p = self.pollers.get(source_id)
        if p is None:
            raise ValueError(f"没有源 {source_id}")
        fut = asyncio.run_coroutine_threadsafe(p.poll_once(), self.loop)
        return {"ok": True, "new": fut.result(timeout=120)}

    def test_push(self, qq: str, token: Optional[str]) -> dict:
        s = self.runtime.settings
        from .contracts import ClassifiedEvent
        item = ClassifiedEvent(
            event_id="test-push", groups=["(测试)"], cat="notice", cat2="notice",
            is_info=1.0, urg=2, action="know", has_ddl=False,
            raw_text="这是一条来自「QQ消息集散」后台的测试推送。如果你收到了它，"
                     "说明 PushPlus 通道工作正常。", created_at=int(time.time()))
        d = PushPlusDeliverer(default_token=token or s.pushplus_token)
        detail = asyncio.run_coroutine_threadsafe(
            d.deliver(qq, item, "instant"), self.loop).result(timeout=60)
        return {"ok": True, "detail": detail}

    def config_view(self) -> dict:
        root = self.runtime.settings.config_dir
        files = []
        for name in ("groups.yml", "tree.yml", "web-sources.yml",
                     "wechat-mp.yml", "labor.yml", "seu-lectures.yml",
                     "subscriptions.yml"):
            p = root / name
            if p.is_file():
                files.append({"name": name, "content": _mask(p.read_text(
                    encoding="utf-8"))})
        envp = runtime_root() / ".env"
        if envp.is_file():
            files.append({"name": ".env", "content": _mask(envp.read_text(
                encoding="utf-8"))})
        return {"ok": True, "files": files}


def create_app(ctx: AdminContext) -> Flask:
    app = Flask(__name__)

    def guard(fn):
        def wrapper(*a, **kw):
            try:
                return jsonify(fn(*a, **kw))
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        wrapper.__name__ = fn.__name__
        return wrapper

    @app.get("/")
    def index():
        return _PAGE

    @app.get("/api/status")
    @guard
    def _status():
        return ctx.status()

    @app.get("/api/items")
    @guard
    def _items():
        return {"ok": True, "items": ctx.items(int(request.args.get("limit", 50)))}

    @app.get("/api/subs")
    @guard
    def _subs():
        return {"ok": True, "subs": ctx.subs()}

    @app.post("/api/subs")
    @guard
    def _save_sub():
        return ctx.save_sub(request.get_json(force=True))

    @app.delete("/api/subs/<qq>")
    @guard
    def _del_sub(qq):
        return ctx.delete_sub(qq)

    @app.post("/api/scan/<source_id>")
    @guard
    def _scan(source_id):
        return ctx.scan(source_id)

    @app.post("/api/test-push")
    @guard
    def _test_push():
        body = request.get_json(force=True)
        return ctx.test_push(str(body.get("qq") or "tester"),
                             body.get("token") or None)

    @app.get("/api/config")
    @guard
    def _config():
        return ctx.config_view()

    return app


# ---------------------------------------------------------------- 启动

def main(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    from .main import build_runtime, spawn_web_pollers

    s = Settings.from_env()
    s.ensure_dirs()

    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_run_loop, daemon=True).start()
    fut = asyncio.run_coroutine_threadsafe(_build(s), loop)
    runtime = fut.result(timeout=60)

    ctx = AdminContext(runtime, runtime.pollers, loop)
    app = create_app(ctx)
    url = f"http://{host}:{port}"
    print(f"[admin] 后台管理 → {url} （数据目录：{runtime_root()}）")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


async def _build(s: Settings):
    import asyncio

    from .main import build_runtime, spawn_web_pollers

    runtime = await build_runtime(s, with_server=False)
    await spawn_web_pollers(runtime)
    asyncio.create_task(runtime.scheduler.run_forever())   # 临期提醒调度
    return runtime


if __name__ == "__main__":
    main()
