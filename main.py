"""AstrBot commands for Path of Exile 1 Wiki answers and public prices."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register
from quart import jsonify

from .builds import BuildSearchError, find_character_url
from .economy import CurrencyPrice, EconomyClient, EconomyError, PriceSnapshot
from .poecurrency import (
    NationalEconomyClient,
    NationalPriceSnapshot,
)
from .wiki import WikiClient, WikiError, WikiPage
from .price_image_store import PriceImageStore
from .price_images import render_international_html, render_national_html
from .price_notifications import (
    group_umo_parts,
    ready_price_requests,
    select_notification_targets,
)
from .price_schedule import (
    next_hourly_price_refresh_at,
    next_price_refresh_at,
    normalize_utc_offset_hours,
    timezone_for_utc_offset,
)


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
    "0.3.0",
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
        self._price_snapshots: dict[str, object] = {}
        data_dir = StarTools.get_data_dir("astrbot_plugin_poe1db")
        self._price_image_store = PriceImageStore(data_dir)
        self._price_images = dict(self._price_image_store.images)
        self._price_image_updated_at = dict(self._price_image_store.updated_at)
        self._pending_price_requests: set[tuple[str, str]] = set()
        self._known_group_umos: set[str] = set()
        self._price_refresh_lock = asyncio.Lock()
        self._manual_price_refresh_task: asyncio.Task[None] | None = None
        self._manual_price_refresh_state = "idle"
        self._manual_price_refresh_message = "后台每小时自动采集；也可以在此手动采集。"
        self._manual_price_refresh_started_at: str | None = None
        self._manual_price_refresh_completed_at: str | None = None
        self.context.register_web_api(
            "/astrbot_plugin_poe1db/price/status",
            self._price_dashboard_status_api,
            ["GET"],
            "获取 PoE1 物价采集状态",
        )
        self.context.register_web_api(
            "/astrbot_plugin_poe1db/price/refresh",
            self._start_manual_price_refresh_api,
            ["POST"],
            "手动采集 PoE1 物价",
        )
        self._price_refresh_task = asyncio.create_task(self._price_refresh_loop())

    async def terminate(self) -> None:
        """Cancel background price jobs when AstrBot unloads this plugin."""
        tasks = [
            task
            for task in (self._price_refresh_task, self._manual_price_refresh_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _price_local_timestamp(self) -> str:
        offset_hours = normalize_utc_offset_hours(
            self.config.get("price_timezone_offset"), 8.0
        )
        return datetime.now(timezone_for_utc_offset(offset_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def _price_dashboard_status(self) -> dict[str, object]:
        return {
            "state": self._manual_price_refresh_state,
            "message": self._manual_price_refresh_message,
            "started_at": self._manual_price_refresh_started_at,
            "completed_at": self._manual_price_refresh_completed_at,
            "tables": {
                market: {
                    "ready": bool(self._price_images.get(market)),
                    "updated_at": self._price_image_updated_at.get(market),
                }
                for market in ("international", "national")
            },
        }

    async def _price_dashboard_status_api(self):
        return jsonify(self._price_dashboard_status())

    async def _start_manual_price_refresh_api(self):
        task = self._manual_price_refresh_task
        if task is not None and not task.done():
            return jsonify(self._price_dashboard_status())
        self._manual_price_refresh_state = "running"
        self._manual_price_refresh_message = "正在采集 PoE1 国际服和国服价格并生成图片……"
        self._manual_price_refresh_started_at = self._price_local_timestamp()
        self._manual_price_refresh_completed_at = None
        self._manual_price_refresh_task = asyncio.create_task(
            self._run_manual_price_refresh()
        )
        return jsonify(self._price_dashboard_status())

    async def _run_manual_price_refresh(self) -> None:
        try:
            complete = await self._refresh_price_tables()
            try:
                await self._notify_pending_price_requests()
            except Exception as exc:
                self._warn_price_refresh("手动采集后的查询回告", exc)
            if complete:
                self._manual_price_refresh_state = "success"
                self._manual_price_refresh_message = "两服价格采集和图片生成已完成；物价命令现在会使用新图片。"
            else:
                self._manual_price_refresh_state = "failed"
                self._manual_price_refresh_message = "至少一服采集或图片生成失败，已保留最近成功的图片；请查看插件日志。"
        except asyncio.CancelledError:
            self._manual_price_refresh_state = "cancelled"
            self._manual_price_refresh_message = "插件卸载或重载，手动采集已停止。"
            raise
        except Exception as exc:
            self._warn_price_refresh("手动采集", exc)
            self._manual_price_refresh_state = "failed"
            self._manual_price_refresh_message = "物价采集失败，已保留最近成功的图片；请查看插件日志。"
        finally:
            self._manual_price_refresh_completed_at = self._price_local_timestamp()

    def _warn_price_refresh(self, source: str, error: object) -> None:
        plugin_logger = getattr(self, "logger", None)
        if plugin_logger and hasattr(plugin_logger, "warning"):
            plugin_logger.warning(f"{source}物价表刷新失败，保留最近成功数据：{error}")

    async def _refresh_price_tables(self) -> bool:
        complete = True
        updated_markets: list[str] = []
        async with self._price_refresh_lock:
            self.economy.invalidate_cache()
            self.national_economy.invalidate_cache()
            international_result, national_result = await asyncio.gather(
                self.economy.currency_snapshot(),
                self.national_economy.currency_snapshot(),
                return_exceptions=True,
            )
            if isinstance(international_result, PriceSnapshot):
                self._price_snapshots["international"] = international_result
                updated_markets.append("international")
            else:
                self._warn_price_refresh("国际服", international_result)
                complete = False
            if isinstance(national_result, NationalPriceSnapshot):
                self._price_snapshots["national"] = national_result
                updated_markets.append("national")
            else:
                self._warn_price_refresh("国服", national_result)
                complete = False

            render_results = await asyncio.gather(
                *(self._render_price_image(market) for market in updated_markets),
                return_exceptions=True,
            )
            for market, image_path in zip(updated_markets, render_results):
                if isinstance(image_path, str) and image_path:
                    try:
                        persisted_path = self._price_image_store.save_replacement(
                            market, image_path, self._price_local_timestamp()
                        )
                    except Exception as exc:
                        self._warn_price_refresh(f"{market}图片保存", exc)
                        complete = False
                        continue
                    self._price_images[market] = persisted_path
                    self._price_image_updated_at[market] = self._price_image_store.updated_at[market]
                else:
                    self._warn_price_refresh(f"{market}图片生成", image_path)
                    complete = False
        return complete

    async def _render_price_image(self, market: str) -> str | None:
        snapshot = self._price_snapshots.get(market)
        if market == "international" and isinstance(snapshot, PriceSnapshot):
            html = render_international_html(snapshot, self._price_local_timestamp())
        elif market == "national" and isinstance(snapshot, NationalPriceSnapshot):
            international = self._price_snapshots.get("international")
            icons_by_name = (
                {
                    re.sub(r"[^a-z0-9]", "", price.name.casefold()): price.icon_url
                    for price in international.prices
                    if isinstance(price, CurrencyPrice) and price.icon_url
                }
                if isinstance(international, PriceSnapshot)
                else {}
            )
            html = render_national_html(snapshot, icons_by_name)
        else:
            return None
        try:
            image_path = await self.html_render(
                html,
                data={},
                return_url=False,
                options={"type": "png", "full_page": True},
            )
        except Exception as exc:
            self._warn_price_refresh("物价图片生成", exc)
            return None
        return str(image_path) if image_path else None

    async def _price_refresh_loop(self) -> None:
        complete = False
        try:
            complete = await self._refresh_price_tables()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._warn_price_refresh("物价", exc)
        try:
            await self._notify_pending_price_requests()
        except Exception as exc:
            self._warn_price_refresh("物价查询回告", exc)

        notify_after_success = False
        while True:
            offset = normalize_utc_offset_hours(self.config.get("price_timezone_offset"), 8.0)
            timezone = timezone_for_utc_offset(offset)
            now = datetime.now(timezone)
            events = [
                (next_price_refresh_at(now, self.config.get("price_refresh_times"), offset), "notification"),
                (next_hourly_price_refresh_at(now, offset), "collection"),
            ]
            if not complete:
                events.append((now + timedelta(minutes=15), "retry"))
            run_at = min(event_time for event_time, _ in events)
            await asyncio.sleep(max(1.0, (run_at - datetime.now(timezone)).total_seconds()))
            due = {name for event_time, name in events if event_time == run_at}
            if "notification" in due:
                notify_after_success = True
            if due & {"collection", "retry"}:
                try:
                    complete = await self._refresh_price_tables()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._warn_price_refresh("物价", exc)
                    complete = False
                try:
                    await self._notify_pending_price_requests()
                except Exception as exc:
                    self._warn_price_refresh("物价查询回告", exc)
            if complete and notify_after_success:
                try:
                    await self._send_scheduled_price_notifications()
                except Exception as exc:
                    self._warn_price_refresh("物价通知", exc)
                notify_after_success = False

    def _remember_group_session(self, event: AstrMessageEvent) -> None:
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if group_umo_parts(umo):
            self._known_group_umos.add(umo)

    def _price_notification_enabled(self) -> bool:
        value = self.config.get("price_notification_enabled", False)
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on", "是"}
        return bool(value)

    def _proactive_platform_ids(self) -> list[str]:
        manager = getattr(self.context, "platform_manager", None)
        platforms = getattr(manager, "platform_insts", []) if manager else []
        result: list[str] = []
        for platform in platforms:
            try:
                metadata = platform.meta()
            except Exception:
                continue
            if not getattr(metadata, "support_proactive_message", True):
                continue
            platform_id = str(getattr(metadata, "id", "") or "").strip()
            if platform_id and platform_id not in result:
                result.append(platform_id)
        return result

    def _price_notification_destinations(self) -> list[str]:
        return select_notification_targets(
            self.config.get("price_notification_mode", "whitelist"),
            self.config.get("price_notification_targets", ""),
            self._known_group_umos,
            self._proactive_platform_ids(),
        )

    async def _notify_pending_price_requests(self) -> None:
        labels = {"international": "国际服", "national": "国服"}
        for umo, market in ready_price_requests(self._pending_price_requests, set(self._price_images)):
            image_path = self._price_images.get(market)
            if not image_path:
                continue
            try:
                sent = await self.context.send_message(
                    umo,
                    MessageChain().message(f"{labels[market]}物价采集完成，这是你刚才查询的价格表：").file_image(image_path),
                )
                if sent:
                    self._pending_price_requests.discard((umo, market))
                else:
                    self._warn_price_refresh("物价查询回告", f"未找到可发送到会话的平台：{umo}")
            except Exception as exc:
                self._warn_price_refresh("物价查询回告", f"发送到 {umo} 失败：{exc}")

    async def _send_scheduled_price_notifications(self) -> None:
        if not self._price_notification_enabled():
            return
        destinations = self._price_notification_destinations()
        if not destinations:
            self._warn_price_refresh("物价通知", "没有可发送的群会话，请检查通知名单和平台配置")
            return
        international = self._price_images.get("international")
        national = self._price_images.get("national")
        if not international or not national:
            self._warn_price_refresh("物价通知", "两服价格图片尚未准备完成")
            return
        for destination in destinations:
            try:
                message = (
                    MessageChain()
                    .message("《流放之路1》物价表已更新\n国际服：")
                    .file_image(international)
                    .message("\n国服：")
                    .file_image(national)
                    .message("\n\n查询物价：\n/poe1 国际服物价\n/poe1 国服物价")
                )
                if not await self.context.send_message(destination, message):
                    self._warn_price_refresh("物价通知", f"未找到可发送到会话的平台：{destination}")
            except Exception as exc:
                self._warn_price_refresh("物价通知", f"发送到 {destination} 失败：{exc}")

    async def _price_result(self, event: AstrMessageEvent, market: str):
        image_path = self._price_images.get(market)
        if image_path:
            return event.image_result(image_path)
        self._pending_price_requests.add((str(event.unified_msg_origin), market))
        label = "国际服" if market == "international" else "国服"
        return event.plain_result(f"{label}物价图片正在首次采集；后台每小时更新，完成后会自动发送。")

    @filter.command("poe1")
    async def poe1(self, event: AstrMessageEvent):
        """Answer a PoE1 question or show current international prices."""
        self._remember_group_session(event)
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
            yield await self._price_result(event, "international")
            return
        if query in ("国服物价", "國服物價"):
            yield await self._price_result(event, "national")
            return
        if len(query) > 300:
            yield event.plain_result("问题请控制在 300 字以内。")
            return
        async for result in self._answer_question(event, query):
            yield result

    @filter.command("poe1search")
    async def poe1_search(self, event: AstrMessageEvent):
        """Search PoE Wiki and return source pages without using a chat model."""
        self._remember_group_session(event)
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
        self._remember_group_session(event)
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
