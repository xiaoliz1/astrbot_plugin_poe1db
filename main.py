"""AstrBot commands for Path of Exile 1 Wiki answers and public prices."""

from __future__ import annotations

import json
import re

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .builds import BuildSearchError, find_character_url
from .economy import EconomyClient, EconomyError
from .poecurrency import (
    CURRENCY_NAMES,
    NationalEconomyClient,
    NationalEconomyError,
)
from .wiki import WikiClient, WikiError, WikiPage


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _command_argument(message: str, command: str) -> str:
    text = message.strip()
    match = re.match(rf"(?i)^\s*\S*?{re.escape(command)}(?:\s+|$)", text)
    return text[match.end():].strip() if match else text


def _format_search_results(pages: list[WikiPage], limit: int = 5) -> str:
    if not pages:
        return "没有找到匹配词条。可以尝试英文技能名、物品名或机制名。"
    rows = ["PoE Wiki 搜索结果："]
    for index, page in enumerate(pages[:limit], 1):
        snippet = page.extract[:240].strip()
        if len(page.extract) > 240:
            snippet += "…"
        rows.append(f"{index}. {page.title}\n{snippet}\n{page.url}")
    return "\n\n".join(rows)


def _parse_terms(text: str, fallback: str) -> list[str]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    candidates = value.get("queries") if isinstance(value, dict) else None
    results: list[str] = []
    if isinstance(candidates, list):
        for candidate in candidates[:3]:
            if isinstance(candidate, str):
                term = re.sub(r"\s+", " ", candidate).strip()[:100]
                if term and term.casefold() not in {item.casefold() for item in results}:
                    results.append(term)
    if not results:
        results.append(fallback[:120])
    return results


def _completion_text(response: object) -> str:
    text = getattr(response, "completion_text", "")
    return text.strip() if isinstance(text, str) else ""


@register(
    "astrbot_plugin_poe1db",
    "xiaoliz1",
    "流放之路1资料问答",
    "0.2.0",
)
class Poe1DBPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        timeout = _bounded_int(config.get("timeout_seconds"), 15, 5, 30)
        cache_seconds = _bounded_int(config.get("cache_minutes"), 15, 0, 60) * 60
        self.wiki = WikiClient(timeout, cache_seconds)
        self.economy = EconomyClient(timeout, 300)
        self.national_economy = NationalEconomyClient(timeout, 3600)
        self.build_timeout = timeout

    @filter.command("poe1")
    async def poe1(self, event: AstrMessageEvent):
        """Answer a PoE1 question or show current international prices."""
        query = _command_argument(event.message_str, "poe1")
        if not query:
            yield event.plain_result(
                "《流放之路 1》：\n"
                "/poe1 问题\n"
                "/poe1 国际服物价\n"
                "/poe1 国服物价\n"
                "/poe1search 英文词条\n"
                "/poe1bd 角色名"
            )
            return
        if query in ("国际服物价", "國際服物價"):
            yield event.plain_result(await self._price_text())
            return
        if query in ("国服物价", "國服物價"):
            yield event.plain_result(await self._national_price_text())
            return
        if len(query) > 300:
            yield event.plain_result("问题请控制在 300 字以内。")
            return
        async for result in self._answer_question(event, query):
            yield result

    @filter.command("poe1search")
    async def poe1_search(self, event: AstrMessageEvent):
        """Search PoE Wiki and return source pages without using a chat model."""
        query = _command_argument(event.message_str, "poe1search")
        if not query:
            yield event.plain_result("用法：/poe1search 英文技能名、物品名或机制名")
            return
        if len(query) > 120:
            yield event.plain_result("搜索词请控制在 120 个字符以内。")
            return
        try:
            pages = await self.wiki.search(query, limit=5)
        except WikiError as exc:
            yield event.plain_result(f"PoE Wiki 暂时无法搜索：{exc}")
            return
        yield event.plain_result(_format_search_results(pages))

    @filter.command("poe1bd")
    async def poe1_build(self, event: AstrMessageEvent):
        """Find a public poe.ninja Builds character detail page by name."""
        name = _command_argument(event.message_str, "poe1bd")
        if not name:
            yield event.plain_result("用法：/poe1bd 角色名")
            return
        try:
            league = await self.economy.current_league()
        except (EconomyError, ValueError) as exc:
            yield event.plain_result(f"暂时无法查询 poe.ninja 当前赛季：{exc}")
            return
        try:
            detail_url = await find_character_url(
                league, name, timeout_seconds=self.build_timeout
            )
        except BuildSearchError:
            yield event.plain_result(
                "暂时无法读取 poe.ninja 角色详情，请检查 AstrBot 环境中的 "
                "Playwright、Chromium 和网络连接。"
            )
            return
        if detail_url:
            yield event.plain_result(detail_url)
        else:
            yield event.plain_result(f"当前赛季 Builds 中未找到「{name}」的唯一公开角色详情页。")

    async def _price_text(self) -> str:
        try:
            snapshot = await self.economy.currency_snapshot()
        except EconomyError as exc:
            return f"国际服物价暂时无法读取：{exc}"
        rows = [f"PoE1 国际服物价 · {snapshot.league} · 混沌石参考价"]
        for index, price in enumerate(snapshot.prices[:25], 1):
            rows.append(f"{index}. {price.name}：{price.chaos_value:g} 混沌石")
        rows.append("数据源：poe.ninja 公开经济 API")
        return "\n".join(rows)

    async def _national_price_text(self) -> str:
        try:
            snapshot = await self.national_economy.currency_snapshot()
        except NationalEconomyError as exc:
            return f"国服物价暂时无法读取：{exc}"
        rows = ["PoE1 国服通货行情 · 今日均价"]
        if snapshot.latest_update:
            rows[0] += f" · 更新至 {snapshot.latest_update}"
        for unit in ("d", "e", "c"):
            prices = [price for price in snapshot.prices if price.currency_unit == unit]
            if not prices:
                continue
            rows.append(f"\n按{CURRENCY_NAMES[unit]}计价：")
            prices.sort(
                key=lambda price: (-max(price.buy_average, price.sell_average), price.name)
            )
            for price in prices[:10]:
                rows.append(
                    f"{price.name}：买 {price.buy_average:g} / 卖 {price.sell_average:g} "
                    f"{CURRENCY_NAMES[unit]}"
                )
        rows.append("数据源：poecurrency.top（国服公开行情，OCR 采集）")
        return "\n".join(rows)

    async def _answer_question(self, event: AstrMessageEvent, question: str):
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
        except Exception:
            yield event.plain_result("请先为当前会话配置可用的聊天模型。")
            return

        try:
            query_response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=(
                    "你负责把《流放之路》玩家的问题转换为 PoE Wiki 的英文搜索词。"
                    '只输出 JSON：{"queries":["English term"]}。'
                    "最多给出三个具体技能、物品或机制名称；不要解释，也不要猜不确定的名称。"
                ),
                prompt=f"玩家问题：{question}",
            )
            terms = _parse_terms(_completion_text(query_response), question)
        except Exception:
            terms = [question]

        term = terms[0]
        page = None
        normalize = lambda value: re.sub(r"[\W_]+", "", value.casefold())
        for candidate_term in terms:
            try:
                hits = await self.wiki.search(candidate_term, limit=5)
                if not hits:
                    continue
                exact = [
                    hit for hit in hits
                    if normalize(hit.title) == normalize(candidate_term)
                ]
                selected = exact[0] if exact else hits[0]
                page = await self.wiki.page(selected.title)
                if page:
                    term = candidate_term
                    break
            except WikiError:
                continue
        if not page:
            yield event.plain_result(
                "PoE Wiki 没有找到足够资料；可以改用英文技能名或物品名搜索。\n"
                + self.wiki.search_url(term)
            )
            return

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=(
                    "你是《流放之路》资料助手。根据给出的 PoE Wiki 原文，用简体中文简短回答。"
                    "只陈述来源支持的内容；资料不足就明确说不足，不要补猜。"
                    "回答控制在 250 个汉字以内，不要重复列出长篇英文原文。"
                ),
                prompt=f"玩家问题：{question}\n\nPoE Wiki 资料：\n[{page.title}]\n{page.extract}",
            )
            answer = _completion_text(response)
        except Exception:
            answer = "当前聊天模型未能完成资料整理，请查看 PoE Wiki 页面。"
        if not answer:
            answer = "当前没有生成可用的简体中文回答，请查看 PoE Wiki 页面。"
        yield event.plain_result(f"{answer.strip()}\n资料：{page.title} {page.url}")
