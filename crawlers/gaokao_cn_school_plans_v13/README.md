# gaokao.cn 招生计划页面爬虫 v13

本目录吸收自历史仓库 `FutureTechnique/plans`，用于保留 v13 页面抓取方案和经验。

## 定位

该实现通过 Playwright 打开掌上高考学校招生计划页面：

```text
https://www.gaokao.cn/school/{school_id}/sturule
```

并按学校实际页面动态发现可选省份、年份、科类、批次、专业组和分页中的专业计划数据。

它和仓库中现有的 `crawlers/new_plans.py` 不是同一套代码；本目录用于保留 v13 中对页面 dropdown、登录态、多 worker 和错误恢复的处理逻辑，后续可按需融合进正式 `NewPlanCrawler`。

## v13 重点经验

- 不再用固定 31 省作为任务源，而是对每个学校实时读取页面实际可选省份。
- 省份、年份、科类、批次切换统一走可见 dropdown，并校验选中值。
- 切换失败后重新打开学校页面恢复状态，避免页面长期卡在错误省份。
- 专业组切换前后强制回第一页，并重新抓取 group 列表。
- 错误日志记录 stage、school_id、province/year/type/batch/group、worker_id 和 debug 信息，便于后续聚类分析。

## 使用方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python3 -m playwright install chromium

# 如目标页面需要登录，先保存登录态；不要提交 storage_state.json
python3 scripts/save_gaokao_login_state.py

# 小样本
python3 crawlers/gaokao_cn_school_plans_v13/crawl_school_plans.py   --data-file data/schools.json   --output-dir data/v13_plans   --state-file storage_state.json   --resume   --headless   --workers 4   --limit 1
```

## 不迁入的历史文件

- `storage_state.json`：浏览器登录态，可能包含敏感 cookie；
- `errors/*.jsonl`：历史运行日志；
- 旧根目录 `data.json`：体积较大且与本仓 `data/` 数据源可能重复，后续如需迁移应单独校验 schema。
