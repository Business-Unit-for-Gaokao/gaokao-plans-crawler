# gaokao-plans-crawler
Generated crawler repo for plans

<!-- target-crawl-links:start -->
## Target Crawl Links

This crawler targets 掌上高考 admission plan data.

| Data | Link |
| --- | --- |
| 掌上高考根域名 | `https://www.gaokao.cn` |
| 静态数据域名 | `https://static-data.gaokao.cn` |
| 招生计划接口模板 | `https://static-data.gaokao.cn/www/2.0/schoolspecialplan/{school_id}/{province_id}/{type}.json` |
| 招生计划学校页 | `https://www.gaokao.cn/school/{school_id}` |
<!-- target-crawl-links:end -->

<!-- crawl-sources:start -->
## 爬取链接 / 数据源

> 维护说明：本节只记录源码中实际请求的源站/接口；爬取结果文件（data/results/output/json/csv/xlsx 等）不纳入统计。

### 掌上高考招生计划

- `https://static-data.gaokao.cn/www/2.0/schoolspecialplan/{school_id}/{year}/{province_id}.json`
- `https://www.gaokao.cn/school/{school_id}/sturule`

### 通用 API / Header

- `https://api.zjzw.cn/web/api/`
- `Origin: https://www.gaokao.cn`
- `Referer: https://www.gaokao.cn/`
<!-- crawl-sources:end -->
