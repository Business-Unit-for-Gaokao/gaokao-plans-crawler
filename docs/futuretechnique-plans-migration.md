# FutureTechnique/plans 合并记录

历史仓库：`FutureTechnique/plans`

正式仓库：`Business-Unit-for-Gaokao/gaokao-plans-crawler`

## 结论

`FutureTechnique/plans` 不是通用计划仓库，而是掌上高考招生计划页面爬虫 v13。正式仓库已经存在 `gaokao-plans-crawler`，因此不做整仓 transfer，而是把有价值的 v13 代码和经验吸收到正式仓。

## 已合并内容

| 来源 | 目标 | 说明 |
| --- | --- | --- |
| `crawl_school_plans.py` | `crawlers/gaokao_cn_school_plans_v13/crawl_school_plans.py` | v13 页面抓取脚本，保留动态省份发现、dropdown 校验、多 worker、错误恢复逻辑。 |
| `dedupe_meta_errors.py` | `scripts/dedupe_plan_errors.py` | 错误日志去重/汇总工具。 |
| `save_login_state.py` | `scripts/save_gaokao_login_state.py` | 手动登录并保存 Playwright storage state 的辅助脚本。 |
| `open_with_storage_state.py` | `scripts/open_gaokao_with_storage_state.py` | 使用登录态打开指定页面进行人工检查。 |
| README 经验 | `crawlers/gaokao_cn_school_plans_v13/README.md` | 保存 v13 重点经验和使用方式。 |

## 未合并内容

| 来源 | 原因 |
| --- | --- |
| `storage_state.json` | 可能包含登录态/cookie，不应提交。 |
| `errors/*.jsonl` | 运行日志，不属于正式代码资产。 |
| `data.json` | 31MB 学校列表，需先和正式仓 `data/` 数据源比对，避免重复。 |

## 后续建议

1. 以 `crawlers/new_plans.py` 作为正式主实现。
2. 从 v13 逐步吸收以下能力：
   - 每校动态发现可选省份；
   - dropdown 选中值校验；
   - 切换失败后的 reopen/recover；
   - 专业组切换前后强制回第一页；
   - 更细粒度的错误日志聚类。
3. 验证 v13 逻辑后，可将其能力融入 `NewPlanCrawler`，再删除 v13 兼容目录。
