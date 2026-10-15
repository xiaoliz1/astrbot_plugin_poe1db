# 流放之路 1 资料问答（AstrBot 插件）

独立实现的 PoE1 插件，参考 [`astrbot_plugin_poe2db`](https://github.com/xiaoliz1/astrbot_plugin_poe2db) 的插件组织方式，并使用 PoE1 对应的数据源。问答资料来自 [Path of Exile Wiki](https://www.poewiki.net/)，国际服行情来自 poe.ninja 的公开经济 API。

## 安装

需要 Python 3.10+ 和 AstrBot 4.24.2+。将本目录放入 AstrBot 的 `data/plugins/astrbot_plugin_poe1db/`，确认其中的 `main.py`、`metadata.yaml` 等文件位于该目录根部，然后在 AstrBot 插件页加载或重载。插件不需要额外 Python 依赖，运行问答时需要当前会话已配置聊天模型。

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
- `/poe1 国际服物价`：按混沌石参考价列出当前赛季通货与碎片。
- `/poe1 国服物价`：当前尚未接入稳定的国服公开行情源。
- `/poe1bd 角色名`：读取 poe.ninja 公开赛季列表，生成当前赛季角色筛选链接。

poe.ninja 当前只将公开经济概览接口列为受支持的 API；Builds、角色、PoB 和身份验证接口属于内部接口，不供第三方调用。因此 `/poe1bd` 仅生成 poe.ninja 网站的公开筛选页，不读取或分析角色详情，也不会绕过隐藏角色设置。若角色没有公开展示在 Builds 中，筛选页不会找到该角色。

## 数据与隐私

- PoE Wiki 请求通过其公开 MediaWiki API 完成，插件限制访问 `www.poewiki.net`，并使用短期内存缓存。
- 物价仅请求 poe.ninja 文档列明的 PoE1 经济接口，遵守服务端缓存时间并使用 ETag 条件请求；不会轮询 Builds/Profile 接口。
- 问答会将玩家问题及检索到的公开 Wiki 摘要交给 AstrBot 当前会话模型；`/poe1search`、物价和 Builds 链接命令不调用聊天模型。

## 来源

- [Path of Exile Wiki](https://www.poewiki.net/wiki/Path_of_Exile_Wiki)
- [Path of Exile Wiki 数据查询 API](https://www.poewiki.net/wiki/Path_of_Exile_Wiki:Data_query_API)
- [poe.ninja API 文档](https://poe.ninja/docs/api)
- [poe.ninja PoE1 Builds](https://poe.ninja/poe1/builds)
