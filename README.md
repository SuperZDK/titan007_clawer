# Titan007 爬虫

爬取球探体育（zq.titan007.com）的比赛分析、亚盘、大小球、欧赔数据。

## 快速开始

```bash
# 查看支持哪些联赛及其 ID
python run.py --list-leagues

# 查看所有参数
python run.py --help
```

## Pipeline 一览

| Pipeline | 数据来源 | 存储路径 |
|---|---|---|
| `schedule` | zq.titan007.com/jsData/matchResult/{season}/s{id}.js | data/schedule/ |
| `analysis` | zq.titan007.com/analysis/ | data/analysis/ |
| `asian` | vip.titan007.com/changeDetail/ | data/odds/asian/ |
| `ou` | vip.titan007.com/changeDetail/ | data/odds/over_under/ |
| `euro` | 1x2d.titan007.com/{sid}.js → 1x2.titan007.com/OddsHistory.aspx | data/odds/european/ |
| `live` | 增量爬取：titan + nowscore fallback（一次 3in1 请求双盘） | 复用上面各存储路径 |

## 常用命令

```bash
# 赛程
python run.py --pipeline schedule --league 36       # 英超所有赛季
python run.py --pipeline schedule --league 36 --force # 强制覆盖历史赛季
python run.py --pipeline schedule --type cup --league 103  # 欧冠

# 跑单个联赛的单个 pipeline
python run.py --pipeline analysis --league 36
python run.py --pipeline asian --league 36
python run.py --pipeline ou --league 36
python run.py --pipeline euro --league 36

# 跑单个联赛的亚盘（只爬全场）
python run.py --pipeline asian --league 36 --asian-full-only

# 跑全部 11 个联赛的全部 pipeline（不含 schedule）
python run.py

# 跑全部 11 个联赛的亚盘（只爬全场）
python run.py --pipeline asian --asian-full-only

# 指定赛季
python run.py --pipeline analysis --league 36 --season 2024-2025 --season 2023-2024
```

**执行顺序**（非 schedule pipeline）：默认按**赛季从新到旧**遍历，每个赛季内遍历 11 个联赛。
例如：2025 赛季跑完英超→西甲→...→J2，再进入 2024 赛季。

## 联赛 ID

| ID | 联赛 | 赛季格式 |
|---|---|---|
| 36 | 英超 | 2025-2026 |
| 31 | 西甲 | 2025-2026 |
| 8 | 德甲 | 2025-2026 |
| 34 | 意甲 | 2025-2026 |
| 11 | 法甲 | 2025-2026 |
| 37 | 英冠 | 2025-2026 |
| 23 | 葡超 | 2025-2026 |
| 16 | 荷甲 | 2025-2026 |
| 25 | J1 联赛 | 2025 |
| 273 | 澳超 | 2025-2026 |
| 284 | J2 联赛 | 2025 |

## 杯赛 ID

| ID | 赛事 | 赛季格式 |
|---|---|---|
| 103 | 欧冠 | 2025-2026 |
| 113 | 欧联 | 2025-2026 |
| 2187 | 欧协联 | 2025-2026 |
| 90 | 英足总杯 | 2025-2026 |
| 84 | 英联杯 | 2025-2026 |
| 51 | 德国杯 | 2025-2026 |
| 83 | 意大利杯 | 2025-2026 |
| 81 | 西班牙国王杯 | 2025-2026 |
| 54 | 法国杯 | 2025-2026 |
| 72 | 日联杯 | 2025 |

## 全场 / 半场控制

| 参数 | 作用范围 | 说明 |
|---|---|---|
| `--full-only` | 亚盘 + 大小球 | 两个都只爬全场 |
| `--asian-full-only` | 仅亚盘 | 亚盘只爬全场，大小球不受影响 |
| `--ou-full-only` | 仅大小球 | 大小球只爬全场，亚盘不受影响 |

不指定任何 `--*-full-only` 参数时，默认同时爬全场和半场。

### 示例

```bash
# 亚盘只爬全场，大小球全场+半场
python run.py --pipeline both --asian-full-only

# 大小球只爬全场，亚盘全场+半场
python run.py --pipeline both --ou-full-only

# 两者都只爬全场
python run.py --pipeline both --asian-full-only --ou-full-only

# 等价写法（向后兼容）
python run.py --pipeline both --full-only
```

## 公司 ID

```bash
# 指定欧赔公司（默认：115 威廉希尔、281 365、90 易胜博、104 Interwetten、2 betfair）
python run.py --pipeline euro --euro-companies 115 281 90

# 指定亚盘公司（默认：1 澳门、8 365、12 易胜博、17 明升）
python run.py --pipeline asian --asian-companies 1 8

# 指定大小球公司（默认同上）
python run.py --pipeline ou --ou-companies 1 8

# 亚盘只爬 1 家公司的全场
python run.py --pipeline asian --asian-companies 1 --asian-full-only
```

## Live Pipeline（增量爬取）

短生命周期进程，由 systemd timer 每 5 分钟触发（`flock` 防重叠）。空闲时开销极小：窗口外的比赛直接跳过。

```bash
# 单次 tick（生产入口）
python run.py --pipeline live

# 预览：不抓取、不写盘，打印每个比赛会做什么
python run.py --pipeline live --dry-run

# 指定"当前时间"（北京时间），用于测试窗口逻辑
python run.py --pipeline live --dry-run --now "2026-08-07 08:00"

# 强制刷新（忽略节流），通常只用于调试
python run.py --pipeline live --force --skip-season-sync
```

### 每次 tick 做什么

1. **赛季同步**（每天 10:00 后一次）：刷新 `latest_seasons.json`、检测新赛季并触发全季赛程爬取、重建当前赛季赛程文件（自动捕捉延期/赛果/新轮次）。
2. **赔率窗口** `[开赛前, 开赛+3天]`，仅赛前：亚盘 + 大小球（全场/半场）+ 欧赔。亚盘/大小球共用同一循环：titan 空则一次 nowscore `3in1Odds.aspx` 请求同时解析两盘，另一盘型本地记录缺失/过期时顺带写入。节流：P0（竞彩在售）= 5 分钟（开赛前 1 小时内缩至 3 分钟），P1 = 90 分钟。
3. **详情窗口** `[开赛前, 开赛+1天]`，仅赛前：analysis 每天刷新一次。
4. **每周一巡检**：找"开赛时间已过但无赛果"的比赛写入 `data/live_pending.json`（延期安全网）。

### 比赛分层（P0 / P1）

由 `config/live_priority.json` 白名单驱动：

```json
{
  "default": "P1",
  "dates": {
    "2026-08-08": [3000400, 3000401]
  }
}
```

某比赛日期列出的 `schedule_id` 走 P0（高频节流），其余走 P1。主项目"当日竞彩在售表"就绪后，替换 `core/priority_provider.py::get_provider` 的实现即可。

### 配置开关

每场比赛在 `config/competitions_config.json` 里有 `crawl` 开关：

```json
"crawl": { "enabled": true, "tier": "P1", "season_scope": "current" }
```

默认只启用 11 个目标联赛（英超/西甲/德甲/意甲/法甲/英冠/葡超/荷甲/J1/澳超/J2），杯赛默认关闭。

### 落盘格式

与批量 pipeline 完全同路径（`data/odds/{asian|over_under|european}/...`），增补了 `competition_id` / `competition_name_en` / `season` / `match_time` / `source` / `fetched_at` / `_version`。详见 `docs/data_contract.md`。

## 数据目录结构

```
data/
├── analysis/
│   └── leagues/English_Premier_League/2024-2025/{sid}.json
├── odds/
│   ├── asian/leagues/English_Premier_League/2024-2025/{sid}/{cid}.json
│   │                                              {sid}/{cid}_half.json
│   ├── over_under/.../{sid}/{cid}.json
│   └── european/.../{sid}/{cid}.json
├── schedule/
│   ├── leagues/English_Premier_League/2024-2025.json
│   │                            .../2025-2026.json
│   └── cups/UEFA_Champions_League/2024-2025.json
├── latest_seasons.json
├── live_state.json        # 上次赛季同步/详情刷新/周巡检标记
└── live_pending.json      # 周巡检发现的疑似延期比赛
```

## 反爬措施

| 措施 | 说明 |
|---|---|
| **UA 轮换** | 146 条真实 UA，Chrome/Firefox/Edge/Safari/Opera 混用 |
| **中文 locale** | 模拟国内用户，上海时区 |
| **随机 viewport** | 1200~1400 × 800~900 |
| **Referer 校验** | OddsHistory.aspx 必须带正确 Referer |
| **随机延迟** | 每次请求后 1~2 秒 |
| **缓存规避** | JS 数据文件 URL 带随机参数 |
| **自动重试** | 失败自动重试 2 次 |
| **直接抓 JS 数据** | 绕过动态渲染，直接请求数据源 |

## 赛程 Pipeline

### 最新赛季发现

```bash
# 从网站实时获取所有联赛/杯赛的最新赛季，存入 latest_seasons.json
python run.py --update-latest
```

`latest_seasons.json` 记录每个赛事的 `latest_season` 和 `all_seasons` 完整列表，
schedule pipeline 据此判断哪个赛季是最新的。

### 赛季判断逻辑

| 情况 | 行为 |
|---|---|
| 文件不存在 | 抓取保存 |
| 文件存在 + **最新赛季** | 重新抓取覆盖 |
| 文件存在 + 历史赛季 + `--force` | 重新抓取覆盖 |
| 文件存在 + 历史赛季 + 无 `--force` | 跳过 |

### 示例

```bash
# 更新记录表（首次或新赛季开始后运行）
python run.py --update-latest

# 爬英超：最新赛季自动覆盖，历史赛季跳过
python run.py --pipeline schedule --league 36

# 强制覆盖英超历史赛季
python run.py --pipeline schedule --league 36 --season 2020-2021 --force

# 爬欧冠
python run.py --pipeline schedule --type cup --league 103

# 全量爬所有联赛赛程
python run.py --pipeline schedule

# 指定赛季（不依赖记录表）
python run.py --pipeline schedule --league 36 --season 2025-2026 --season 2024-2025
```

## 爬取顺序建议

首次爬取推荐按顺序执行：

```bash
# 0. 更新最新赛季记录
python run.py --update-latest

# 1. 赛程
python run.py --pipeline schedule

# 2. 详情页
python run.py --pipeline analysis
# 3. 亚盘（只爬全场）
python run.py --pipeline asian --asian-full-only
# 4. 大小球（只爬全场）
python run.py --pipeline ou --ou-full-only
# 5. 欧赔
python run.py --pipeline euro
```

各 pipeline 有增量检查，已爬过的比赛不会重复请求。

> 亚盘 / 大小球批量爬取时，若 titan 为空会改用 nowscore：一次 `3in1Odds.aspx` 请求同时解析两盘，对侧盘型本地文件不存在时顺带补写（完整 `build_record` 格式，`source="nowscore"`）。补写只针对不存在的文件，不覆盖已有数据。

## Live Pipeline 部署（systemd）

部署文件已备好在 `deploy/systemd/`，用于生产服务器（Linux）：

```bash
# 假设代码在 /opt/titan007_pro，venv 在 /opt/titan007_pro/.venv
sudo cp deploy/systemd/titan007-live.service deploy/systemd/titan007-live.timer \
         deploy/systemd/titan007-live.sh /etc/systemd/system/
sudo chmod +x /etc/systemd/system/titan007-live.sh
sudo systemctl daemon-reload
sudo systemctl enable --now titan007-live.timer

# 查看状态/日志
systemctl status titan007-live.timer
journalctl -u titan007-live.service --since "10 minutes ago"
```

- Timer：每 5 分钟触发一次，`Persistent=true` 补跑错过的 tick。
- Service：`oneshot`，由 `titan007-live.sh` 用 `flock -n` 防重叠（单次 tick 超过 5 分钟时跳过而不是并发）。
- 路径按需改 `deploy/systemd/titan007-live.sh` 和 `.service` 中的 `/opt/titan007_pro`。
