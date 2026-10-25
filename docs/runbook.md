# 操作手册（runbook）

> 版本 v0.1 · 2026-10-25 · P0/P1 的操作步骤。所有命令在项目根 `<项目根>` 执行；venv、pip 缓存、数据、NapCat 全部在项目内。

## 0. 一次性环境搭建（已完成 ✅）

```bash
py -V:3.13 -m venv .venv
set PIP_CACHE_DIR=%CD%\.pipcache
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m qq_relay.store.db      # 建 10 张表
.venv\Scripts\python -m pytest                 # 22 项测试
```

> Windows 控制台中文输出乱码时，先 `set PYTHONIOENCODING=utf-8`。

## 1. NapCat 安装与配置（待用户操作）

**安装**：`napcat/NapCat.Shell.Windows.Node.zip` 已下载（v4.18.41，Node 运行时自带，无需装 Node）。解压到 `napcat/`，运行启动器（`NapCat.Shell.Windows.Node.bat` 或解压出的 launcher）。

**配置 OneBot 11 反向 WS**（两种方式任选）：

- **WebUI**（推荐）：启动后浏览器开 `http://127.0.0.1:6099` → OneBot 11 配置 → 新增**反向 WebSocket 客户端**：
  - URL：`ws://127.0.0.1:3001`
  - Token：与 `.env` 里 `ONEBOT_TOKEN` 一致（改了任一边就两边一起改）
  - 消息格式：array
- **配置文件**：`napcat/config/onebot11_<你的QQ号>.json`，`network.websocketClients` 里加：
  ```json
  { "enable": true, "name": "qq-relay", "url": "ws://127.0.0.1:3001",
    "messagePostFormat": "array", "reportSelfMessage": false,
    "reconnectInterval": 3000, "token": "与 .env 一致" }
  ```

**扫码登录（关键，只能你来）**：

- 用**小号**，**备用机**扫码（小号扫码会把该号手机 QQ 顶掉线；别用主号、别用刚注册的号）
- 登录成功后 NapCat 会自动连出反向 WS 到我们的 `127.0.0.1:3001`

## 2. 冒烟（验收 A1）

```bash
.venv\Scripts\python -m qq_relay.smoke --seconds 300     # 5 分钟观察
.venv\Scripts\python -m qq_relay.smoke --forever         # 持续跑，Ctrl-C 退出
```

**通过的判据**：控制台逐条打印群消息（含群名/发送者/延迟秒数），`data/logs/smoke-*.jsonl` 有原始事件。

**拿到群号**：冒烟日志里每条事件的 `group_id`/`group_name`——把它们填进 `config/groups.yml`（P3 画像用；P1 预筛先用通用词）。

## 3. 排障

| 现象 | 原因 / 处理 |
|---|---|
| 冒烟一直"连接 0 次" | NapCat 没连出来：① 反向 WS 配置的 URL/端口不对（我们是服务端，NapCat 来连）；② token 两边不一致；③ 冒烟没先启动（顺序：先起冒烟，再配/重启 NapCat） |
| 连上但立刻断 | token 不匹配（服务端回 4001 关闭）；核对 `.env` 与 NapCat 配置 |
| 端口 3001 被占用 | `netstat -ano \| findstr :3001` 找到占用进程；或改 `.env` 的 `ONEBOT_REVERSE_PORT`（两边同步） |
| 扫码后反复掉线 | 风控/互挤：换备用机、老号； NapCat 日志里看登录态 |
| 中文乱码 | `set PYTHONIOENCODING=utf-8` 后再运行 |
| 事件收得到但没有群消息 | 只解析 `message_type=group` 的事件；私聊/通知按设计忽略（见 onebot.py） |

## 4. P1 主管道（冒烟通过后）

```bash
.venv\Scripts\python -m qq_relay.main --seconds 300     # 5 分钟观察
.venv\Scripts\python -m qq_relay.main --forever         # 持续跑
```

**会发生什么**：

- 群消息 → 预筛链（发送者过滤[默认关] → 去重 → 关键词）→ 假分类器 → 订阅匹配 → **写文件**
- 每条推送落到 `data/outbox/<用户QQ>/<时间戳>_<类别>_<事件号>.txt`；低紧急度进 `digest-<日期>.txt`
- 同一条通知在多个群出现只分类一次（fan-in），只给新命中群的用户补文件
- 私聊 bot 可下命令：`/sub 群 <群名|all> 类别 <活动 通知 …>`、`/sub list`、`/unsub`、`/mute 23:00-07:00`、`/digest on|off`；回复"不感兴趣"记录负反馈

**检查点**：往测试群贴一条含"作业/截止"的通知 → 30 秒内 `data/outbox/<你的QQ>/` 出现 txt；灌水群不应产生任何新文件（验收 A3/A5）。

**当前订阅用户**：编辑 `config/subscriptions.yml` 或让用户私聊发 `/sub`（双通道同一份数据，ADR-018）。

## 5. P2 预告（P1 真实群验证后）

JEV 分类树替换假分类器（`CLASSIFIER=tree`）：连通性测试先行（禁思考参数）→ JEV 客户端（队列/退避/缓存）→ L4 小模型提取 → 金标准 harness 校准。
