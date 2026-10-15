# 更新日志

## v0.2.0 - 2026-10-15

### 新增

- 新增 `/poe1 国服物价`，读取 poecurrency.top 的 PoE1 当前赛季通货均价。
- `/poe1bd` 现在通过 Playwright + Chromium 搜索 poe.ninja 当前赛季公开 Builds，并在精确匹配时返回角色详情页链接。
- Builds 搜索无唯一匹配时明确提示未找到；Playwright/Chromium 不可用时提示检查环境，不再把筛选页链接误当成详情页。

### 调整

- 国际服 Builds 链接使用 poe.ninja 的小写赛季路由格式，修复 `Allflame` 路径 404。
- README 增加国服行情来源、OCR 数据提示及 Chromium 安装说明。

## v0.1.0 - 2026-10-15

### 新增

- 新建独立的流放之路 1 AstrBot 插件，使用 PoE Wiki 公共 MediaWiki API 搜索资料。
- 新增 `/poe1` 问答、`/poe1search` 词条搜索和 `/poe1bd` 当前赛季 Builds 筛选链接。
- 新增 `/poe1 国际服物价`，按混沌石参考价读取通货与碎片行情。
- 新增配置项、安装说明、来源与接口限制说明。
