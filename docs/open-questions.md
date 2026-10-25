# 待决问题与已知缺口

> 版本 v0.2 · 2026-10-25 · Q1/Q2 已由用户拍板，留档于 decisions.md（ADR-018/019）

## 已决（留档）

| # | 问题 | 决定 | 依据 |
|---|---|---|---|
| Q1 | 配置通道 | **bot 命令 + YAML 双通道**，单一配置管理器（单写者/原子写/热更新） | ADR-018 |
| Q2 | 下一步顺序 | **先完整搭建规划（build-plan.md），审后再搭骨架** | ADR-019 |

## 已知缺口（未讨论或主动后置）

| # | 缺口 | 状态 |
|---|---|---|
| G1 | 用户添加入口流程（加好友欢迎语、订阅引导、防举报话术） | P1 botcmd 时细化 |
| G2 | Digest 具体时间点（早/晚？周末？） | 待定，P1 先实现可配置 |
| G3 | 金标准集：需用户提供真实通知；SRTP 类若试点群没有则复制补 | P4 依赖用户 |
| G4 | JEV 免费额度与速率的实测数据 | P2 连通性测试后实测 |
| G5 | 课程别名词典初始化（各课程常见昵称） | P4 依赖用户课程表 |
| G6 | 试点小号是否已在 SRTP 群 | 待确认（影响 research 类真实数据） |
| G7 | cat 选项按画像收窄 + other 逃逸 + 全量重判 | 扩展点已留（ADR-012），accuracy 不达标时启用 |
| G8 | 根调用 6 题 vs 精简 3 题（后三题下沉 L3） | 后备方案（classification.md），准确率不达标时启用 |
| G9 | 香橙派 arm64 上 NapCat 部署方式（Docker 多架构镜像 or Python 直跑） | P5 第一步提前验证 |
| G10 | Web 端 Digest 页面 | 未规划，可选 |
| G11 | 学校网站爬虫的目标站点清单（教务处/学院/图书馆，RSS 有无） | P6，未调研 |
| G12 | 微信分发具体服务选型（WxPusher / Server酱 / 企微） | P6，未定 |

## 当前进度

- **设计文档 v0.5 完备**：architecture / classification / config / decisions(ADR-001~022) / acceptance / build-plan / runbook
- **代码进度**：P0（NapCat+OneBot+冒烟）✅、P1（预筛链/假分类器/匹配/文件分发/bot 命令）✅ 65 测试；**P6 的 web 采集提前落地**（SEU-Monitor + SEUdaily 输出库，ADR-022）
- **待用户操作**：① NapCat 扫码登录 + 反向 WS 配置（runbook 第 1 节）→ 跑冒烟过 A1 → 跑 main.py 看真实群消息入 outbox；② WSL 里跑一次 SEU-Monitor 真实扫描填充归档（runbook 第 5 节）
- **下一步**：P2 模型接入（JEV 分类树替换假分类器 + 金标准 harness）
