# 决策记录（ADR）

> 版本 v0.1 · 2026-10-25 · 改决策时**新增** ADR，不静默修改旧条目。每条含：背景 / 决定 / 理由 / 被否方案 / 后果。

---

## ADR-001 框架选型：NapCat + OneBot 11

- **背景**：需要实时获取 QQ 群消息并私聊推送。用户原倾向 qq-chat-exporter。
- **决定**：NapCat 为首选，业务代码只对接 **OneBot 11 协议**，不对接具体框架。
- **理由**：qq-chat-exporter 定位是导出/归档（后端 Lagrange.Core，批量拉历史），没有事件流，做不了实时分类。OneBot 11 反向 WebSocket 提供实时消息事件。NapCat 跨平台、生态最大，且**支持 Linux/ARM64**（后续要迁香橙派）。
- **被否方案**：LLBot/LLOneBot（LiteLoaderQQNT 插件，寄生官方客户端，绑 Windows，迁不到 Debian）；go-cqhttp（2023 起归档停更）；Mirai（半停滞、风控针对）；Lagrange.OneBot（可用，作为备选）。
- **后果**：后端可随时更换，选错沉没成本为零。账号侧用小号（见 ADR-011）。

## ADR-002 分类与匹配分离

- **背景**：需求描述为"按多个用户的需求逐个分类"。
- **决定**：每条消息**只分类一次**（树输出 ClassifiedEvent），再匹配 N 个用户（本地查询）。
- **理由**：按用户分类会使模型调用量 = 消息数 × 用户数，免费额度不可持续；分离后模型成本只与消息量有关。
- **被否方案**：按用户逐个分类。
- **后果**：系统可从小范围试点扩展到全院；匹配层是纯本地逻辑。

## ADR-003 分类器主模型：JEV 结构化决策，而非 Chat 小模型

- **背景**：用户曾提出用 Chat Completion 小模型（neohorse-1-9b）做全流程语义分析；后自行纠正。
- **决定**：**分类/判断全部由 JEV（NeoHorse-Jev-4B，/v1/decision）完成**；Chat 小模型只做 L4 开放集信息提取（如 DDL 归一化）。
- **理由**：JEV 一次调用可并行 1~16 题且按打包输入 token 计费（题数几乎不增成本）；结构化输出（noul/choice/score）无 JSON 可靠性问题；小模型生成式调用贵且 1.9B 吐非法 JSON 需整套降级链，只留给真正需要生成的环节。
- **被否方案**：全流程 Chat 小模型分类（JSON 不可靠、贵、需 few-shot 兜底）。
- **后果**：三层工具分工原则成立（见 ADR-004）；分类器契约与模型实现解耦，可替换。

## ADR-004 三工具分工原则

- **决定**：封闭集的判断 → JEV；开放集的抽取 → Chat 小模型；字面匹配 → 规则；元数据（群/发送者） → 画像。模型调用量沿"免费 → 便宜 → 贵"单向递增。
- **理由**：每类工具做自己擅长且便宜的那段；任何"越界使用"（用小模型做判断、用 JEV 做抽取）都是成本和可靠性的双重浪费。
- **后果**：分类树的分层边界即按此划定；L4 只做归一化，不判类别。

## ADR-005 渠道画像：树的前几层用群+发送者免费先验

- **背景**：用户指出马原群出的就是马原信息、年级大群出竞赛/活动/任务、班干部群出通知任务/团课、辅导员出任务通知、教务处出学习绩点考试、课程老师出作业——群和发送者本身就携带强先验。
- **决定**：新增 L0 渠道画像（groups.yml，人工配置）：课程绑定、范围、角色表、角色→类别先验、画像预筛词。画像写入 state、免课程识别、定制预筛、支撑按群订阅。
- **理由**：把树的前几层从"推理"变成"查表"，课程绑定/范围判定/常见类别全部免费化；预筛词按群定制更紧。
- **被否方案**：全部类别判断交给模型（浪费且更不准）。
- **后果**：用户订阅以"群 × 类别"为轴（课程群即渠道）；需要新群 onboarding 流程（自动猜 + 人确认）；画像错误只影响路由不污染分类树，但需审计日志。

## ADR-006 发送者降级为先验，不是过滤门

- **背景**：初版预筛设计含"发送者白名单优先"层。用户指出：不能只读取给定发送者的消息——重要信息可能来自任何人（转发的同学、潜水的课代表、匿名提问后老师回答）。
- **决定**：发送者从 L1 过滤门撤出，只保留三处非门用途：① state 上下文；② 角色先验（影响 L3 分支与默认 urg）；③ 运营级过滤（bot 自身回声、入退群系统消息）。
- **理由**：发送者门 = 系统性漏报，漏的不是噪音是漏报。
- **后果**：去留只由内容判断（预筛关键词 → JEV is_info/cat）决定。后经 ADR-007 补充为"可选有损过滤器"形态。

## ADR-007 发送者白/黑名单：可选有损过滤器

- **背景**：用户要求可以有发送者白/黑名单功能，用于初步过滤避免达到模型并发限制，但**不能强制使用**。
- **决定**：按四原则实现——**默认关闭 · 可 dry-run · 可审计 · 一键恢复**。黑名单优先于白名单；角色表达优先于 user_id。
- **理由**：它是限流保命的静态闸，不是提准手段；白名单漏报代价高，须 dry-run 报告（24h 该滤 N 条、其中关键词命中 M 条）让人先看代价再决定。
- **后果**：过滤只发生在分类之前，不改变分类与分发语义；M 值成为该群"已知漏报基线"（验收项）。

## ADR-008 预筛链顺序：发送者过滤 → 去重 → 关键词

- **背景**：若先去重后过滤，A 群（黑名单发送者）的拷贝先登记内容 hash 后被滤掉，同一条通知在 B 群的拷贝会被去重判为"已见过"直接跳过。
- **决定**：发送者过滤必须排在去重**之前**；去重只注册通过过滤的消息。
- **理由**：反序是一个静默漏报 bug——过滤造成的丢弃污染去重状态。
- **后果**：顺序写入 architecture.md 关键不变量，测试需覆盖。

## ADR-009 去重 fan-in：一条 ClassifiedEvent 记录所有来源群

- **决定**：同内容通知在多个群出现只分类一次，ClassifiedEvent.groups 记录全部来源群；匹配时任一来源群命中用户订阅即推送。
- **理由**：省分类成本，不省分发覆盖面——各群订阅者都应收到。
- **后果**：dedup 与分发解耦；DDL 等提取字段全局唯一。

## ADR-010 部署路径：Win11 开发 → 香橙派 4 Pro 常驻

- **背景**：用户确认先在 Windows 11 打通工作流，之后迁到局域网内香橙派 4 Pro（RK358S/ARM64/6GB/Debian）。
- **决定**：业务代码（Python + SQLite + OneBot 客户端）全平台通用；迁移 = 改 .env 的 WS 地址与 token，零代码改动；所有路径/端口/token 配置化，零硬编码。
- **理由**：框架选型因此钉死 NapCat（LLBot 绑 Windows，迁不过去）。
- **后果**：SQLite WAL 单文件；NapCat arm64 部署方式（Docker 多架构镜像或 Python 直跑）待验证；无头环境扫码登录入口提前试通；掉线看门狗为刚需。

## ADR-011 试点策略：小号 + 现有群 + 金标准集 + 主号当测试用户

- **背景**：小号内好友与群聊并非课程群与同学；类别分布严重失衡（灌水负类极多、正类极少）。
- **决定**：用注册过一段时间的**小号**（不用主号、不用刚注册的号）；先用小号全部群做功能测试；造 30~50 条真实课程通知作**金标准集**（贴测试群或存文件）；**主号加小号为好友当第一个测试用户**。
- **理由**：试点群证明不了正类召回，金标准集同时是验收基准和回归测试；自己就能端到端验证推送，不用拉同学。
- **后果**：SRTP 等类别若试点群没有，从复制真实通知补、验收标注"样本外"；验收标准含按群分组统计。

## ADR-012 9 类分类体系 + cat2 次类别

- **背景**：初版 7 类；讨论中用户补充了事务任务（收集填写/团课/大会/集合）和 SRTP 科研项目流程两类真实存在的内容。
- **决定**：9 类：homework / exam / competition / research / exchange / lecture / task / notice / chat。SRTP、大创、国省创合并为 `research`（同一项目制家族），阶段用 L3 `stage` 封闭集表达。增设 `cat2` 次类别（同 cat = 无）解决跨界消息。
- **理由**：类别是订阅和分支的路由轴，必须 MECE 且边界可观察；拆成"SRTP 六个阶段类"会爆炸，收敛为一类 + stage 字段。
- **被否方案**：7 类（漏 task/research）；按阶段拆类。
- **后果**：choice 从 7 扩到 9 项；accuracy 不达标时的后备是"按画像收窄选项集 + other 逃逸 + 逃逸后全量重判"（扩展点已留，未启用）。

## ADR-013 推送分层：紧急即时 + 防抖，其余 Digest

- **背景**：用户担心"只能汇总后定时统一发布"。
- **决定**：urg ≥ instant_min_urg（默认 2）且非免打扰 → 即时推（5~10 秒防抖合并同波爆发）；其余进早晚 Digest。
- **理由**：定时汇总不是缺陷是防扰民功能；关键是分层不是二选一。
- **后果**：免打扰时段默认 23:00–07:00；Digest 时间点待定（见 open-questions.md）。

## ADR-014 分发通道：QQ 私聊为主，微信降级

- **决定**：QQ 私聊做主通道（免费、实时、同一 bot）；微信侧用 WxPusher/Server酱 类推送服务转发，或先只做网页版 Digest。
- **理由**：个人微信没有可靠的非官方框架。
- **被否方案**：个人微信非官方方案（不存在可靠实现）。

## ADR-015 学习通/雨课堂：两步走

- **决定**：第一步"用户转发/截图上报"——用户把学习通、雨课堂消息转发给 bot，零 cookie 零封号风险，走同一条管线；第二步再评估 cookie 版直连。
- **理由**：cookie 版易失效、有 ToS 风险；转发上报先解决有无问题。
- **后果**：无 OCR（用户明确不要）；截图仅存档，截止时间靠转发文本。

## ADR-016 限流五层防线

- **决定**：去重（免费）→ 关键词预筛（免费）→ 发送者过滤（可选有损）→ 有界并发队列 + 指数退避 → 压力降级（队列积压/429 频繁时临时切"仅关键词强命中"或 digest-only，按群公平降级）。
- **理由**：429 是容量限流；静态闸（人配置）与动态闸（系统自保）互补；**宁可晚到，不可静默丢**。
- **后果**：超时请求按内容 hash 幂等，不无条件重试（API 文档要求）；traceId 留档。

## ADR-017 neohorse-1-9b 禁思考参数

- **背景**：用户此前已定位：该模型只接受"不思考"，任何推理档位字段都导致 400（模型/网关自身限制，与客户端/插件无关）。
- **决定**：L4 客户端封装前先用最小请求（空 system + 一条 user message、无 reasoning 字段）验证 200；请求禁止携带任何思考参数。
- **后果**：写进 architecture.md 模型接入硬约束；这是封装第一个连通性测试。

## ADR-018 配置双通道：bot 命令 + YAML，单一配置管理器

- **背景**：用户确认（2026-10-25）画像/过滤器配置要双通道。
- **决定**：所有 YAML 读写经由**单一配置管理器**：单写者原则（命令通道不直接写文件）、原子写（tmp + rename）、写前重读、mtime 监听热更新。人和命令改的是同一份数据、同一把锁。
- **理由**：双通道最大风险是双写冲突（命令写一半、人编辑一半）；热更新失败时旧配置继续生效并告警，不做"失败就重启"。
- **后果**：botcmd 只产"意图"，配置管理器执行写；`/config rollback` 保留上一版本。

## ADR-019 搭建顺序：先完整规划后动手，垂直切片推进

- **背景**：用户确认（2026-10-25）先写完整搭建规划与各步方案，再开始搭骨架。
- **决定**：按 docs/build-plan.md 的 P0→P5 推进：管道先于模型（假分类器贯通）、模型先于校准（harness 就绪）、校准先于试点、试点先于迁移。每阶段出口 = 验收条目变绿 + 可回滚开关。
- **理由**：管道正确性不依赖模型质量，两者可分别调试；每个阶段独立可验，问题不跨阶段传染。
- **后果**：build-plan.md 是施工唯一依据；阶段出口未达不进入下一阶段。

## ADR-020 技术栈：Python 3.11+ / 自写薄 OneBot 客户端 / SQLite

- **背景**：需要定语言与依赖边界。
- **决定**：Python 3.11+ / asyncio；httpx + websockets；PyYAML + dataclass 校验；SQLite（aiosqlite，WAL）；APScheduler；pytest。**不用 nonebot2 等 bot 框架**，OneBot 客户端自写薄层（反向 WS + action 封装）。
- **理由**：中文日期解析生态（dateparser/chrono）；管道是我们自己的状态机，框架的控制反转不值得；依赖最少 = 迁移到香橙派最省。
- **被否方案**：nonebot2（插件体系与我们的管道重叠、升级包袱）；Node/TS（日期解析与 NapCat 生态弱一点）。
- **后果**：venv 与 pip 缓存全部指向 项目目录（用户硬性约束）。

## ADR-021 测试期分发：文件模式（outbox/<用户QQ>/*.txt），不做真实推送

- **背景**：用户要求（2026-10-25）测试与完善筛选机制阶段**不做真实 QQ 推送**，推送改为写 txt 并分发到项目目录下按用户分的文件夹（一个文件夹代表一个用户）。
- **决定**：deliver 层可插拔（`DELIVER_MODE=file|qq`）：测试期默认 `file`——`data/outbox/<用户QQ>/` 下每条推送一个 txt（命名 `<时间戳>_<cat>_<事件短id>.txt`，Digest 写 `digest-<date>.txt`），文案与 QQ 推送同模板；真实 QQ 推送（deliver/qq.py）后置，试点审批后再开。
- **理由**：零风控零打扰；产物可直接检查；模板先行保证日后切 QQ 只是换出口。
- **后果**：acceptance A3-A5 口径改为文件断言；"不感兴趣"负反馈在文件模式不可用（改由管理员直接标注 labels）；outbox 与 data/ 全部 gitignore。

## ADR-022 SEU 项目接入：消费输出库，不重写爬虫

- **背景**：用户已有两个验证通过的东南大学网站项目（seu-projects-test/ 下）：**SEU-Monitor**（Go，教务处六栏目监控，CAS 认证 + zju-connect VPN + 飞书推送，归档到 `web/教务处/<栏目>/<标题--ID>/{meta.json,text.md,attachments/}`）和 **SEUdaily**（TS/Python 校园助手，网页库 `web-files/metadata/<sha>.json` + `files/<host>/<section>/<notice>/<sha>.md`，监控 jwc/cse/news 三站）。本项目需要学校网站通知源（原 P6 规划）。
- **决定**：**消费两个项目的输出库**，在本项目内实现 web 采集适配器（`adapters/web/`）：`seu_monitor` 扫归档目录、`seudaily` 扫网页库，统一转 RawEvent（source=web_crawl，合成群 = 站点级 `web-jwc` / `web-cse`），进同一条分类树与订阅匹配。**不重写、不 fork 爬虫逻辑**；两个项目的更新互不影响。
- **理由**：爬虫（CAS 登录、反爬、VPN、HTML 解析）是他们已验证的核心资产，重写=双倍维护；输出库是稳定接口；群=站点级足够订阅（栏目级细分留作后续）；SEUdaily 与 SEU-Monitor 在教务处重叠的部分由内容去重自动合并（fan-in）。
- **被否方案**：fork/内嵌爬虫代码（维护分叉）；webhook 接收（SEU-Monitor 只推飞书，格式不适合当数据源）。
- **后果**：web-sources.yml 配置 root 与间隔；首次扫描全量 backfill，之后增量（web_seen 表）；SEUdaily metadata 无发布日期 → ts 用文件 mtime（抓取时间）；未配画像的站点通知会被通用词预筛挡掉（漏检可控，配画像即恢复）；SEU-Monitor 在 Linux/WSL 跑监控，Windows 侧读其归档（root 可指向 /mnt/<盘> 或 \\wsl.localhost）。

## ADR-023 引擎定位与投稿提取栈

- **背景**：本引擎定位为「校园信息聚合与强提醒」类产品的内容与决策引擎，前端触点由独立仓库负责：个人公众号投稿 + OCR+LLM 提取 + 双按钮核验 + PushPlus 微信强推送（截止前 24h/3h）+ 临期提醒。
- **决定**（2026-10-25 拍板）：
  1. **定位**：qq-relay 作为**内容与决策引擎**（多源采集 → JEV 分类树 → 提取 → 订阅匹配 → 提醒调度），公众号/H5/PushPlus 为前端触点；bot 保留为**内部增强通道**（我方主动接入部分群，不专门维护适配，NapCat 登录暂缓）；
  2. **OCR 纳入**：投稿提取层 = **OCR/视觉模型（Chat Completion 协议）→ 大模型（可选层）→ 小模型（备用层）** 的降级链；JEV 分类树**保留用于分类**（不替代）；
  3. **模型接入统一走 Chat Completion 协议**（大模型/小模型/免费视觉模型/讯飞类 OCR）；专用 OCR 协议接口（如讯飞通用 OCR）作为 provider 之一可插拔；
  4. QQ 私聊仅内部测试通道；先本地实现全部引擎侧能力。
- **理由**：前端触点（公众号 + PushPlus）已实测可用，产品与增长层是独立方向；引擎层复用已落地的采集/分类/订阅资产，并补齐其中最重的「临期强提醒」与「投稿提取」缺口；网站采集可直接自动化原本需要人工维护的全校讲座/教务事件。
- **被否方案**：另起独立产品线（重复投入）；bot 作为产品主通道（封号与隐私风险，明确回避）。
- **后果**：引擎侧新增三能力（PushPlus 分发、deadline 提醒调度、用户投稿通道）+ 两数据层复用（labels/votes 核验、课程别名词典）；H5 看板由前端侧负责，引擎提供数据导出。工作项列入 build-plan P7。

## ADR-024 全院系覆盖 + 劳动教育推送器源码接入

- **背景**：① SEUdaily 只监控计软智学院（cse）一个学院站点，产品需求是覆盖**东南大学全部学院**并按学院订阅；② 用户已有项目 SEU-Labor-Course-Pusher（Rust+WebView2，监控劳动教育平台新课 + PushPlus 推送，仓库 zz6zz666/SEU-Labor-Course-Pusher，已克隆至 seu-projects-test/），要求**只用其源码、不接打包 exe**；当前非校内网，不测试连通性，保证可用即可。
- **决定**：
  1. **全院系**：从东南大学官网院系设置页自动发现 **33 个学院**通知列表页（WebPlus CMS `/<id>/list.htm`，scripts/discover_colleges.py），落 `config/colleges.yml`；新增 `seu_colleges` 异步扫描器（列表解析 + 文章页 arti_title/arti_update/wp_articlecontent 提取 + 页脚截断）；每学院一个 `web-<key>` 画像群，订阅粒度 = 学院 × 类别。chem/math/futuretech/bme 四院首页未发现列表页，留配置位后续补。
  2. **劳动教育**：移植 Rust 源码三块到 `adapters/web/labor.py`——`site.rs` 课程表解析（table#c_app_page_index_XuanKe_table、列偏移探测、td-data、已满/已截止）、`watcher.rs` 的 diff 语义（unique_id=课程名|时间，由 web_seen 承担）、`login.rs` 的 CAS 无浏览器登录（探测验证码 → RSA 公钥加密密码 → casLogin → 票据兑换）；会话优先 cookie（env/文件），CAS 自动登录兜底，需短信/验证码时 NeedManual 跳过本轮并告警。**推送复用本项目 deliver 层**（PushPlus/file/qq），不用其 exe。
  3. WebPoller 的 scanner 支持异步（文件扫描器同步、学院/劳动教育异步）。
- **理由**：学院站与教务处同构（WebPlus），直采可控且与另两源互补；劳动教育的登录/解析是验证过的资产，移植优于重写；新课程通知天然接入分类与订阅（web-labor 群）。
- **被否方案**：改 SEUdaily 的 notice_categories.json 让它爬全院系（其抓取由助手使用时触发、非定时，不满足"监控"）；接 exe（违反用户要求且无法融入管道）。
- **后果**：web 采集源增至 4 个；groups.yml +34 画像（33 学院 + web-labor）；新增依赖 cryptography（RSA）；测试 95 项（含真实页面夹具与 CAS 全流程 mock）；劳动教育会话走 .env（LABOR_USERNAME/PASSWORD 或 LABOR_COOKIES）。

## ADR-025 公众号免登录监控（模型代读）+ 人文讲座监控接入

- **背景**：① 用户要求接入**免登录监控微信公众号**能力：多账号、由大/小模型代读汇总，默认监控「东南大学文化素质教育中心」，提取**活动题目/活动时间/活动地点（校区着重+教室）/报名途径**（文字路径如"数智东南-工作台-学业生活-素质讲座"即可，不提取二维码）；② 附加接入 seu-lecture-cli（wynter-yaxley，讲座预约工具），**只用其监控能力，不用预约/抢票**。
- **决定**：
  1. **公众号（`adapters/web/wechat_mp.py`）**：免登录三段——搜狗微信**文章搜索**（type=2，按公众号名；账号搜索 type=1 实测返回空，弃用）→ `/link?url=` 跳转解析（`url += '…'` 片段与 `var url='a'+'b'` 两种拼法）→ mp.weixin.qq.com 公开文章页（rich_media_title/js_content）；**大/小模型代读**（Chat Completion，JSON 契约 is_lecture/title/time/campus/room/signup_path/summary）；**校区着重显示**（`【九龙湖校区】`前缀+地点行）；模型判非讲座不入库；未配模型降级原文入库。多账号 `config/wechat-mp.yml`，群 = `web-mp-<key>`。
  2. **人文讲座（`adapters/web/seu_lectures.py`）**：移植 seu-lecture-cli 的 `parse_lectures` + `queryActivityList.do` 分页 + CAS 登录（收敛到共用 `cas.py`）；**不移植** reserve/captcha/clock；讲座 → 群 `web-lecture`，文案含预约开放时间与余量，注明"仅监控不代预约"。
  3. **共用 CAS**（`adapters/web/cas.py`）：劳动教育与讲座监控共用同一套 auth.seu.edu.cn 无浏览器登录（探测验证码→RSA 加密→casLogin→票据兑换）。
- **理由**：搜狗文章搜索是当前少数可用的免登录发现通道（mp 文章页本身公开）；模型代读把非结构化文章变成结构化字段；讲座监控复用已验证项目的解析，规避自研风险。
- **被否方案**：搜狗账号搜索 type=1（实测空结果）；第三方 RSS 中转（不自托管、不稳定）；使用 seu-lecture-cli 的预约/抢票（用户明确排除）。
- **后果**：web 采集源增至 6 个；测试 109 项（真实搜狗页面夹具+跳转解析+模型代读 mock+讲座解析移植）；**已知限制**：搜狗风控（验证码→跳过本轮，间隔 ≥1800s）、搜狗索引可能滞后、提取质量取决于配置的模型层。

## ADR-026 便携版打包 + 后台管理界面

- **背景**：需要把引擎做成**便携版软件**分发给校内非技术用户（无需安装 Python 即可运行），以便验证**人文讲座与劳动教育的监控与订阅**；要求**先做后台管理人员界面**、PushPlus 分发、**先打基础后续再配置**。
- **决定**：
  1. **后台管理**（`src/qq_relay/admin.py`，Flask + 自包含单页，无构建无外部静态文件）：监控源状态（上次扫描/新增/错误/立即扫描）、最近信息流、订阅管理（群×类别 增删查，原子写 YAML）、PushPlus 测试推送（token 页内可填）、配置概览（密钥脱敏）。items 查询走**独立 SQLite 连接**，不与监控 loop 争抢（学院源一轮扫描数分钟，走 loop 会堵死页面）。
  2. **便携打包**：PyInstaller **one-dir**（符合用户 one-dir 偏好）；`runtime_root()` 冻结模式下把数据/配置解析到 **exe 同级目录**（不写 %APPDATA%、不写系统目录）；构建脚本 `scripts/build_portable.ps1` 产出 `dist/qq-relay-portable/`（exe + config/ + .env.example + 使用说明.md），整 folder 发给使用者，无需 Python。
  3. **使用者文档** `docs/portable-readme.md`：双击 exe → 浏览器开后台 → 填 PushPlus token 与讲座/劳动教育 CAS 账号 → 观察监控与推送；日志在 logs/。
  4. **基础版边界**：可改配置仍在 config/*.yml 与 .env（页内只读展示）；订阅保存后重启生效（P3 配置管理器落地前）；QQ 通道（main.py）与便携版（admin.py）双入口并存。
- **理由**：校内使用者是实际使用者，后台界面让他们能自证链路（扫描→信息流→推送）并回传日志；PyInstaller one-dir 是 Windows 零依赖分发的标准解；焦点源（讲座/劳动教育）需校内网，恰好由他们验证。
- **被否方案**：安装包（inno setup，打包脚本已预留但本轮不做）；Web 部署（使用者无服务器）；Electron/Tauri 桌面壳（过重）。
- **后果**：测试 124 项（含 admin API 桩测试 8 项）；新增依赖 flask/pyinstaller（构建期）；`spawn_web_pollers` 重构为 Runtime 持有 pollers（main.py 与 admin.py 共用）。

## ADR-027 订阅文件移出版本库（与 .env 同一约定）

- **背景**：安全排查发现 `config/subscriptions.yml` 被 git 跟踪；该文件记录用户 QQ 与订阅偏好（个人信息），正式使用后一旦 `git add` 即入库，构成隐私泄漏面。
- **决定**：沿用 `.env` 的既定约定——**真实文件不入库，模板入库**：
  1. 新增被 git 跟踪的模板 `config/subscriptions.yml.example`（占位 QQ/群号，含注释说明）；
  2. `config/subscriptions.yml` 加入 `.gitignore`，并 `git rm --cached` 解除跟踪（本地文件保留）；
  3. `Settings.ensure_dirs()` 增加引导：真实文件不存在时自动从 `.example` 复制生成；模板也不在（极端情况）则退化为空订阅，保证启动不中断；
  4. `scripts/build_portable.ps1` 同步把模板拷进便携版 `config/`（首次启动自动生成真实文件）。
- **理由**：与 `.env` / `.env.example` 完全一致的心智模型，最小改动、零迁移成本；引导逻辑保证全新克隆与便携版开箱即用。
- **被否方案**：给 `subscriptions.yml` 加占位提交并只靠 `.gitignore`（文件已跟踪时 ignore 无效，必须 `git rm --cached`）；把用户 QQ 改成哈希/脱敏存储（订阅匹配依赖可读 QQ 查 users 表与 outbox 目录，改动面过大）。
- **后果**：真实订阅从版本库消失（消除一处 PII 泄漏面）；测试 127 项（新增 `TestEnsureSubscriptionsBootstrap` 3 项：从模板生成 / 不覆盖已存在 / 无模板退化空订阅）；文档（config.md / runbook.md / portable-readme.md）同步说明。

## ADR-028 GitHub Actions 自动构建分发 + Linux 服务器版

- **背景**：① 用户要求增加 GitHub 工作流，自动构建并分发便携版；② Windows 平台专用构建源码需归置到项目内 `win/` 目录；③ 再补一份 Linux 服务器版，同样由工作流构建分发。
- **决定**：
  1. **源码归置**：Windows 便携版构建源码移入 `win/`——`win/build_portable.ps1`（原 `scripts/build_portable.ps1`）、`win/portable_entry.py`（原根目录）、新增 `win/README.md`；**产物仍输出到项目根 `dist/`**（`dist/` 已 gitignore），符合用户"产物不散落"的偏好。
  2. **Linux 服务器版**（`linux/`）：新增无头入口 `server_entry.py`（`admin.main(host=0.0.0.0, open_browser=False)`，`ADMIN_HOST`/`ADMIN_PORT` 可覆盖）、构建脚本 `build_server.sh`（PyInstaller one-dir，不加 `--windowed`）、systemd unit `qq-relay-server.service`、`linux/README.md`；产物 `dist/qq-relay-server/` + `dist/qq-relay-server.tar.gz`。
  3. **工作流** `.github/workflows/build.yml`：`test`（ubuntu，pytest）→ `win`（windows-latest）+ `linux`（ubuntu-latest）并行构建 → 上传 artifact；`release` job（`needs: [win, linux]`）在 **tag `v*`** 或手动勾选时用 `softprops/action-gh-release` 上传两份产物。`permissions: contents: write`。
  4. **脚本 CI 兼容**：构建脚本支持参数/环境变量（`-Python`/`$PYTHON`/`$OUT`），本地优先用项目内 `.venv`，CI 回退到 runner 的 `python`/`python3`；统一设 `PYTHONPATH=src` + `--paths src`，避免依赖 `pip install -e .`。
  5. **产物校验**：win 校验 `qq-relay.exe` 与 zip 存在，linux 校验可执行文件与 tar.gz 存在，缺失即 fail。
- **理由**：GitHub Actions 是零自建服务器的标准分发通道；`win/`/`linux/` 按平台分目录使仓库结构清晰；无头服务器版复用同一 admin 后端（Flask），只改绑定地址与浏览器行为，改动最小；先跑 pytest 再构建，避免把测试失败的产物发出去。
- **被否方案**：用 GitHub Pages / 自建 NAS 分发（无 Release 语义）；Linux 版用 Docker 镜像（用户明确要二进制 + systemd，且镜像构建在 runner 上更重）；把构建产物也提交进仓库（体积膨胀且不可追溯）。
- **后果**：新增 `win/`（3 文件）、`linux/`（4 文件）、`.github/workflows/build.yml`；`scripts/build_portable.ps1` 与根 `portable_entry.py` 迁移；runbook 新增第 12/13 节；测试仍 127 项全绿（本 ADR 未改业务代码）；**注意**：仓库尚无 git remote，工作流在首次推送到 GitHub 后生效。

## ADR-029 教务处直采（自包含采集）+ 许可边界核查

- **背景**：用户希望把参考项目的源码整合成统一架构，不再只是「读取其输出库」。核查发现 SEU-Monitor（Go，教务处监控）**无 LICENSE 文件**（本地与上游 GitHub 均无，21 个 Go 文件也无版权头），按著作权法默认保留所有权利，不可复制其源码。曾误判「其依赖是 AGPL，故其本身是 AGPL」——核查后不成立：`internal/monitor/licenses/AGPL-3.0.txt` 是 SEU-Monitor 下载 **zju-connect**（可选外部 VPN 核心）时随附写入的许可证副本（`vpn.go` 的 `coreNotices()`）；其 `go.mod` 依赖只有 BSD-3-Clause 的 `golang.org/x/*`；AGPL 的传染方向是「污染下游」，不是「向上赋予授权」。
- **决定**：
  1. **教务处六栏目改为自研直采**（`adapters/web/jwc.py`）：按 WebPlus CMS **公开 HTML 结构**独立实现列表解析（新版 `news-list-item` / 旧版 `td.main` 两种模板）、正文容器提取（`wp_articlecontent` / `Article_Content` + 页脚截断）、附件链接识别（pdf/doc/xls/ppt/zip…）。**未复制 SEU-Monitor 的 Go 源码**。
  2. **配置** `config/jwc.yml`：六栏目可增删（zxdt/jwxx/xjgl/sjjx/gjjl/cbxx）；缺省内置同款六栏目，文件缺失也能跑。
  3. **新 kind `jwc`** 加入 `WEB_KINDS` 与 `SCANNERS`；`web-sources.yml` 新增 `jwc` 源替换旧的 `seu-monitor` 源。
  4. **旧通道保留但默认停用**：新增 `WebSourceCfg.enabled`（`enabled: false` 不参与轮询），`seu_monitor` 源标为 false。若仍想在 WSL 跑 SEU-Monitor，改回 true 即可继续消费其归档。
  5. **NOTICE 如实记录**：SEU-Monitor 条目写明「许可未声明 / 未获作者授权 / 本次未复制其源码」，并澄清那个 AGPL 文件属于 zju-connect。
- **理由**：自研直采让 qq-relay **自包含**——不再需要先在 WSL 里跑一个 Go 程序生成 `store/` 才能工作，消除最脆弱的外部依赖；同时绕开无许可项目的复制风险。学院站（ADR-024）已是同构直采，教务处沿用同一套解析思路，架构统一。
- **被否方案**：① 直接移植 SEU-Monitor 的 Go 源码（无许可，侵权）；② 继续只读其输出库（用户明确要求整合架构而非只读数据）；③ 等作者授权后再做（用户知晓风险后选择先推进可合法实现的部分）。
- **后果**：新增 `adapters/web/jwc.py`（约 290 行）、`config/jwc.yml`、`tests/test_jwc.py`（15 项）、`tests/fixtures/jwc_list.html` + `jwc_article.html`；`WEB_KINDS` 加 `jwc`；`WebSourceCfg` 加 `enabled`；`web-sources.yml` 停用 `seu-monitor`、新增 `jwc`；测试 127 → **145 项全绿**。**遗留**：若要直接移植 SEU-Monitor 的 Go 代码，仍需先取得 miunerofrade 书面许可；SEUdaily 等三源仍是 MIT 合法移植，暂无变化。
