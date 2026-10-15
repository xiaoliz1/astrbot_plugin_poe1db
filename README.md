# 流放之路 1 资料问答（AstrBot 插件）

独立实现的 PoE1 插件，参考 [`astrbot_plugin_poe2db`](https://github.com/xiaoliz1/astrbot_plugin_poe2db) 的插件组织方式，并使用 PoE1 对应的数据源。问答资料来自 [Path of Exile Wiki](https://www.poewiki.net/)，国际服行情来自 poe.ninja 公开经济 API，国服行情来自 [poecurrency.top](https://poecurrency.top/)。

## 安装

需要 Python 3.10+、AstrBot 4.24.2+ 和 Chromium。将本目录放入 AstrBot 的 `data/plugins/astrbot_plugin_poe1db/`，在 AstrBot 插件页加载或重载。插件通过 `requirements.txt` 安装 Playwright；在 AstrBot 运行环境中再执行 `python -m playwright install chromium`。运行问答时需要当前会话已配置聊天模型。

## 指令

```text
/poe1
/poe1 火球有什么效果？
/poe1 国际服物价
/poe1 国服物价
/poe1search Fireball
/poe1bd 角色名
```

- `/poe1`：显示指令用法。
- `/poe1 问题`：把问题转换为 PoE Wiki 搜索词，读取相关页面，再由当前聊天模型以简体中文简短回答并附来源。
- `/poe1search 英文词条`：直接搜索 PoE Wiki，不调用聊天模型。
- `/poe1 国际服物价`：发送后台生成的当前赛季价格图片，按混沌石价格列出 poe.ninja PoE1 通货与碎片。
- `/poe1 国服物价`：发送后台生成的行情图片，按神圣石、崇高石和混沌石计价分组显示 poecurrency.top 的买卖均价。
- `/poe1bd 角色名`：在 poe.ninja 当前赛季公开 Builds 页搜索精确角色名，只返回唯一匹配角色的详情页链接；没有唯一公开匹配时说明未找到。

角色检索使用 Playwright + Chromium 打开 poe.ninja 公开 Builds 页面并读取页面上显示的角色详情链接，不调用 poe.ninja 内部角色 API，也不会绕过隐藏角色设置。角色未公开展示或出现重名时会说明无法唯一定位；Chromium 不可用时会提示检查运行环境，不会把搜索页链接误当成详情页返回。

物价会在插件启动时采集，并在每小时整点后台更新；命令直接发送最近成功生成的图片，不会因每次查询重复采集。生成的图片会保存在插件数据目录中，直到同一服的新图片成功生成才替换。插件页面“物价采集”可以立即刷新两服行情。群通知默认关闭，可在插件配置中启用并设置白名单/黑名单、目标群、每日通知时段和 UTC 偏移；默认通知时刻为 00:00、06:00、12:00、18:00（UTC+8）。

## 数据与隐私

- PoE Wiki 请求通过其公开 MediaWiki API 完成，插件限制访问 `www.poewiki.net`，并使用短期内存缓存。
- 国际服物价仅请求 poe.ninja 文档列明的 PoE1 经济接口，遵守服务端缓存时间并使用 ETag 条件请求；国服物价读取 `poecurrency.top` 的 `version=1` 当前赛季汇总接口并缓存一小时。
- `poecurrency.top` 标注其国服行情由 OCR 采集，数据可能出现识别偏差；该站服务仅供个人非商业使用。
- 国际服和国服物价图片由 AstrBot HTML 渲染生成；接口或图片生成失败时会保留上一张成功图片。
- 问答会将玩家问题及检索到的公开 Wiki 摘要交给 AstrBot 当前会话模型；`/poe1search`、物价和 Builds 链接命令不调用聊天模型。

## 来源

- [Path of Exile Wiki](https://www.poewiki.net/wiki/Path_of_Exile_Wiki)
- [Path of Exile Wiki 数据查询 API](https://www.poewiki.net/wiki/Path_of_Exile_Wiki:Data_query_API)
- [poe.ninja API 文档](https://poe.ninja/docs/api)
- [poe.ninja PoE1 Builds](https://poe.ninja/poe1/builds)
- [poecurrency.top API 文档](https://poecurrency.top/api.html)
