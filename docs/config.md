# 配置 schema

> 版本 v0.1 · 2026-10-25 · 配置 schema 的唯一权威。**分类树和画像都是配置不是代码**——加一层树 = 加一段 YAML + 在金标准集上校准，不动管道代码。

## groups.yml（群画像 + 发送者过滤）

```yaml
groups:
  "123456789":                        # group_id：绑定用 id，改名/换届不失效；name 只是标签
    name: 马原群
    kind: course                      # course | grade | cadre | class | program | club | other
    course: 马原                       # kind=course 时绑定；多群可绑同一门课（理论+习题课）
    scope: course                     # course | grade | class | school
    prefilter: [作业, DDL, 截止, 考试, 范围, 提交, 大作业]   # 画像词，与通用词取并集
    default_cats: [homework, exam]    # 该群常见类别（先验，不替代 JEV 判断）
    roles:                            # 发送者 → 角色，user_id 为准，note 仅备注
      "10001": { role: 课程老师, note: 王老师 }
      "10003": { role: 课代表,   note: 小陈 }
    sender_filter:                    # 可选有损过滤器：默认 off，四原则见 classification.md
      mode: "off"                     # off | whitelist | blacklist；YAML 会把 off/on 解析成布尔，必须加引号
      whitelist: []                   # user_id 列表
      blacklist: []
      roles: { allow: [], deny: [] }  # 角色表达（复用上面的角色表），比 id 耐换届
      dry_run: false                  # true = 只记录不滤除；上线前先跑 24h 看代价
      log_filtered: true              # 被滤消息全文入审计日志，供 /filter audit 复盘

  "987654321":
    name: 2024级年级群
    kind: grade
    scope: grade
    prefilter: [竞赛, 报名, 收集, 填写, 活动, 大会, 通知]
    default_cats: [competition, task, lecture, notice]
    roles:
      "20001": { role: 辅导员, note: 李导员 }
    sender_filter: { mode: blacklist, blacklist: ["30099"], dry_run: false, log_filtered: true }

# 角色 → 类别先验：用于 state 上下文、L3 分支先验、默认 urg；不替代 JEV 内容判断
role_prior:
  课程老师:   [homework, exam]
  辅导员:     [notice, task]
  教务处老师: [exam, notice]
  班干部:     [task, lecture]
  课代表:     [homework, task]
  unknown:    [全部]
```

**新群引导（进群 onboarding）**：bot 首次在某群发言或被拉入 → DM 管理员：检测到群名、群主、管理员清单 → 按群名自动猜画像（群名含课程名 → course；"级/年级" → grade；"班干部" → cadre；"SRTP/大创" → program）→ **猜测永远待确认，不静默生效** → 管理员用命令或直接编辑 YAML 完成配置。`unknown` 角色回退全量 9 类。

## tree.yml（分类树）

```yaml
root:                                  # L2 · JEV 根调用
  call: jev
  questions: [is_info, cat, cat2, urg, has_ddl, action]
  drop_if: { is_info_below: 0.6, cat_in: [chat] }
  state_max_chars: 1500                # 自行截断，防上游 422

branches:                              # L3 · 按 cat 条件触发
  - when: { cat: [homework, exam] }
    questions: [channel, exam_type]    # exam_type 仅 exam；画像已绑课程则无 course_noul
    course_noul_when: "画像未绑定课程"   # 别名词典预筛 1~3 门 → noul 确认
  - when: { cat: [competition] }
    questions: [reg_ddl, final_ddl, team]
  - when: { cat: [research] }
    questions: [stage]                 # 立项/选题/开题/中期/结题/分数
  - when: { cat: [exchange] }
    questions: [program_type, eligibility]
  - when: { cat: [lecture] }
    questions: [format, signup]
  - when: { cat: [task] }
    questions: [form_channel, scope]
  - when: { cat: [notice] }
    questions: [scope]

extract:                               # L4 · Chat 小模型，按需触发
  trigger: "该字段规则未拿到 ∧ has_ddl(或类别需要) ∧ len<=1500"
  call: chat                           # neohorse-1-9b，禁思考参数
  fields:
    homework: [deadline]
    exam: [exam_time]
    competition: [deadlines(reg, final)]
    research: [deadline]
    exchange: [deadline]
    lecture: [time, place]
    task: [deadline]
    notice: []
  fallback: "重试1次 → 规则结果 → 见原文 + low_conf 进复核队列"
```

## classification.yml（本地规则分类树，与 JEV 独立）

`CLASSIFIER=stub` 时使用；不花模型调用。与 `tree.yml`（JEV 分类）是两份独立配置。

```yaml
rules:
  - cat: competition                   # 9 类之一
    priority: 90                       # 同分时的优先级
    urg: 2
    action: signup
    keywords: [竞赛, 大赛, 数学建模]    # 命中数 ×100 + priority
    exclude: [公示, 名单, 获奖]         # 命中即整条规则作废（只看标题）
overrides:
  notice_title: [公示, 名单, 获奖]      # 标题命中 → 强制 notice
  news_title: [顺利举办, 荣获, 开幕]     # 新闻/报道标题 → 强制 notice
prefix_categories:                     # 标题开头【讲座】【国际交流】等直判
  讲座: lecture
  国际交流: exchange
source_categories:                     # 来源白名单：网站不可能有“作业”
  web_crawl: [notice, exam, competition, research, exchange, lecture, task]
  qq_group: [homework, exam, competition, research, exchange, lecture, task, notice, chat]
group_categories:                      # 频道级进一步收紧（优先于来源）
  web-lecture: [lecture, task, notice]
  web-labor: [task, lecture, notice]
fallback: { cat: notice, urg: 1, action: know }
```

判分：**标题命中 ×200 > 正文命中 ×100**；标题命中存在时不再看正文。
`web_crawl` 通知只按标题分类（正文常是新闻噪音），QQ 消息才回退正文。
命中类别若不在来源/频道白名单内，直接跳过该规则，最终落到白名单内的 `notice`。
配置按 mtime 缓存，改完重启后台生效。

历史信息流重分类：

```bash
python scripts/reclassify_items.py            # 预览（默认只看标题）
python scripts/reclassify_items.py --apply    # 写回 items.cat/cat2
```

## 订阅 schema（用户侧）

```yaml
# 用户可自选订阅哪些群的哪些类别；没有发送者维度。
# 模板（被 git 跟踪）：config/subscriptions.yml.example
# 真实文件（含用户 QQ，不入库）：config/subscriptions.yml（首次运行自动从模板生成）
subscriptions:
  "100001":                         # 用户 QQ（主号加小号为好友）
    groups: ["123456789"]           # bot 可见的群；["*all"] = 全局追某类
    cats: ["homework", "exam"]      # cat 或 cat2 命中即中（OR 语义）
    keywords: { inc: ["大创"], exc: ["推销", "广告"] }   # 可选细筛
    quiet: ["23:00-07:00"]          # 免打扰时段
    instant_min_urg: 2              # urg ≥ 此值且非免打扰 → 即时分发；其余进 Digest
    digest: true
```

> **真实文件不入库**（ADR-027）：`config/subscriptions.yml` 已加入 `.gitignore`，与 `.env` 同一约定（`.env` 不入库、`.env.example` 入库）。首次运行若不存在会自动从 `config/subscriptions.yml.example` 复制一份，无需手动创建。

**新用户默认值**（宁漏勿误，觉得窄了随时开）：全部群 × {homework, exam, task, notice}，静默 23:00–07:00，即时 urg ≥ 2。

**匹配规则**：`群 ∈ groups`（ClassifiedEvent.groups 任一命中）∧（`cat ∈ cats` ∨ `cat2 ∈ cats`）∧（keywords 无 inc 或有命中）∧ 无 exc 命中。

**中文类别别名**（用户记中文，系统存英文 cat）：活动 → {lecture, task}；考试 → {exam}；科研 → {research, competition}；作业 → {homework}；通知 → {notice, task}；讲座 → {lecture}；交流/访学 → {exchange}。

**分发粒度前提**：bot 只能分发它所在的群。要覆盖某课程群，bot 得先被拉进那个群——这是人的事务，不是技术能解决的。

## Web 采集源（web-sources.yml）

```yaml
sources:
  - id: jwc
    kind: jwc                    # 教务处六栏目**直采**（ADR-029；root=jwc.yml，自包含）
    name: 教务处通知（直采）
    root: config/jwc.yml
    interval: 900                # 秒，≥60
  - id: lecture-site
    kind: jwc                    # 人文讲座·学校网站渠道（复用 jwc 解析器；群=web-lecture）
    name: 人文讲座（文化素质教育栏目）
    root: config/lecture-site.yml
    interval: 900
  - id: seu-monitor
    kind: seu_monitor            # SEU-Monitor 归档库 web/教务处/<栏目>/<标题--ID>/
    name: 教务处通知（SEU-Monitor）
    root: seu-projects-test/SEU-Monitor/store     # 相对项目根；绝对路径亦可
    interval: 900                # 秒，≥60
    enabled: true                # 已启用；归档由 seu_alert.tools.seu_archive 生成（Windows 原生）
  - id: seudaily
    kind: seudaily               # SEUdaily 网页库：metadata/*.json + files/<host>/<section>/<notice>/*.md
    name: SEUdaily 网页库
    root: seu-projects-test/SEUdaily/.seudaily/web-files
    interval: 900
```

**kind 取值**：`jwc`（教务处直采）/ `seu_monitor` / `seudaily` / `seu_colleges` / `labor` / `wechat_mp` / `seu_lectures`。
**enabled**：省略或 `true` 参与轮询；`false` 则不启动该源的 poller，后台页面标注「已停用」。

语义（ADR-022/029）：首次扫描全量 backfill，之后增量；`web_seen` 表持久化已见 key；扫描失败只记日志不拖垮管道。web 群是**站点级**合成群（`web-jwc` / `web-cse`，kind=web、scope=school），订阅与普通群一致（`/sub 群 教务处 类别 通知 考试`）。SEUdaily 的 metadata 无发布日期，ts 用抓取时间（文件 mtime）。教务处直采不需要任何外部程序；SEU-Monitor 归档用 Windows 原生生成器：`.venv\Scripts\python -m seu_alert.tools.seu_archive --once`（无需 Go/WSL）。

## 教务处直采（jwc.yml，ADR-029）

```yaml
base_url: https://jwc.seu.edu.cn
columns:
  - id: jwxx                   # 去重键用；群固定 web-jwc
    name: 教务信息             # 推送文案的【栏目】前缀
    url: https://jwc.seu.edu.cn/jwxx/list.htm
```

缺省内置六栏目（zxdt 最新动态 / jwxx 教务信息 / xjgl 学籍管理 / sjjx 实践教学 / gjjl 国际交流 / cbxx 文化素质教育），文件缺失时自动回落到内置清单。

### 人文讲座·网站渠道（lecture-site.yml）

复用同一套 jwc 解析器，只换栏目与群：

```yaml
group_id: web-lecture
group_name: 人文讲座（文化素质教育栏目）
columns:
  - {id: cbxx, name: 文化素质教育, url: https://jwc.seu.edu.cn/cbxx/list.htm}
  - {id: lcsdjt, name: 六朝松大师讲堂, url: https://jwc.seu.edu.cn/lcsdjt/list.htm}
```

## 学院采集（colleges.yml，ADR-024）

```yaml
colleges:
  - key: arch                  # 群 = web-arch；groups.yml 有同名画像
    name: 建筑学院
    list: https://arch.seu.edu.cn/9126/list.htm    # WebPlus 列表页
    prefilter: [通知, 公告, 报名, ...]             # 画像预筛词
```

33 个学院由 `scripts/discover_colleges.py` 从官网院系设置页自动发现生成；每学院每轮最多抓 12 篇文章（增量轮只新增）。未覆盖的学院往该文件加一条即可，无需改代码。

## 劳动教育（labor.yml + .env，ADR-024）

```yaml
filters:
  location_whitelist: []     # 地点子串白名单（如 ["九龙湖"]），空=不限
  category_blacklist: []     # 类别精确黑名单
```

会话（.env，二选一）：`LABOR_USERNAME` + `LABOR_PASSWORD`（CAS 自动登录：探测验证码→RSA 加密→casLogin→票据兑换；需短信/验证码时跳过本轮并告警）或 `LABOR_COOKIES`（JSON / `k=v; k=v`）/ `LABOR_COOKIE_FILE`。课程表解析与 diff 移植自 SEU-Labor-Course-Pusher（Rust）源码；**新课程 → web-labor 群 → 分类树 → 订阅分发**（含临期提醒）。非校内网期间该源连续失败只记日志。

## 公众号监控（wechat-mp.yml，ADR-025）

```yaml
accounts:
  - key: wzjy                    # name 用于搜狗搜索与账号过滤
    name: 东南大学文化素质教育中心
    group_id: web-lecture        # 可选：讲座并入人文讲座频道（缺省 web-mp-<key>）
extract_layer: big               # big=大模型代读 | small=小模型备用；未配置则降级原文入库
```

免登录链路：搜狗文章搜索（type=2）→ `/link?url=` 跳转解析 → mp.weixin.qq.com 公开正文 → 模型代读（题目/时间/**校区+教室**/报名途径/摘要）。**校区着重显示**（`【九龙湖校区】`前缀）；报名途径只提取文字路径，不提取二维码。模型判 `is_lecture=false` 不入库。加账号 = 加一条 accounts。

## 人文讲座监控（seu-lectures.yml，ADR-025）

```yaml
keyword: ""        # 可选：只监控标题含关键词的讲座
```

移植 seu-lecture-cli **仅监控**（queryActivityList.do 分页 + CAS，**不预约不抢票**）。会话：`SEU_LECTURE_USERNAME/PASSWORD` 或 `SEU_LECTURE_COOKIES`（与劳动教育共用 cas.py）。讲座 → `web-lecture` 群，文案含预约开放时间与余量。

## bot 命令表

| 命令 | 作用 |
|---|---|
| `/sub 群 <群名/id> 类别 <中文类别...>` | 订阅（如 `/sub 群 年级大群 类别 活动 通知`） |
| `/unsub ...` / `/sub list` | 退订 / 查看当前订阅 |
| `/mute <HH:mm-HH:mm>` / `/digest on|off` | 免打扰 / Digest 开关 |
| 回复"不感兴趣" | 负反馈，进标注集（调关键词与阈值的依据） |
| `/group bind <群> kind=... course=...` | （管理员）绑定群画像 |
| `/role @<人> <角色>` | （管理员）配置发送者角色 |
| `/filter status` | （管理员）当前过滤模式 + 近 24h 计数（滤除 N / 其中关键词命中 M） |
| `/filter dry-run on|off` | （管理员）只记录不滤除 |
| `/filter audit [24h]` | （管理员）被滤消息中含关键词命中的清单（"我可能错过了什么"） |
| `/filter mode off` | （管理员）一键全量恢复 |

命令与 YAML 是同一份数据的双通道，全部读写经由单一配置管理器（单写者 / 原子写 / 热更新，ADR-018）。

## 环境约定（.env，见 .env.example）

```bash
# 分发与分类器开关
DELIVER_MODE=file          # file=测试期写 txt 到 outbox/<用户QQ>/（ADR-021）；qq=真实推送（后置）
CLASSIFIER=stub            # stub=假分类器（P1）；tree=JEV 分类树（P2）

# 目录（相对项目根；全部在项目内，不写系统目录）
DATA_DIR=./data            # SQLite（WAL）+ 日志 + outbox
LOG_DIR=./data/logs
CONFIG_DIR=./config
OUTBOX_DIR=./data/outbox   # 测试期分发目标：一个文件夹代表一个用户

# OneBot（NapCat 反向 WS：NapCat 来连我们；Win11 与香橙派之间只改这里）
ONEBOT_REVERSE_HOST=127.0.0.1
ONEBOT_REVERSE_PORT=3001
ONEBOT_TOKEN=change-me

# 模型
JEV_BASE_URL=https://tokenrhythm.studio
JEV_API_KEY=sk_...
CHAT_BASE_URL=https://tokenrhythm.studio
CHAT_API_KEY=sk_...
CHAT_MODEL=neohorse-1-9b

ADMIN_QQ=100000            # 管理员（告警、复核队列接收人）
```

**运行方式**（venv 与 pip 缓存均在项目内）：

```bash
py -V:3.13 -m venv .venv                      # 建虚拟环境（仅一次）
set PIP_CACHE_DIR=<项目根>\.pipcache          # pip 缓存也进项目，不写系统目录
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .      # 可编辑安装
set PYTHONIOENCODING=utf-8                    # Windows 控制台中文输出
.venv\Scripts\python -m seu_alert.store.db     # 初始化 SQLite schema
.venv\Scripts\python -m seu_alert.smoke        # P0 冒烟（--seconds/--forever）
.venv\Scripts\python -m pytest                # 测试
```

## 代码骨架（src/ 布局，P0 已落地部分标 ✅）

```
src/seu_alert/
├── __init__.py
├── config.py          # ✅ 配置加载 + dataclass 校验（P3 扩为单一配置管理器）
├── contracts.py       # ✅ RawEvent / ClassifiedEvent 数据契约
├── smoke.py           # ✅ P0 冒烟：反向 WS 服务 + 事件打印 + 原始日志
├── adapters/
│   ├── __init__.py
│   ├── base.py        # ✅ Adapter 协议（后续爬虫/上报都实现它）
│   └── onebot.py      # ✅ OneBot 11 反向 WS 服务端 + 事件解析 + action 调用
├── pipeline/          # P1/P2 填充
│   ├── prefilter.py       # 发送者过滤 → 去重 → 关键词预筛（顺序不可反）
│   ├── classifier_stub.py # 假分类器（P1）
│   ├── jev.py             # JEV 客户端：有界并发队列、退避重试、hash 缓存
│   ├── chat_client.py     # L4 小模型客户端（禁思考参数）
│   ├── extract.py         # 课程别名词典 + 截止时间正则；L4 归一化
│   ├── tree.py            # 按 tree.yml 驱动分类树
│   └── matcher.py         # 订阅匹配
├── deliver/
│   ├── base.py        # Deliverer 协议
│   ├── file.py        # 测试期：outbox/<用户QQ>/*.txt
│   └── qq.py          # 真实私聊推送（后置）
├── store/
│   ├── schema.sql     # ✅ 10 张表
│   └── db.py          # ✅ SQLite 连接 / schema 初始化
├── botcmd.py          # P1/P3：私聊指令与管理员命令
└── main.py            # P1：装配 + 启动

tests/                 # ✅ test_config.py / test_onebot.py（22 项）
config/                # ✅ groups.yml / tree.yml / subscriptions.yml（占位待校准）
napcat/                # NapCat 解包目录（下载物，gitignore）
```
