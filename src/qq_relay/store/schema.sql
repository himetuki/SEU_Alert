-- qq-relay SQLite schema（P0 建表；python -m qq_relay.store.db 初始化）
-- 设计口径见 docs/config.md 与 docs/architecture.md 数据契约。

CREATE TABLE IF NOT EXISTS events (          -- RawEvent 落库（预筛前的原始事件）
  event_id      TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  group_id      TEXT NOT NULL,
  group_name    TEXT,
  sender_id     TEXT,
  sender_card   TEXT,
  msg_id        TEXT,
  text          TEXT NOT NULL,
  ts            INTEGER NOT NULL,
  at_all        INTEGER NOT NULL DEFAULT 0,
  content_hash  TEXT NOT NULL,               -- 去重键（同内容多群转发只判一次）
  received_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_hash  ON events(content_hash);
CREATE INDEX IF NOT EXISTS idx_events_group ON events(group_id, ts);

CREATE TABLE IF NOT EXISTS items (           -- ClassifiedEvent（分类树输出）
  event_id      TEXT PRIMARY KEY,
  groups_json   TEXT NOT NULL,               -- fan-in：所有来源群
  cat           TEXT NOT NULL,
  cat2          TEXT NOT NULL,
  is_info       REAL NOT NULL,
  urg           INTEGER NOT NULL,
  action        TEXT NOT NULL,
  has_ddl       INTEGER NOT NULL,
  course        TEXT,
  scope         TEXT,
  channel       TEXT,
  stage         TEXT,
  deadline      TEXT,
  deadline_src  TEXT NOT NULL DEFAULT 'none',
  low_conf      INTEGER NOT NULL DEFAULT 0,
  raw_text      TEXT NOT NULL,
  model_calls_json TEXT,
  created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_cat ON items(cat, created_at);

CREATE TABLE IF NOT EXISTS users (
  user_qq     TEXT PRIMARY KEY,
  joined_at   INTEGER NOT NULL,
  note        TEXT
);

CREATE TABLE IF NOT EXISTS subs (
  user_qq        TEXT PRIMARY KEY,
  groups_json    TEXT NOT NULL,
  cats_json      TEXT NOT NULL,
  inc_json       TEXT,
  exc_json       TEXT,
  quiet_json     TEXT,
  instant_min_urg INTEGER NOT NULL DEFAULT 2,
  digest         INTEGER NOT NULL DEFAULT 1,
  updated_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (      -- 每次分发（测试期=文件路径）
  delivery_id  TEXT PRIMARY KEY,
  user_qq      TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  mode         TEXT NOT NULL,                -- file | qq
  path         TEXT,                         -- file 模式下的 txt 路径
  kind         TEXT NOT NULL,                -- instant | digest
  urg          INTEGER NOT NULL,
  created_at   INTEGER NOT NULL,
  ack          INTEGER NOT NULL DEFAULT 0    -- 负反馈/已读标记
);
CREATE INDEX IF NOT EXISTS idx_deliveries_user ON deliveries(user_qq, created_at);

CREATE TABLE IF NOT EXISTS labels (          -- 人工标注 / 负反馈 / 复核确认
  label_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id   TEXT,
  source     TEXT NOT NULL,                  -- goldset | feedback | review
  cat        TEXT,
  cat2       TEXT,
  urg        INTEGER,
  deadline   TEXT,
  note       TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (           -- 配置变更审计（画像/过滤/订阅）
  audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,
  target      TEXT NOT NULL,
  before_json TEXT,
  after_json  TEXT,
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (     -- 模型调用与用量（配额监控）
  call_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  endpoint    TEXT NOT NULL,                 -- jev | chat
  model       TEXT,
  state_hash  TEXT,
  questions   INTEGER,
  resp_json   TEXT,
  latency_ms  INTEGER,
  trace_id    TEXT,
  in_tokens   INTEGER,
  out_tokens  INTEGER,
  ok          INTEGER NOT NULL,
  err         TEXT,
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS filtered_log (    -- 预筛丢弃记录（可审计，防静默漏报）
  filter_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    TEXT,
  stage       TEXT NOT NULL,                 -- sender_filter | dedup | keyword | jev_drop
  reason      TEXT NOT NULL,
  detail      TEXT,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filtered_stage ON filtered_log(stage, created_at);
