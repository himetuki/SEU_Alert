"""后台管理界面（ADR-026 升级）：Flask API + 自包含单页（无构建、无外部静态文件）。

面向对象：校内运营人员（校内用户）。焦点能力：人文讲座/劳动教育等源的监控状态、
订阅管理（群 × 类别）、手动触发扫描、PushPlus 测试推送、配置概览（脱敏）。

前端视觉基因（哈希种子组）：
  94f3664b → cockpit-drawer（暗色驾驶舱骨架 + 脉冲呼吸）
  07985f25 → bento-dashboard（bento 信息面板，一目了然）
色系沿用东大黄绿：#057C66 #2CB497 #ddd000 #231815。

"只打基础"：可改的配置仍在 config/*.yml 与 .env；本页负责运行态操作。

    python -m seu_alert.admin          # 开发运行
    seu_alert.exe                      # 便携版（PyInstaller one-dir）
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
from .adapters.web.errors import friendly_error
from . import settings_io
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
:root{
  --bg:#0a1a16; --panel:#0d241f; --panel2:#0f2d26; --card:#103029;
  --border:#1a3a31; --text:#c8e6db; --muted:#7fbfa8;
  --accent:#2CB497; --accent2:#057C66; --yellow:#ddd000; --danger:#f87171;
  --shadow:0 4px 20px rgba(0,0,0,.25); --radius:12px; --pulse:6000ms;
}
html[data-theme="light"]{
  --bg:#f0f5f0; --panel:#ffffff; --panel2:#f7faf7; --card:#ffffff;
  --border:#d8e4d8; --text:#231815; --muted:#7a8a7a;
  --accent:#057C66; --accent2:#2CB497; --yellow:#ddd000; --danger:#d64541;
  --shadow:0 2px 12px rgba(5,124,102,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:"Source Han Sans CN","Microsoft YaHei",system-ui,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;
  height:100vh;display:flex;flex-direction:column;overflow:hidden;
  transition:background .3s,color .3s;
}
.pulse-glow{
  position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(circle at 12% -10%,rgba(44,180,151,.07),transparent 42%),
             radial-gradient(circle at 88% 90%,rgba(5,124,102,.05),transparent 40%);
  animation:breathe var(--pulse) ease-in-out infinite;
}
@keyframes breathe{0%,100%{opacity:.55;transform:scale(1)}50%{opacity:1;transform:scale(1.08)}}
.app{position:relative;z-index:1;display:flex;flex:1;overflow:hidden}

/* 侧栏（驾驶舱抽屉） */
.drawer{
  width:216px;background:var(--panel);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;
}
.drawer-header{display:flex;align-items:center;gap:10px;padding:15px 16px;border-bottom:1px solid var(--border)}
.drawer-header .logo{
  width:32px;height:32px;border-radius:8px;flex-shrink:0;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:grid;place-items:center;font-size:17px;font-weight:900;color:#fff;
}
.drawer-header h1{font-size:14.5px;font-weight:700;letter-spacing:-.02em}
.drawer-nav{padding:10px;flex:1;overflow-y:auto}
.drawer-nav .grp{font-size:10px;color:var(--muted);letter-spacing:.1em;padding:10px 10px 4px;text-transform:uppercase}
.nav-item{
  display:flex;align-items:center;gap:10px;width:100%;
  padding:9px 12px;margin-bottom:2px;
  background:none;border:none;border-radius:8px;cursor:pointer;
  color:var(--muted);font-size:13.5px;text-align:left;
  transition:background .15s,color .15s;
}
.nav-item:hover{background:var(--panel2);color:var(--text)}
.nav-item.active{background:rgba(44,180,151,.16);color:var(--accent);font-weight:600}
.nav-item .ic{width:18px;text-align:center;flex-shrink:0}
.nav-item .badge{margin-left:auto;font-size:10px;background:rgba(248,113,113,.2);color:var(--danger);padding:1px 6px;border-radius:99px}
.drawer-footer{padding:12px;border-top:1px solid var(--border);display:flex;gap:8px}
.theme-btn{
  flex:1;padding:7px;border-radius:7px;font-size:12px;cursor:pointer;
  border:1px solid var(--border);background:var(--panel2);color:var(--muted);
  transition:border-color .15s,color .15s;
}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}

/* 主区 */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.header{
  height:52px;display:flex;align-items:center;justify-content:space-between;
  padding:0 18px;background:var(--panel);border-bottom:1px solid var(--border);flex-shrink:0;
}
.header .crumb{font-size:12.5px;color:var(--muted)}
.header .crumb b{color:var(--accent);font-weight:600}
.header-right{display:flex;align-items:center;gap:10px}
.clock{font-family:"JetBrains Mono","Consolas",monospace;font-size:12px;color:var(--muted)}
.status-dot{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--accent)}
.status-dot .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 0 rgba(44,180,151,.6);animation:dotPulse 2s infinite}
@keyframes dotPulse{0%{box-shadow:0 0 0 0 rgba(44,180,151,.5)}70%{box-shadow:0 0 0 8px rgba(44,180,151,0)}100%{box-shadow:0 0 0 0 rgba(44,180,151,0)}}
.btn{
  padding:7px 16px;border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;
  border:1px solid transparent;transition:all .15s;white-space:nowrap;
}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent2)}
.btn-ghost{background:var(--panel2);color:var(--text);border-color:var(--border)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}

.content{flex:1;overflow-y:auto;padding:18px}
.view{display:none;animation:fadeIn .3s ease}
.view.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.section-title{font-size:15px;font-weight:700;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.section-title .hint{font-size:11px;color:var(--muted);font-weight:400}

/* bento 信息面板 */
.bento{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
.span-2{grid-column:span 2}.span-3{grid-column:span 3}.span-6{grid-column:span 6}
@media(max-width:1000px){.span-3{grid-column:span 6}.span-2{grid-column:span 3}}
@media(max-width:640px){.span-2{grid-column:span 6}}
.panel{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;box-shadow:var(--shadow);
  display:flex;flex-direction:column;gap:8px;
  transition:transform .15s,box-shadow .15s;
}
.panel:hover{transform:translateY(-1px);box-shadow:0 6px 24px rgba(0,0,0,.18)}
.panel h3{font-size:12.5px;font-weight:700;color:var(--muted);letter-spacing:.02em}
.panel .kpi{font-size:32px;font-weight:800;color:var(--accent);line-height:1.1}
.panel .kpi small{font-size:13px;font-weight:600;color:var(--muted);margin-left:6px}
.panel .sub{font-size:11.5px;color:var(--muted)}
.panel .kpi.danger{color:var(--danger)}
.panel .kpi.yellow{color:var(--yellow)}
.panel-list{display:flex;flex-direction:column;gap:2px;flex:1}
.mini{display:flex;align-items:center;gap:8px;padding:5px 2px;font-size:12.5px;border-bottom:1px solid var(--border)}
.mini:last-child{border-bottom:none}
.mini .ic{flex-shrink:0}
.mini .name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mini .dl{font-size:11px;color:var(--danger);flex-shrink:0}
.mini .ok{color:var(--accent);font-size:11px;flex-shrink:0}
.mini .muted{color:var(--muted);font-size:11px;flex-shrink:0}
.mini .warn{color:var(--yellow);font-size:11px;flex-shrink:0}
.tag{display:inline-block;padding:2px 8px;border-radius:5px;font-size:10.5px;font-weight:700;background:rgba(44,180,151,.14);color:var(--accent)}
.tag.y{background:rgba(221,208,0,.14);color:var(--yellow)}
.tag.r{background:rgba(248,113,113,.14);color:var(--danger)}
.tags{display:flex;gap:4px;flex-wrap:wrap}
.bar{height:6px;border-radius:99px;background:var(--panel2);overflow:hidden;margin-top:2px}
.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent2),var(--accent));width:0;transition:width .8s ease}
.bar.y i{background:linear-gradient(90deg,var(--accent),var(--yellow))}

.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;padding:9px 14px;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);background:var(--panel2);white-space:nowrap}
td{padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr{transition:background .12s}
tbody tr:hover{background:var(--panel2)}
.mini-tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:10.5px;background:rgba(44,180,151,.13);color:var(--accent);font-weight:600;margin-right:4px}
.mono{font-family:"JetBrains Mono","Consolas",monospace;font-size:11.5px}
td.err-cell{max-width:340px;white-space:normal;word-break:break-word;color:var(--muted);line-height:1.5}
.op{padding:3px 9px;border-radius:5px;font-size:11px;cursor:pointer;border:1px solid var(--border);background:var(--panel2);color:var(--text);transition:all .12s}
.op:hover{border-color:var(--accent);color:var(--accent)}
.op.danger{border-color:transparent;background:rgba(248,113,113,.14);color:var(--danger)}
.op.danger:hover{border-color:var(--danger)}

.filter-bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.fchip{padding:5px 14px;border-radius:99px;font-size:12px;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--muted);transition:all .12s}
.fchip:hover{border-color:var(--accent);color:var(--accent)}
.fchip.active{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.sub-form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
.sub-form input,.sub-form select{
  padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:12.5px;
  background:var(--panel2);color:var(--text);min-width:120px;
}
.sub-form input:focus,.sub-form select:focus{outline:none;border-color:var(--accent)}
.rule-list{display:flex;flex-direction:column;gap:10px}
.rule{display:flex;gap:10px;align-items:flex-start;font-size:12.5px}
.rule .r-num{width:20px;height:20px;border-radius:50%;background:rgba(44,180,151,.15);color:var(--accent);display:grid;place-items:center;font-size:10.5px;font-weight:700;flex-shrink:0;margin-top:1px}
.cfg-item{display:flex;align-items:center;justify-content:space-between;padding:9px 2px;border-bottom:1px solid var(--border);font-size:12.5px;gap:12px}
.cfg-item:last-child{border-bottom:none}
.cfg-item .key{color:var(--muted);flex-shrink:0}
pre.cfg-body{background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:10px;font-size:11px;overflow:auto;max-height:200px;white-space:pre-wrap;word-break:break-all;font-family:"JetBrains Mono","Consolas",monospace;color:var(--text)}

/* ── 传统配置表单 ── */
.cfg-section{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);margin-bottom:14px}
.cfg-section>h2{font-size:14px;font-weight:700;margin:0 0 6px;display:flex;align-items:center;gap:8px}
.cfg-section>h2 small{font-size:11px;color:var(--muted);font-weight:400}
.cfg-row{display:grid;grid-template-columns:230px 1fr;gap:16px;padding:12px 0;border-bottom:1px dashed var(--border);align-items:center}
.cfg-row:last-child{border-bottom:none;padding-bottom:2px}
.cfg-label{font-size:13px;font-weight:600}
.cfg-label small{display:block;font-weight:400;color:var(--muted);font-size:11px;margin-top:2px;line-height:1.5}
.ctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ctl input[type=text],.ctl input[type=password],.ctl input[type=number],.ctl select{
  padding:8px 12px;border:1px solid var(--border);border-radius:8px;
  background:var(--panel2);color:var(--text);font-size:12.5px;min-width:130px;
}
.ctl input:focus,.ctl select:focus{outline:none;border-color:var(--accent)}
.opt{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border:1px solid var(--border);border-radius:8px;background:var(--panel2);font-size:12.5px;cursor:pointer;user-select:none}
.opt:has(input:checked){border-color:var(--accent);background:rgba(44,180,151,.14);color:var(--accent);font-weight:600}
.opt input{accent-color:var(--accent)}
.switch{position:relative;display:inline-block;width:42px;height:24px;flex-shrink:0}
.switch input{opacity:0;width:0;height:0}
.switch span{position:absolute;inset:0;background:var(--border);border-radius:99px;transition:.2s;cursor:pointer}
.switch span::before{content:"";position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.switch input:checked+span{background:var(--accent)}
.switch input:checked+span::before{transform:translateX(18px)}
.slider{display:flex;align-items:center;gap:10px;flex:1;min-width:200px}
.slider input[type=range]{flex:1;accent-color:var(--accent)}
.slider output{min-width:72px;text-align:right;font-family:"JetBrains Mono","Consolas",monospace;font-size:12px;color:var(--accent)}
.src-row{display:grid;grid-template-columns:1fr 90px 96px;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border)}
.src-row:last-child{border-bottom:none}
.src-row .src-name{font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src-row .src-kind{font-size:10.5px;color:var(--muted);font-weight:400;margin-left:6px}
.src-row input[type=number]{width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--panel2);color:var(--text);font-size:12px}
.settings-bar{position:sticky;bottom:0;display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:12px 0 2px;background:linear-gradient(180deg,transparent,var(--bg) 40%);z-index:5}
.dirty-badge{font-size:11px;color:var(--yellow);margin-right:auto;opacity:0;transition:opacity .2s}
.dirty-badge.show{opacity:1}
@media(max-width:760px){.cfg-row{grid-template-columns:1fr;gap:6px}.src-row{grid-template-columns:1fr 70px 90px}}
.footer{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:7px 18px;background:var(--panel);border-top:1px solid var(--border);
  font-size:11px;color:var(--muted);flex-shrink:0;flex-wrap:wrap;
}
.footer .hash{font-family:"JetBrains Mono","Consolas",monospace}
.toast{
  position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(20px);
  background:var(--accent);color:#fff;padding:10px 20px;border-radius:9px;
  font-size:13px;z-index:999;opacity:0;pointer-events:none;
  transition:opacity .25s,transform .25s;box-shadow:0 6px 24px rgba(0,0,0,.3);
}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:99px}
::-webkit-scrollbar-track{background:transparent}
</style>
</head>
<body>

<div class="pulse-glow"></div>

<div class="app">

  <aside class="drawer">
    <div class="drawer-header">
      <div class="logo">南</div>
      <h1>QQ消息集散</h1>
    </div>
    <nav class="drawer-nav" id="drawerNav">
      <div class="grp">概览</div>
      <button class="nav-item active" data-view="dashboard"><span class="ic">📊</span>仪表盘</button>
      <button class="nav-item" data-view="reminders"><span class="ic">🔔</span>提醒调度<span class="badge" id="badgeUrgent">·</span></button>
      <button class="nav-item" data-view="stream"><span class="ic">📋</span>最近信息流</button>
      <div class="grp">管理</div>
      <button class="nav-item" data-view="sources"><span class="ic">📡</span>采集源</button>
      <button class="nav-item" data-view="subscriptions"><span class="ic">👥</span>订阅管理</button>
      <div class="grp">系统</div>
      <button class="nav-item" data-view="config"><span class="ic">⚙️</span>配置概览</button>
    </nav>
    <div class="drawer-footer">
      <button class="theme-btn" id="themeToggle">🌓 切换主题</button>
    </div>
  </aside>

  <main class="main">
    <header class="header">
      <div class="crumb">后台管理 / <b id="crumbNow">仪表盘</b></div>
      <div class="header-right">
        <span class="status-dot"><span class="dot" id="dot"></span><span id="dotTxt">…</span></span>
        <span class="clock" id="clock">--:--:--</span>
        <button class="btn btn-ghost" id="btnRefresh">🔄 刷新</button>
      </div>
    </header>

    <div class="content">

      <!-- ═══ 仪表盘 ═══ -->
      <section class="view active" id="view-dashboard">
        <div class="bento">
          <div class="panel span-2">
            <h3>📥 累计入库</h3>
            <div class="kpi" id="kpiPassed">·</div>
            <div class="sub">事件 <span id="kpiEvents">·</span> · 丢弃 <span id="kpiDropped">·</span> · fan-in <span id="kpiFanned">·</span></div>
            <div class="bar"><i id="barPassed" style="width:0"></i></div>
            <div class="sub">今日新增（近 30 条内）<b id="kpiToday">·</b></div>
          </div>
          <div class="panel">
            <h3>⚠️ 临期提醒</h3>
            <div class="kpi danger" id="kpiUrgent">·</div>
            <div class="sub">未来 7 天待触发 DDL</div>
          </div>
          <div class="panel">
            <h3>👥 订阅数</h3>
            <div class="kpi" id="kpiSubs">·</div>
            <div class="sub">订阅配置条数</div>
          </div>
          <div class="panel">
            <h3>📤 分发模式</h3>
            <div class="kpi yellow" id="kpiMode" style="font-size:20px">·</div>
            <div class="sub">file / pushplus / qq</div>
          </div>

          <div class="panel span-2">
            <h3>📡 采集源健康</h3>
            <div class="panel-list" id="srcHealth"><div class="mini muted">加载中…</div></div>
          </div>

          <div class="panel span-2">
            <h3>📋 分类分布（近 30 条）</h3>
            <div class="panel-list" id="catDist"><div class="mini muted">加载中…</div></div>
          </div>

          <div class="panel span-2">
            <h3>⏳ 临期 DDL 轨道</h3>
            <div class="panel-list" id="ddlTrack"><div class="mini muted">加载中…</div></div>
          </div>

          <div class="panel span-6">
            <h3>🆕 最新信息 · <span style="font-weight:400">近 4 条</span></h3>
            <div class="panel-list" id="latestList"><div class="mini muted">加载中…</div></div>
          </div>
        </div>
      </section>

      <!-- ═══ 采集源 ═══ -->
      <section class="view" id="view-sources">
        <div class="section-title">📡 监控源</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>源</th><th>方式</th><th>状态</th><th>上次扫描</th><th>累计新增</th><th>错误</th><th></th></tr></thead>
            <tbody id="sourcesBody"></tbody>
          </table>
        </div>
        <div class="panel" style="margin-top:12px">
          <div class="sub">💡 采集源在 <span class="mono">config/web-sources.yml</span> 配置，<span class="mono">enabled: false</span> 的源不参与轮询。讲座模块只监控、不代预约、不抢票。</div>
        </div>
      </section>

      <!-- ═══ 最近信息流 ═══ -->
      <section class="view" id="view-stream">
        <div class="section-title">📋 最近信息流 <span class="hint">类别：作业 考试 竞赛 科研 交流 讲座 任务 通知</span></div>
        <div class="filter-bar" id="filterBar"><button class="fchip active" data-filter="all">全部</button></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>类别</th><th>题目</th><th>来源群</th><th>截止</th></tr></thead>
            <tbody id="streamBody"></tbody>
          </table>
        </div>
      </section>

      <!-- ═══ 提醒调度 ═══ -->
      <section class="view" id="view-reminders">
        <div class="section-title">🔔 临期提醒调度 <span class="hint">带 DDL 的通知在截止前多轮提醒，到点即发、不重复发</span></div>
        <div class="bento">
          <div class="panel span-2">
            <h3>📅 已排程</h3>
            <div class="kpi" id="rScheduled">·</div>
            <div class="sub">reminders 表累计写入</div>
          </div>
          <div class="panel">
            <h3>📤 已发送</h3>
            <div class="kpi" id="rSent">·</div>
            <div class="sub">提醒已送达</div>
          </div>
          <div class="panel">
            <h3>❌ 发送错误</h3>
            <div class="kpi danger" id="rErrors">·</div>
            <div class="sub">分发失败次数</div>
          </div>
          <div class="panel span-3">
            <h3>🧭 触发机制</h3>
            <div class="rule-list">
              <div class="rule"><span class="r-num">1</span><div><b>截止前 24h</b>：首轮提醒，推送「即将截止」摘要 + 直达链接。</div></div>
              <div class="rule"><span class="r-num">2</span><div><b>截止前 3h</b>：末轮提醒，高优先级强调，仅发一次。</div></div>
              <div class="rule"><span class="r-num">3</span><div><b>免打扰时段</b>内的触发顺延到下一个可发送窗口，不丢提醒。</div></div>
              <div class="rule"><span class="r-num">4</span><div>轮询调度为 <b>每分钟 tick</b>，检查 DDL 与发送状态，幂等去重。</div></div>
            </div>
          </div>
          <div class="panel span-3">
            <h3>📅 未来 7 天 DDL 轨道</h3>
            <div class="panel-list" id="ddlTrackFull"><div class="mini muted">加载中…</div></div>
          </div>
        </div>
      </section>

      <!-- ═══ 订阅管理 ═══ -->
      <section class="view" id="view-subscriptions">
        <div class="section-title">👥 订阅管理（群 × 类别） <span class="hint">保存后重启软件生效</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>用户</th><th>群</th><th>类别</th><th>免打扰</th><th>粒度</th><th></th></tr></thead>
            <tbody id="subsBody"></tbody>
          </table>
        </div>
        <div class="panel" style="margin-top:14px">
          <h3>➕ 添加 / 修改订阅</h3>
          <div class="sub-form">
            <input id="fQq" placeholder="用户 QQ">
            <input id="fGroups" placeholder="群名 / 群号，逗号分隔" style="min-width:200px">
            <input id="fCats" placeholder="类别，逗号分隔（如 讲座,任务）" style="min-width:200px">
            <select id="fGran"><option value="digest">Digest</option><option value="instant">即时</option></select>
            <button class="btn btn-primary" onclick="saveSub()">添加订阅</button>
          </div>
          <div class="sub" style="margin-top:10px">类别可选：作业 考试 竞赛 科研 交流 讲座 任务 通知；群名须与「配置概览」中画像群一致。</div>
        </div>
      </section>

      <!-- ═══ 配置概览 ═══ -->
      <section class="view" id="view-config">
        <div class="section-title">⚙️ 配置 <span class="hint">保存后重启后台进程生效；密钥留空表示保持原值</span></div>
        <div id="settingsForm">

          <section class="cfg-section">
            <h2>🚀 运行</h2>
            <div class="cfg-row">
              <div class="cfg-label">分发方式<small>可多选，至少一个</small></div>
              <div class="ctl" id="sDeliver">
                <label class="opt"><input type="checkbox" value="file"> 文件落盘</label>
                <label class="opt"><input type="checkbox" value="pushplus"> PushPlus</label>
                <label class="opt"><input type="checkbox" value="qq"> QQ 私聊</label>
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">分类器<small>stub 用于联调；tree 走 JEV 分类树</small></div>
              <div class="ctl" id="sClassifier">
                <label class="opt"><input type="radio" name="classifier" value="stub"> Stub 假分类</label>
                <label class="opt"><input type="radio" name="classifier" value="tree"> JEV 分类树</label>
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">管理员 QQ<small>告警与复核队列接收人，可留空</small></div>
              <div class="ctl"><input id="sAdminQq" type="text" placeholder="例如 10001"></div>
            </div>
          </section>

          <section class="cfg-section">
            <h2>⏰ 临期提醒</h2>
            <div class="cfg-row">
              <div class="cfg-label">提前提醒<small>两轮，单位小时（1–168）</small></div>
              <div class="ctl">
                <span class="sub">第一轮</span>
                <input id="sOff1" type="number" min="1" max="168" step="1" style="width:88px">
                <span class="sub">小时 · 第二轮</span>
                <input id="sOff2" type="number" min="1" max="168" step="1" style="width:88px">
                <span class="sub">小时</span>
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">扫描间隔<small>调度器 tick 间隔，15–600 秒</small></div>
              <div class="ctl slider">
                <input id="sRemInterval" type="range" min="15" max="600" step="5">
                <output id="sRemIntervalOut">60 秒</output>
              </div>
            </div>
          </section>

          <section class="cfg-section">
            <h2>📤 PushPlus</h2>
            <div class="cfg-row">
              <div class="cfg-label">Token<small>留空保持原值；已配置时显示占位提示</small></div>
              <div class="ctl"><input id="sPushToken" type="password" placeholder="未配置" autocomplete="new-password"></div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">群组主题<small>可选，PUSHPLUS_TOPIC</small></div>
              <div class="ctl"><input id="sPushTopic" type="text" placeholder="留空则不使用主题"></div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">测试推送<small>发送一条测试消息验证通道</small></div>
              <div class="ctl">
                <input id="tQq" placeholder="接收人 QQ" style="min-width:130px">
                <input id="tToken" placeholder="临时 token（可空）" style="min-width:170px">
                <button class="btn btn-primary" onclick="testPush()">发送测试</button>
              </div>
            </div>
          </section>

          <section class="cfg-section">
            <h2>🤖 模型服务</h2>
            <div class="cfg-row">
              <div class="cfg-label">JEV 分类服务<small>Base URL + API Key（留空保持）</small></div>
              <div class="ctl">
                <input id="sJevBase" type="text" placeholder="https://…" style="min-width:220px">
                <input id="sJevKey" type="password" placeholder="API Key（留空保持）" style="min-width:200px" autocomplete="new-password">
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">对话模型<small>Base URL + API Key + 模型名</small></div>
              <div class="ctl">
                <input id="sChatBase" type="text" placeholder="https://…" style="min-width:220px">
                <input id="sChatKey" type="password" placeholder="API Key（留空保持）" style="min-width:200px" autocomplete="new-password">
                <input id="sChatModel" type="text" placeholder="模型名" style="min-width:150px">
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">投稿提取栈<small>按勾选顺序启用，可多选</small></div>
              <div class="ctl" id="sExtractChain">
                <label class="opt"><input type="checkbox" value="vision"> 视觉</label>
                <label class="opt"><input type="checkbox" value="big"> 大模型</label>
                <label class="opt"><input type="checkbox" value="small"> 小模型</label>
              </div>
            </div>
          </section>

          <section class="cfg-section">
            <h2>📡 采集源</h2>
            <div class="sub" style="margin-bottom:4px">开关控制是否参与轮询；间隔单位秒（60–86400）</div>
            <div id="sSources"></div>
          </section>

          <section class="cfg-section">
            <h2>📰 公众号 · 人文讲座</h2>
            <div class="cfg-row">
              <div class="cfg-label">提取层<small>公众号文章字段抽取模型</small></div>
              <div class="ctl" id="sWechatLayer">
                <label class="opt"><input type="radio" name="wechatLayer" value="big"> 大模型</label>
                <label class="opt"><input type="radio" name="wechatLayer" value="small"> 小模型</label>
              </div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">公众号间隔<small>秒（60–86400，建议 ≥900）</small></div>
              <div class="ctl"><input id="sWechatInterval" type="number" min="60" max="86400" step="60" style="width:140px"></div>
            </div>
            <div class="cfg-row">
              <div class="cfg-label">讲座关键词<small>只监控标题含该词的讲座，空=全部</small></div>
              <div class="ctl"><input id="sLectureKeyword" type="text" placeholder="空 = 全部"></div>
            </div>
          </section>

          <div class="settings-bar">
            <span class="dirty-badge" id="dirtyBadge">● 有未保存的修改</span>
            <button class="btn btn-ghost" onclick="resetSettings()">重置默认</button>
            <button class="btn btn-ghost" onclick="cancelSettings()">取消</button>
            <button class="btn btn-primary" onclick="saveSettings()">保存</button>
            <button class="btn btn-primary" onclick="confirmSettings()">确定</button>
          </div>
        </div>
      </section>

    </div>

    <footer class="footer">
      <span>SEU_Alert · 校园信息聚合与强提醒引擎</span>
      <span class="hash">94f3664b × 07985f25 · AGPL-3.0</span>
    </footer>
  </main>
</div>

<div class="toast" id="toast"></div>

<script>
const $=id=>document.getElementById(id);
const ZH={homework:"作业",exam:"考试",competition:"竞赛",research:"科研",exchange:"交流",
          lecture:"讲座",task:"任务",notice:"通知",chat:"闲聊"};
const CATMAP={"作业":"homework","考试":"exam","竞赛":"competition","科研":"research",
              "交流":"exchange","讲座":"lecture","任务":"task","通知":"notice"};
const CATORDER=["lecture","homework","exam","competition","research","exchange","task","notice"];
const VIEW_TITLES={dashboard:"仪表盘",reminders:"提醒调度",stream:"最近信息流",
                   sources:"采集源",subscriptions:"订阅管理",config:"配置概览"};
let state={items:[],subs:[],st:null};

function toast(t){
  const e=$("toast");e.textContent=t;e.classList.add("show");
  clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove("show"),2600);
}
function esc(s){
  return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
async function api(p,opt){
  try{
    const r=await fetch(p,Object.assign({headers:{"Content-Type":"application/json"}},opt));
    return await r.json();
  }catch(e){return {ok:false,error:"网络异常"}}
}
function fmtTs(ts){
  return ts?new Date(ts*1000).toLocaleString("zh-CN",{hour12:false}):"—";
}
function catZH(c){return ZH[c]||c||"?"}
function dlTime(deadline){
  if(!deadline)return null;
  const t=new Date(deadline.replace(" ","T")).getTime();
  return isNaN(t)?null:t;
}
function hoursLeft(deadline){
  const t=dlTime(deadline);
  if(!t)return null;
  return (t-Date.now())/3600000;
}
function dlLabel(deadline){
  const h=hoursLeft(deadline);
  if(h==null)return "—";
  if(h<=0)return "已截止";
  if(h<48)return Math.round(h)+"h 后";
  return Math.round(h/24)+"d 后";
}
function isToday(ts){
  const d=new Date(ts*1000),n=new Date();
  return d.getFullYear()===n.getFullYear()&&d.getMonth()===n.getMonth()&&d.getDate()===n.getDate();
}

/* ═══ 视图切换 ═══ */
$("drawerNav").addEventListener("click",e=>{
  const btn=e.target.closest(".nav-item");
  if(!btn)return;
  document.querySelectorAll(".nav-item").forEach(n=>n.classList.remove("active"));
  btn.classList.add("active");
  const v=btn.dataset.view;
  document.querySelectorAll(".view").forEach(s=>s.classList.remove("active"));
  $("view-"+v).classList.add("active");
  $("crumbNow").textContent=VIEW_TITLES[v];
  if(v==="config")loadSettings();
});

/* ═══ 时钟 ═══ */
setInterval(()=>{
  const d=new Date(),p=n=>String(n).padStart(2,"0");
  $("clock").textContent=p(d.getHours())+":"+p(d.getMinutes())+":"+p(d.getSeconds());
},1000);

/* ═══ 主题 ═══ */
function applyTheme(t){document.documentElement.dataset.theme=t;
  try{localStorage.setItem("seu_alert-theme",t)}catch(e){}}
applyTheme((function(){try{return localStorage.getItem("seu_alert-theme")||"dark"}catch(e){return "dark"}})());
$("themeToggle").addEventListener("click",()=>{
  const cur=document.documentElement.dataset.theme;
  applyTheme(cur==="dark"?"light":"dark");
});

/* ═══ 仪表盘渲染 ═══ */
function renderDashboard(){
  const st=state.st,its=state.items,subs=state.subs;
  const rn=st.runner||{};
  $("kpiPassed").textContent=(rn.passed||0)+"";
  $("kpiEvents").textContent=rn.events||0;
  $("kpiDropped").textContent=rn.dropped||0;
  $("kpiFanned").textContent=rn.fan_in||0;
  $("kpiToday").textContent=its.filter(i=>isToday(i.created_at)).length+" 条";
  const maxP=Math.max(1,rn.passed||0);
  $("barPassed").style.width=Math.min(100,Math.round((rn.delivered||0)/maxP*100))+"%";
  // 未来 7 天待触发
  const urgent=its.filter(i=>{const h=hoursLeft(i.deadline);return h!=null&&h>0&&h<168;});
  $("kpiUrgent").textContent=urgent.length+"";
  $("badgeUrgent").textContent=urgent.length||"";
  $("kpiSubs").textContent=(subs||[]).length+"";
  $("kpiMode").textContent=st.deliver_mode||"—";
  // 采集源健康
  const srcs=st.sources||[];
  $("srcHealth").innerHTML=srcs.length?srcs.slice(0,8).map(s=>{
    const pending=!!s.pending_restart;
    const bad=s.last_error||(s.errors>0);
    const txt=pending?"待重启":bad?"异常":"正常";
    return `<div class="mini"><span class="ic">${s.enabled===false?"⭕":pending?"🕓":bad?"🟡":"✅"}</span>`+
      `<span class="name">${esc(s.name)}${s.enabled===false?' <span class="muted">（停用）</span>':""}</span>`+
      `<span class="${pending||bad?"warn":"ok"}">${txt}</span>`+
      `<span class="muted">${s.enabled===false?"—":fmtTs(s.last_scan_at)}</span></div>`;
  }).join(""):'<div class="mini muted">暂无监控源</div>';
  // 分类分布
  const cnt={};its.forEach(i=>{cnt[i.cat]=(cnt[i.cat]||0)+1});
  const max=Math.max(1,...Object.values(cnt));
  const keys=Object.keys(cnt).sort((a,b)=>(CATORDER.indexOf(a)<0?99:CATORDER.indexOf(a))-(CATORDER.indexOf(b)<0?99:CATORDER.indexOf(b)));
  $("catDist").innerHTML=keys.length?keys.map(k=>{
    const n=cnt[k];
    return `<div class="mini"><span class="ic">${catZH(k)}</span><span style="flex:1"></span>`+
      `<span class="ok">${n}</span><span style="width:60px;flex-shrink:0"><div class="bar"><i style="width:${Math.round(n/max*100)}%"></i></div></span></div>`;
  }).join(""):'<div class="mini muted">暂无数据</div>';
  // 临期 DDL 轨道
  const dls=its.filter(i=>hoursLeft(i.deadline)!=null&&hoursLeft(i.deadline)>0)
    .sort((a,b)=>dlTime(a.deadline)-dlTime(b.deadline)).slice(0,4);
  $("ddlTrack").innerHTML=dls.length?dls.map(i=>
    `<div class="mini"><span class="ic">⏰</span><span class="name">${esc(i.title.slice(0,18))}</span>`+
    `<span class="dl">${dlLabel(i.deadline)}</span></div>`).join("")
    :'<div class="mini muted">暂无待触发 DDL</div>';
  // 最新信息
  $("latestList").innerHTML=its.slice(0,4).map(i=>
    `<div class="mini"><span class="tag">${catZH(i.cat)}</span>`+
    `<span class="name">${esc(i.title.slice(0,30))}</span>`+
    `<span class="muted">${esc((i.groups||[]).join("、"))}</span>`+
    `<span class="muted">${dlLabel(i.deadline)}</span></div>`).join("")
    ||'<div class="mini muted">暂无信息（等源扫描或点「立即扫描」）</div>';
}

/* ═══ 采集源视图 ═══ */
function renderSources(){
  const st=state.st,srcs=st.sources||[];
  $("sourcesBody").innerHTML=srcs.map(s=>{
    const enabled=s.enabled!==false;
    const pending=!!s.pending_restart&&enabled;
    return `<tr><td>${esc(s.name)}${!enabled?' <span class="muted">（已停用）</span>':""}</td>`+
      `<td class="muted">${esc(s.kind)}</td>`+
      `<td>${!enabled?"<span class='tag y'>停用</span>":pending?"<span class='tag y'>待重启</span>":(s.last_error?'<span class="tag r">异常</span>':'<span class="tag">正常</span>')}</td>`+
      `<td class="mono">${enabled?fmtTs(s.last_scan_at):"—"}</td>`+
      `<td>${s.new||0}</td>`+
      `<td class="${s.last_error?"err-cell":"muted"}">${esc(s.last_error)||"—"}</td>`+
      `<td><button class="op" onclick="scan('${esc(s.id)}')"${pending?' title="重启后台进程后才会开始轮询"':""}>立即扫描</button></td></tr>`;
  }).join("")||'<tr><td colspan="7" class="muted">暂无监控源</td></tr>';
}

/* ═══ 信息流视图 ═══ */
function renderStream(){
  const its=state.items||[];
  // 筛选 chips：按出现过的类别
  const seen={};its.forEach(i=>{seen[i.cat]=1});
  const cats=Object.keys(seen).sort((a,b)=>CATORDER.indexOf(a)-CATORDER.indexOf(b));
  $("filterBar").innerHTML='<button class="fchip active" data-filter="all">全部</button>'+
    cats.map(c=>`<button class="fchip" data-filter="${c}">${catZH(c)}</button>`).join("");
  renderStreamRows();
}
function renderStreamRows(){
  const f=(document.querySelector("#filterBar .fchip.active")||{}).dataset?.filter||"all";
  const its=state.items||[];
  $("streamBody").innerHTML=its.map(i=>
    `<tr data-cat="${i.cat}" style="${f==="all"||f===i.cat?"":"display:none"}">`+
    `<td class="mono">${fmtTs(i.created_at)}</td>`+
    `<td>${esc(catZH(i.cat))}${i.cat2&&i.cat2!==i.cat?'<span class="muted">+'+esc(catZH(i.cat2))+'</span>':""}</td>`+
    `<td>${esc((i.title||"").slice(0,42))}</td>`+
    `<td class="muted">${esc((i.groups||[]).join("、"))}</td>`+
    `<td class="mono">${i.deadline?esc(String(i.deadline).slice(0,16)):"—"}<span class="muted"> ${dlLabel(i.deadline)}</span></td></tr>`
  ).join("")||'<tr><td colspan="5" class="muted">暂无信息（等源扫描或点「立即扫描」）</td></tr>';
}
$("filterBar").addEventListener("click",e=>{
  const chip=e.target.closest(".fchip");
  if(!chip)return;
  document.querySelectorAll(".fchip").forEach(c=>c.classList.remove("active"));
  chip.classList.add("active");
  renderStreamRows();
});

/* ═══ 提醒视图 ═══ */
function renderReminders(){
  const rm=(state.st&&state.st.reminders)||{};
  $("rScheduled").textContent=rm.scheduled||0;
  $("rSent").textContent=rm.sent||0;
  $("rErrors").textContent=rm.errors||0;
  const its=state.items||[];
  const dls=its.filter(i=>hoursLeft(i.deadline)!=null&&hoursLeft(i.deadline)>0&&hoursLeft(i.deadline)<168)
    .sort((a,b)=>dlTime(a.deadline)-dlTime(b.deadline));
  $("ddlTrackFull").innerHTML=dls.length?dls.map(i=>
    `<div class="mini"><span class="ic">⏰</span><span class="name">${esc(i.title.slice(0,26))}</span>`+
    `<span class="muted">${esc(String(i.deadline).slice(0,16))}</span>`+
    `<span class="dl">${dlLabel(i.deadline)}</span></div>`).join("")
    :'<div class="mini muted">未来 7 天无待触发 DDL</div>';
}

/* ═══ 订阅视图 ═══ */
function renderSubs(){
  const subs=state.subs||[];
  $("subsBody").innerHTML=subs.map(s=>
    `<tr><td class="mono">${esc(s.user_qq)}</td>`+
    `<td>${esc((s.groups||[]).join("、"))}</td>`+
    `<td>${(s.cats||[]).map(c=>`<span class="mini-tag">${esc(catZH(c))}</span>`).join("")}</td>`+
    `<td class="muted">${esc((s.quiet||[]).join(","))||"—"}</td>`+
    `<td>${s.digest?"Digest":"即时"}</td>`+
    `<td><button class="op danger" onclick="delSub('${esc(s.user_qq)}')">删除</button></td></tr>`
  ).join("")||'<tr><td colspan="6" class="muted">暂无订阅</td></tr>';
}

/* ═══ 配置页（传统表单） ═══ */
let settingsData=null, settingsDirty=false;

function setDirty(v){settingsDirty=v;$("dirtyBadge").classList.toggle("show",v)}

function fillSettings(d){
  settingsData=d;
  const env=d.env||{};
  document.querySelectorAll("#sDeliver input").forEach(el=>{el.checked=(env.DELIVER_MODE||[]).includes(el.value)});
  document.querySelectorAll("#sClassifier input").forEach(el=>{el.checked=env.CLASSIFIER===el.value});
  $("sAdminQq").value=env.ADMIN_QQ||"";
  const offs=env.REMINDER_OFFSETS||[24,3];
  $("sOff1").value=offs[0]??24;
  $("sOff2").value=offs[1]??"";
  $("sRemInterval").value=env.REMINDER_INTERVAL??60;
  $("sRemIntervalOut").textContent=(env.REMINDER_INTERVAL??60)+" 秒";
  $("sPushToken").value="";
  $("sPushToken").placeholder=env.PUSHPLUS_TOKEN_SET?"已配置（留空保持原值）":"未配置";
  $("sPushTopic").value=env.PUSHPLUS_TOPIC||"";
  $("sJevBase").value=env.JEV_BASE_URL||"";
  $("sJevKey").value="";
  $("sJevKey").placeholder=env.JEV_API_KEY_SET?"已配置（留空保持原值）":"未配置";
  $("sChatBase").value=env.CHAT_BASE_URL||"";
  $("sChatKey").value="";
  $("sChatKey").placeholder=env.CHAT_API_KEY_SET?"已配置（留空保持原值）":"未配置";
  $("sChatModel").value=env.CHAT_MODEL||"";
  const chain=env.SUBMIT_EXTRACT_CHAIN||["vision","big","small"];
  document.querySelectorAll("#sExtractChain input").forEach(el=>{el.checked=chain.includes(el.value)});
  $("sSources").innerHTML=(d.sources||[]).map(s=>
    `<div class="src-row" data-id="${esc(s.id)}">`+
    `<div><span class="src-name">${esc(s.name)}</span><span class="src-kind">${esc(s.kind)}</span></div>`+
    `<label class="switch"><input type="checkbox" data-src-enabled ${s.enabled?"checked":""}><span></span></label>`+
    `<input type="number" min="60" max="86400" step="60" value="${s.interval}" data-src-interval title="扫描间隔（秒）"></div>`
  ).join("")||'<div class="sub">暂无采集源</div>';
  document.querySelectorAll("#sWechatLayer input").forEach(el=>{el.checked=(d.wechat?.extract_layer||"big")===el.value});
  $("sWechatInterval").value=d.wechat?.interval??1800;
  $("sLectureKeyword").value=d.lectures?.keyword||"";
  setDirty(false);
}

async function loadSettings(){
  const r=await api("/api/settings");
  if(!r.ok){toast("配置加载失败："+(r.error||""));return}
  fillSettings(r);
}

function collectSettings(){
  const env={
    DELIVER_MODE:[...document.querySelectorAll("#sDeliver input:checked")].map(e=>e.value),
    CLASSIFIER:(document.querySelector("#sClassifier input:checked")||{}).value||"stub",
    ADMIN_QQ:$("sAdminQq").value.trim(),
    REMINDER_OFFSETS:[$("sOff1").value,$("sOff2").value].filter(v=>v!=="").map(Number),
    REMINDER_INTERVAL:Number($("sRemInterval").value),
    PUSHPLUS_TOKEN:$("sPushToken").value.trim(),
    PUSHPLUS_TOPIC:$("sPushTopic").value.trim(),
    JEV_BASE_URL:$("sJevBase").value.trim(),
    JEV_API_KEY:$("sJevKey").value.trim(),
    CHAT_BASE_URL:$("sChatBase").value.trim(),
    CHAT_API_KEY:$("sChatKey").value.trim(),
    CHAT_MODEL:$("sChatModel").value.trim(),
    SUBMIT_EXTRACT_CHAIN:[...document.querySelectorAll("#sExtractChain input:checked")].map(e=>e.value),
  };
  const sources=[...document.querySelectorAll("#sSources .src-row")].map(row=>({
    id:row.dataset.id,
    enabled:row.querySelector("[data-src-enabled]").checked,
    interval:Number(row.querySelector("[data-src-interval]").value),
  }));
  return {
    env, sources,
    wechat:{extract_layer:(document.querySelector("#sWechatLayer input:checked")||{}).value||"big",
            interval:Number($("sWechatInterval").value)},
    lectures:{keyword:$("sLectureKeyword").value.trim()},
  };
}

async function saveSettings(){
  if(!settingsData)return false;
  const body=collectSettings();
  if(!body.env.DELIVER_MODE.length){toast("分发方式至少选一个");return false}
  const r=await api("/api/settings",{method:"POST",body:JSON.stringify(body)});
  if(!r.ok){toast("保存失败："+(r.error||""));return false}
  toast("已保存，重启后台进程后生效");
  await loadSettings();
  refreshAll();
  return true;
}

async function confirmSettings(){
  if(await saveSettings()){
    document.querySelectorAll(".nav-item").forEach(n=>n.classList.remove("active"));
    document.querySelector('.nav-item[data-view="dashboard"]').classList.add("active");
    document.querySelectorAll(".view").forEach(s=>s.classList.remove("active"));
    $("view-dashboard").classList.add("active");
    $("crumbNow").textContent=VIEW_TITLES.dashboard;
  }
}

function resetSettings(){
  if(!settingsData)return;
  if(!confirm("恢复默认配置？未保存前可通过「取消」放弃。"))return;
  const d=settingsData.defaults||{}, env=d.env||{};
  document.querySelectorAll("#sDeliver input").forEach(el=>{el.checked=(env.DELIVER_MODE||["file"]).includes(el.value)});
  document.querySelectorAll("#sClassifier input").forEach(el=>{el.checked=env.CLASSIFIER===el.value});
  $("sAdminQq").value=env.ADMIN_QQ||"";
  $("sOff1").value=(env.REMINDER_OFFSETS||[24,3])[0];
  $("sOff2").value=(env.REMINDER_OFFSETS||[24,3])[1]??"";
  $("sRemInterval").value=env.REMINDER_INTERVAL??60;
  $("sRemIntervalOut").textContent=(env.REMINDER_INTERVAL??60)+" 秒";
  $("sPushToken").value="";
  $("sPushTopic").value=env.PUSHPLUS_TOPIC||"";
  $("sJevBase").value=env.JEV_BASE_URL||"";$("sJevKey").value="";
  $("sChatBase").value=env.CHAT_BASE_URL||"";$("sChatKey").value="";
  $("sChatModel").value=env.CHAT_MODEL||"";
  document.querySelectorAll("#sExtractChain input").forEach(el=>{
    el.checked=(env.SUBMIT_EXTRACT_CHAIN||[]).includes(el.value)});
  document.querySelectorAll("#sSources .src-row").forEach(row=>{
    row.querySelector("[data-src-enabled]").checked=true;
    row.querySelector("[data-src-interval]").value=d.source_interval||900;
  });
  document.querySelectorAll("#sWechatLayer input").forEach(el=>{
    el.checked=(d.wechat?.extract_layer||"big")===el.value});
  $("sWechatInterval").value=d.wechat?.interval??1800;
  $("sLectureKeyword").value=d.lectures?.keyword||"";
  setDirty(true);
  toast("已填入默认值，保存后生效");
}

async function cancelSettings(){
  if(settingsDirty&&!confirm("放弃未保存的修改？"))return;
  await loadSettings();
  toast("已取消未保存的修改");
}

document.getElementById("settingsForm").addEventListener("input",e=>{
  setDirty(true);
  if(e.target.id==="sRemInterval")$("sRemIntervalOut").textContent=e.target.value+" 秒";
});
document.getElementById("settingsForm").addEventListener("change",()=>setDirty(true));

/* ═══ 全量刷新 ═══ */
async function refreshAll(){
  const st=await api("/api/status");
  if(st.ok)state.st=st;
  $("dot").style.background=st.running?"var(--accent)":"var(--danger)";
  $("dotTxt").textContent=st.running?"运行中":"已停止";
  $("deliverMode").textContent=st.deliver_mode||"—";
  const its=await api("/api/items?limit=30");
  if(its.ok)state.items=its.items||[];
  const sb=await api("/api/subs");
  if(sb.ok)state.subs=sb.subs||[];
  renderDashboard();renderSources();renderStream();renderReminders();renderSubs();
}
$("btnRefresh").addEventListener("click",()=>{refreshAll();toast("已刷新")});

/* ═══ 操作 ═══ */
async function scan(id){
  toast("扫描中…");
  const r=await api("/api/scan/"+id,{method:"POST",body:"{}"});
  toast(r.ok?("新增 "+r.new+" 条"):("失败："+(r.error||"")));
  refreshAll();
}
async function saveSub(){
  const qq=$("fQq").value.trim(),groups=$("fGroups").value.trim(),
        cats=$("fCats").value.split(/[,，]/).map(s=>CATMAP[s.trim()]||s.trim()).filter(Boolean);
  if(!qq||!groups||!cats.length)return toast("请填全：用户QQ / 群 / 类别");
  const r=await api("/api/subs",{method:"POST",body:JSON.stringify({
    user_qq:qq,
    groups:groups.split(/[,，]/).map(s=>s.trim()).filter(Boolean),
    cats:cats,
    digest:$("fGran").value==="digest",
  })});
  toast(r.ok?"已保存（重启后生效）":"失败："+(r.error||""));
  refreshAll();
}
async function delSub(qq){
  if(!confirm("删除 "+qq+" 的订阅？"))return;
  const r=await api("/api/subs/"+qq,{method:"DELETE"});
  toast(r.ok?"已删除":"失败："+(r.error||""));
  refreshAll();
}
async function testPush(){
  const r=await api("/api/test-push",{method:"POST",body:JSON.stringify({
    qq:$("tQq").value.trim()||"tester",
    token:$("tToken").value.trim()||null})});
  toast(r.ok?("已发送："+r.detail):("失败："+(r.error||"")));
}

/* ═══ 启动 ═══ */
refreshAll();
setInterval(refreshAll,15000);
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
                "enabled": src.enabled,
                # 配置已启用但启动时未注册轮询器（改配置后未重启）→ 前端提示「待重启」
                "pending_restart": bool(src.enabled and p is None),
                "last_scan_at": st.get("last_scan_at", 0),
                "new": st.get("new", 0),
                "errors": st.get("errors", 0),
                "last_error": st.get("last_error", ""),
            })
        # 临期提醒调度统计（reminder.py：scheduled/sent/errors）
        sch = getattr(self.runtime, "scheduler", None)
        reminders = dict(sch.stats) if sch is not None else {}
        return {
            "ok": True, "running": True,
            "uptime_s": int(time.time() - self.started_at),
            "deliver_mode": s.deliver_mode,
            "sources": sources,
            "runner": self.runtime.runner.stats,
            "reminders": reminders,
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
            "quiet": ["23:00-07:00"], "instant_min_urg": 2,
            "digest": bool(payload.get("digest", True))}
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
            raise ValueError(
                f"源 {source_id} 已启用但尚未注册：改完 web-sources.yml 后需重启后台进程。")
        try:
            fut = asyncio.run_coroutine_threadsafe(p.poll_once(), self.loop)
            return {"ok": True, "new": fut.result(timeout=120)}
        except Exception as e:
            # 手动扫描失败也写回状态，监控源表格能立即看到自然语言错误
            p.stats["errors"] = p.stats.get("errors", 0) + 1
            p.stats["last_error"] = friendly_error(e)
            raise

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

    # ------------------------------------------------------------ 结构化配置

    def settings_view(self) -> dict:
        """配置页数据（密钥只回「是否已配置」，不回明文）。"""
        s = self.runtime.settings
        env = settings_io.read_env(runtime_root() / ".env")

        def _split(v: str) -> list[str]:
            return [x.strip() for x in str(v).split(",") if x.strip()]

        def _int(v, default: int) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        offsets = []
        for x in _split(env.get("REMINDER_OFFSETS", "24,3")):
            try:
                offsets.append(int(x))
            except ValueError:
                continue
        wechat = settings_io.read_yaml(s.config_dir / "wechat-mp.yml")
        lectures = settings_io.read_yaml(s.config_dir / "seu-lectures.yml")
        sources = [{
            "id": src.id, "name": src.name, "kind": src.kind,
            "enabled": src.enabled, "interval": src.interval,
        } for src in load_web_sources(s.config_dir / "web-sources.yml").sources]
        return {
            "ok": True,
            "env": {
                "DELIVER_MODE": _split(env.get("DELIVER_MODE", s.deliver_mode)),
                "CLASSIFIER": env.get("CLASSIFIER", s.classifier),
                "ADMIN_QQ": env.get("ADMIN_QQ", s.admin_qq),
                "REMINDER_OFFSETS": offsets or [24, 3],
                "REMINDER_INTERVAL": _int(env.get("REMINDER_INTERVAL"), s.reminder_interval),
                "PUSHPLUS_TOKEN_SET": bool(env.get("PUSHPLUS_TOKEN") or s.pushplus_token),
                "PUSHPLUS_TOPIC": env.get("PUSHPLUS_TOPIC", s.pushplus_topic),
                "JEV_BASE_URL": env.get("JEV_BASE_URL", s.jev_base_url),
                "JEV_API_KEY_SET": bool(env.get("JEV_API_KEY") or s.jev_api_key),
                "CHAT_BASE_URL": env.get("CHAT_BASE_URL", s.chat_base_url),
                "CHAT_API_KEY_SET": bool(env.get("CHAT_API_KEY") or s.chat_api_key),
                "CHAT_MODEL": env.get("CHAT_MODEL", s.chat_model),
                "SUBMIT_EXTRACT_CHAIN": _split(
                    env.get("SUBMIT_EXTRACT_CHAIN", ",".join(s.submit_extract_chain))),
            },
            "sources": sources,
            "wechat": {
                "extract_layer": str(wechat.get("extract_layer") or "big"),
                "interval": _int(wechat.get("interval"), 1800),
            },
            "lectures": {"keyword": str(lectures.get("keyword") or "")},
            "defaults": {
                "env": {
                    "DELIVER_MODE": ["file"], "CLASSIFIER": "stub", "ADMIN_QQ": "",
                    "REMINDER_OFFSETS": [24, 3], "REMINDER_INTERVAL": 60,
                    "PUSHPLUS_TOPIC": "",
                    "JEV_BASE_URL": "https://tokenrhythm.studio",
                    "CHAT_BASE_URL": "https://tokenrhythm.studio",
                    "CHAT_MODEL": "neohorse-1-9b",
                    "SUBMIT_EXTRACT_CHAIN": ["vision", "big", "small"],
                },
                "wechat": {"extract_layer": "big", "interval": 1800},
                "lectures": {"keyword": ""},
                "source_interval": 900,
            },
        }

    def save_settings(self, payload: dict) -> dict:
        """校验并写回 .env / web-sources.yml / wechat-mp.yml / seu-lectures.yml。"""
        s = self.runtime.settings
        env_in = payload.get("env") or {}

        modes = [m for m in (env_in.get("DELIVER_MODE") or [])
                 if m in ("file", "pushplus", "qq")]
        if not modes:
            raise ValueError("分发方式至少选择一个（file / pushplus / qq）")
        classifier = str(env_in.get("CLASSIFIER") or "stub")
        if classifier not in ("stub", "tree"):
            raise ValueError("分类器只能是 stub 或 tree")
        admin_qq = str(env_in.get("ADMIN_QQ") or "").strip()
        if admin_qq and not admin_qq.isdigit():
            raise ValueError("管理员 QQ 只能填数字")

        offsets: list[int] = []
        for x in env_in.get("REMINDER_OFFSETS") or []:
            try:
                v = int(x)
            except (TypeError, ValueError):
                raise ValueError("提醒提前量必须是整数小时")
            if not 1 <= v <= 168:
                raise ValueError("提醒提前量需在 1–168 小时之间")
            offsets.append(v)
        if not offsets or len(offsets) > 4:
            raise ValueError("提醒提前量需 1–4 个")
        interval = int(env_in.get("REMINDER_INTERVAL") or 60)
        if not 15 <= interval <= 3600:
            raise ValueError("提醒扫描间隔需在 15–3600 秒之间")

        updates = {
            "DELIVER_MODE": ",".join(modes),
            "CLASSIFIER": classifier,
            "ADMIN_QQ": admin_qq,
            "REMINDER_OFFSETS": ",".join(str(v) for v in offsets),
            "REMINDER_INTERVAL": str(interval),
            "PUSHPLUS_TOPIC": str(env_in.get("PUSHPLUS_TOPIC") or "").strip(),
            "CHAT_MODEL": str(env_in.get("CHAT_MODEL") or "").strip(),
            "SUBMIT_EXTRACT_CHAIN": ",".join(
                [x for x in (env_in.get("SUBMIT_EXTRACT_CHAIN") or [])
                 if x in ("vision", "big", "small")] or ["vision", "big", "small"]),
        }
        # 密钥：留空表示保持原值，绝不把占位符写回
        for key in ("PUSHPLUS_TOKEN", "JEV_API_KEY", "CHAT_API_KEY"):
            val = str(env_in.get(key) or "").strip()
            if val:
                updates[key] = val
        for key in ("JEV_BASE_URL", "CHAT_BASE_URL"):
            val = str(env_in.get(key) or "").strip().rstrip("/")
            if val and not val.startswith(("http://", "https://")):
                raise ValueError(f"{key} 必须以 http:// 或 https:// 开头")
            updates[key] = val

        valid_ids = {src.id for src in
                     load_web_sources(s.config_dir / "web-sources.yml").sources}
        src_changes: dict[str, dict] = {}
        for item in payload.get("sources") or []:
            sid = str(item.get("id") or "").strip()
            if sid not in valid_ids:
                raise ValueError(f"未知采集源：{sid}")
            iv = int(item.get("interval") or 900)
            if not 60 <= iv <= 86400:
                raise ValueError(f"{sid} 的扫描间隔需在 60–86400 秒之间")
            src_changes[sid] = {"enabled": bool(item.get("enabled")),
                                "interval": iv}

        wechat = payload.get("wechat") or {}
        layer = str(wechat.get("extract_layer") or "big")
        if layer not in ("big", "small"):
            raise ValueError("公众号提取层只能是 big 或 small")
        w_interval = int(wechat.get("interval") or 1800)
        if not 60 <= w_interval <= 86400:
            raise ValueError("公众号扫描间隔需在 60–86400 秒之间")

        lectures = payload.get("lectures") or {}
        keyword = str(lectures.get("keyword") or "").strip()

        # 全部校验通过后再落盘，避免半写状态
        settings_io.update_env(runtime_root() / ".env", updates)
        settings_io.update_web_sources(
            s.config_dir / "web-sources.yml", src_changes)
        settings_io.update_simple_yaml(
            s.config_dir / "wechat-mp.yml",
            {"extract_layer": layer, "interval": w_interval})
        settings_io.update_simple_yaml(
            s.config_dir / "seu-lectures.yml", {"keyword": keyword})

        return {"ok": True, "restart_required": True,
                "updated": ["env", "web-sources.yml", "wechat-mp.yml",
                            "seu-lectures.yml"]}

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
                # 原始堆栈在服务端日志里；API 只回自然语言（DNS/超时/登录页等）
                return jsonify({"ok": False, "error": friendly_error(e)}), 400
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

    @app.get("/api/settings")
    @guard
    def _settings():
        return ctx.settings_view()

    @app.post("/api/settings")
    @guard
    def _save_settings():
        return ctx.save_settings(request.get_json(force=True))

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
