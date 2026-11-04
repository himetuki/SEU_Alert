# SEU_Alert · 校园信息聚合与强提醒引擎

> 多源采集 → 分类 → 按订阅匹配 → 多渠道推送 + 临期提醒

把散落在 **QQ 群、教务处与各学院官网、讲座预约系统、公众号** 里的通知、作业、考试、
讲座、竞赛、DDL 等信息聚合起来，按每个人的需要分成**订阅推送**，并在截止前多轮强提醒。

本项目只做**内容与决策引擎**（采集 → 分类 → 匹配 → 分发）；公众号、H5 看板等前端触点
由独立仓库负责，引擎通过配置文件与数据导出对接。

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## 痛点

大学里的重要信息高度分散：作业与考试通知在课程群、教务通知在教务处网站、学院通知在各自
官网、讲座信息在预约系统、临时通知在公众号。同学要在多个平台之间反复翻找，**漏看**是常态，
而**错过截止时间**的代价往往不可逆。

## 核心能力

| 能力 | 说明 |
|---|---|
| **多源采集** | 教务处六栏目、33 个学院官网、讲座预约系统、劳动教育平台、公众号；QQ 群作为可选内部通道 |
| **渠道画像 + 预筛** | 每个群/站点有画像（类别先验、预筛词、发送者过滤），低成本挡掉灌水，**宁漏勿误** |
| **JEV 分类树** | 封闭集判断交给结构化决策模型（根调用 + 按类别分支），分类一次、匹配多次 |
| **投稿提取栈** | OCR / 视觉模型 → 大模型 → 小模型的降级链，把图片与口语化投稿转成规范通知 |
| **按需订阅** | 「群/站点 × 类别 × 关键词 × 免打扰时段」，支持即时与 Digest 两种粒度 |
| **多渠道分发** | 文件（测试期留档）、PushPlus（微信强推送）、QQ 私聊（内部测试），可组合 |
| **临期提醒** | 带 deadline 的通知在截止前多轮提醒（默认 24h / 3h，可配），到点即发、不重复发 |
| **核验数据层** | `+1 确认 / 报错` 双向反馈，多人确认后标记为已核验 |
| **自包含采集** | 不依赖任何外部程序先跑一遍；直接抓取公开页面 |

## 采集源

| 源 | 方式 | 状态 |
|---|---|---|
| 教务处六栏目（最新动态/教务信息/学籍管理/实践教学/国际交流/文化素质教育） | 直采（WebPlus CMS 解析） | ✅ 默认启用 |
| 33 个学院官网通知 | 直采（自动发现列表页） | ✅ 默认启用 |
| 人文讲座预约系统 | 直采（**仅监控，不预约、不抢票**） | ✅ 默认启用 |
| 人文讲座网站（文化素质教育 + 六朝松大师讲堂） | 直采（复用 jwc 解析器，群 = `web-lecture`） | ✅ 默认启用 |
| 劳动教育课程平台 | 直采（CAS 登录 + 课程表解析） | ✅ 默认启用（需校内网） |
| 微信公众号文章 | 免登录发现 + 模型代读为结构化字段；讲座并入 `web-lecture` | ✅ 默认启用 |
| SEUdaily 输出库 | 消费其网页库 | ✅ 默认启用 |
| QQ 群消息 | OneBot 11 反向 WebSocket（自建薄层） | ⭕ 可选，内部通道 |
| SEU-Monitor 归档库 | 消费其归档数据（**Windows 原生生成器**，无需 Go/WSL） | ✅ 已启用 |

采集源在 `config/web-sources.yml` 配置，`enabled: false` 的源不参与轮询。

## 架构

```
L0 采集 → L1 预筛（发送者过滤/去重/关键词）→ L2 分类根调用
        → L3 按类别分支 → L4 按需提取（DDL 等字段）
        → L5 订阅匹配（群/站点 × 类别）→ L6 分发（file / PushPlus / QQ）
                                        ↳ 临期提醒调度（每分钟 tick）
```

设计要点：**封闭集交给结构化决策模型，开放集抽取交给小模型，字面匹配交给规则，
元数据交给画像**——模型调用量沿「免费 → 便宜 → 贵」单向递增，多数消息在 L0/L1 就被挡掉。

细节见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

```bash
# 1. 环境（Python 3.11+；建议 venv 建在项目内）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/macOS

# 2. 配置：复制模板后填密钥
cp .env.example .env          # 模型密钥、PushPlus token、各源会话
cp config/subscriptions.yml.example config/subscriptions.yml   # 首次启动也会自动生成

# 3. 运行
python -m seu_alert.main       # 主管道（采集 + 分发 + 提醒）
python -m seu_alert.admin      # 后台管理界面（浏览器打开 127.0.0.1:8000）
python -m seu_alert.admin --no-browser   # 不自动开浏览器（Edge 以管理员运行时常用）

# 4. 测试
python -m pytest -q
```

`.env`、`config/subscriptions.yml` 含个人凭据与用户 QQ，**不入版本库**（仓库只保留
`.example` 模板）。

## 部署形态

| 形态 | 产物 | 说明 |
|---|---|---|
| **Windows 便携版** | `dist/seu_alert-portable-win/`（zip） | PyInstaller one-dir，双击即跑，无需 Python；数据与配置在 exe 同级目录 |
| **Linux 服务器版** | `dist/seu_alert-portable-server/`（tar.gz） | 无头二进制 + systemd unit；绑定 `0.0.0.0:8000`，适合常驻服务器 |
| **源码运行** | — | `python -m seu_alert.main` / `-m seu_alert.admin` |

构建源码分别在 [`win/`](win/) 与 [`linux/`](linux/)；产物一律输出到 `dist/`（已 gitignore）。

**CI 自动构建与分发**：[`.github/workflows/build.yml`](.github/workflows/build.yml) 在
push / PR 时跑测试并构建两个平台，打 `v*` tag 时发布 GitHub Release。

> AGPL-3.0 第 13 条要求：若修改后的版本通过网络对外提供服务，须向远程用户提供对应源码。
> 服务器部署请留意这一点。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 分层架构、管线图、数据契约、关键不变量、部署、风险 |
| [docs/classification.md](docs/classification.md) | 类别体系、分类根调用与分支题干、提取契约、限流防线、阈值校准 |
| [docs/config.md](docs/config.md) | `groups.yml` / `tree.yml` / 订阅 schema / 采集源 schema |
| [docs/decisions.md](docs/decisions.md) | 全部设计决策记录（ADR），含被否方案与理由 |
| [docs/build-plan.md](docs/build-plan.md) | 分阶段搭建规划 |
| [docs/runbook.md](docs/runbook.md) | 操作手册：环境、反向 WS、投稿、提醒、排障、打包 |
| [docs/acceptance.md](docs/acceptance.md) | 功能验收标准 |
| [docs/open-questions.md](docs/open-questions.md) | 已知缺口与当前进度 |
| [docs/portable-readme.md](docs/portable-readme.md) | 便携版使用者说明 |

## 项目结构

```
src/seu_alert/
├── adapters/            # 采集：onebot（QQ 反向 WS）、web/*（各站点直采）、user_report（投稿）
├── pipeline/            # 预筛 → 分类 → 提取栈 → 匹配 → 提醒 → 编排
├── deliver/             # 分发出口：file / pushplus / qq
├── store/               # SQLite schema、连接、查询
├── admin.py             # 后台管理（Flask）
├── botcmd.py            # /sub /unsub /mute /digest /confirm /report
├── config.py            # 配置加载与校验（.env + YAML）
└── contracts.py         # RawEvent / ClassifiedEvent 数据契约
config/                  # 群画像、分类树、订阅模板、各采集源配置
win/ · linux/            # 两个平台的构建源码
tests/                   # pytest（含真实页面夹具）
```

## 参考项目与致谢

本项目在若干校内已有项目的基础上搭建，架构、数据结构与登录实现参考了下列项目，一并致谢：

| 参考项目 | 类型 | 本项目借鉴的部分 | 说明 |
|---|---|---|---|
| [miunerofrade/SEU-Monitor](https://github.com/miunerofrade/SEU-Monitor) | Go · 教务处通知监控 CLI | 归档数据目录约定（历史通道消费其归档；教务处采集为**独立实现**） | **许可未声明**（仓库无 LICENSE）；本项目未复制其源码，详见 [NOTICE](NOTICE) |
| [miunerofrade/SEUdaily](https://github.com/miunerofrade/SEUdaily) | TypeScript + Python · 校园助手 | 网页库输出结构与通知 markdown + metadata 形态 | 开源；MIT |
| SEU-Labor-Course-Pusher | Rust · 劳动教育课程平台推送器 | 课程表解析 + CAS 登录（RSA）语义 | MIT |
| seu-lecture-cli | Python · 人文讲座预约 CLI | 讲座列表分页解析（**仅监控，不移植预约/抢票**） | MIT |
| [NapCat](https://github.com/NapCatQQ/NapCat) | OneBot 11 实现 | 反向 WS 事件协议、token 鉴权 | 协议级参考，不依赖其代码 |
| [PushPlus](https://www.pushplus.plus/) | 微信模板消息推送服务 | 订阅制 token 推送通道 | 第三方服务 |
| JEV（NeoHorse-Jev-4B） | 分类模型服务 | `/v1/decision` 分类树（1–16 题 noul/choice/score） | 模型服务 |

**使用边界**：本项目只参考架构与数据形态，不复制上述项目的可执行分发物。各参考项目的版权
与许可归原作者所有，详见 [NOTICE](NOTICE)。

## 许可证

本项目以 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布：

- 全文：[LICENSE](LICENSE)
- 第三方与衍生来源声明：[NOTICE](NOTICE)

要点：可以自由使用、修改、再分发，但**衍生作品整体必须以 AGPL-3.0 发布**；并且若通过网络
向用户提供服务，**必须向这些用户提供对应源码**（第 13 条）。本项目参考/移植的
SEUdaily、SEU-Labor-Course-Pusher、seu-lecture-cli 均为 MIT，与 AGPL-3.0 兼容。

## 免责声明

本项目为**非官方**工具，仅供学习交流及在**授权范围内**查询、聚合校园信息。

- 使用者应遵守所在学校的信息管理规定，妥善保管账号、Cookie 与会话凭据；
- **不得**将受限的校内信息转发给未获授权的人员，或用于其他未经授权的用途；
- 讲座模块**只监控、不代预约、不抢票**；请遵守学校相关系统的使用规则；
- 请合理设置采集间隔，避免对学校站点造成压力；
- 因使用或滥用本项目造成的任何后果，由使用者自行承担。

## 参与修改的约定

1. **先改文档再改代码**：任何设计变更先更新 `docs/`，保持文档是唯一权威。
2. **决策必须留痕**：每个设计决策在 `docs/decisions.md` 追加一条 ADR（背景/决定/理由/被否方案/后果），改决策时**新增** ADR 而非静默修改旧条目。
3. **配置 schema 唯一权威在 `docs/config.md`**：代码实现以它为准。