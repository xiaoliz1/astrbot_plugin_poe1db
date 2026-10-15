"""Safe HTML renderers for PoE1 international and Chinese price tables."""

from __future__ import annotations

import html
import math
import re
from urllib.parse import unquote, urlsplit

from .economy import PriceSnapshot
from .poecurrency import CURRENCY_NAMES, NationalPriceSnapshot

IMAGE_ROWS = 50
NATIONAL_ROWS_PER_UNIT = 10


def _safe(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return html.escape(text, quote=True).replace("{", "&#123;").replace("}", "&#125;")


def _icon_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.query or parts.fragment or parts.username or parts.password or port is not None:
        return None
    path = parts.path
    if any(segment in {".", ".."} or "\\" in segment for segment in map(unquote, path.split("/"))):
        return None
    if parts.scheme != "https" or parts.hostname != "web.poecdn.com":
        return None
    if not (path.startswith("/gen/image/") or path.startswith("/image/")):
        return None
    return "https://web.poecdn.com" + path


def _format(value: float) -> str:
    if not math.isfinite(value):
        return "—"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _name_cell(name: str, icon_url: str | None = None) -> str:
    icon = _icon_url(icon_url)
    image = f'<img class="icon" src="{_safe(icon)}" alt="">' if icon else '<span class="icon empty"></span>'
    return f'<span class="item">{image}<span>{_safe(name)}</span></span>'


def _trend_svg(values: tuple[float, ...], positive: bool) -> str:
    points = tuple(value for value in values if math.isfinite(value))
    if len(points) < 2:
        return '<span class="empty">—</span>'
    low, high = min(points), max(points)
    spread = high - low
    svg_points = " ".join(
        f"{index * 92 / (len(points) - 1):.1f},{12 if not spread else 21 - (value - low) * 18 / spread:.1f}"
        for index, value in enumerate(points)
    )
    color = "#35d5a7" if positive else "#f77983"
    return (
        '<svg width="96" height="24" viewBox="0 0 96 24" aria-hidden="true">'
        f'<polyline points="{svg_points}" fill="none" stroke="{color}" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _document(title: str, subtitle: str, table: str, count: int, source: str) -> str:
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#0d1520;color:#eaf3fb;font:15px/1.5 Arial,"Microsoft YaHei","Noto Sans CJK SC",sans-serif}}
.card{{width:920px;background:#192632;border:1px solid #304252;border-radius:16px;padding:24px 28px 20px;box-shadow:0 12px 30px #06101d}}
.eyebrow{{font-size:12px;color:#28d1b0;font-weight:700;letter-spacing:2px}}h1{{font-size:27px;line-height:1.25;margin:7px 0 5px}}.meta{{color:#a9bac7;font-size:13px;margin:0 0 16px}}
.count{{color:#a9bac7;font-size:12px;margin:0 0 8px}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}th{{color:#a9bac7;font-size:12px;text-align:left;background:#223340;padding:9px 11px;border-bottom:2px solid #17c7a8}}
td{{height:39px;padding:6px 11px;border-bottom:1px solid #2c3d4a;white-space:nowrap}}tbody tr:nth-child(even){{background:#1d2b37}}.rank{{width:52px;color:#7490a3}}.item-col{{width:52%;overflow:hidden}}.item{{display:flex;align-items:center;gap:9px;overflow:hidden;font-weight:600}}.item span:last-child{{overflow:hidden;text-overflow:ellipsis}}
.icon{{width:27px;height:27px;object-fit:contain;flex:0 0 27px}}.icon.empty{{display:inline-block;border:1px solid #465766;background:linear-gradient(135deg,#283a48,#14202b);border-radius:4px}}.value{{color:#d3e9ff;font-variant-numeric:tabular-nums;font-weight:700}}.group td{{height:31px;background:#14212c;color:#26d0ae;font-size:12px;font-weight:700;letter-spacing:1px}}
.category{{width:105px;color:#9eb2c2;font-size:12px;overflow:hidden;text-overflow:ellipsis}}.trend{{width:175px;color:#a9bac7;font-size:12px;text-align:right}}.trend-inner{{display:flex;align-items:center;justify-content:flex-end;gap:8px}}.up{{color:#35d5a7}}.down{{color:#f77983}}.flat,.empty{{color:#879aa9}}
.foot{{margin:12px 0 0;color:#879aa9;font-size:11px}}
</style></head><body><main class="card"><div class="eyebrow">PATH OF EXILE 1 · ECONOMY</div><h1>{_safe(title)}</h1><p class="meta">{_safe(subtitle)}</p><p class="count">按价格排序 · 显示 {count} 项</p>{table}<p class="foot">数据来源：{_safe(source)} · 图片由 AstrBot 后台定时生成</p></main></body></html>'''


def render_international_html(snapshot: PriceSnapshot, updated_at: str) -> str:
    divine_price = next(
        (
            price.chaos_value
            for price in snapshot.prices
            if re.sub(r"[^a-z0-9]", "", price.name.casefold()) in {"divineorb", "divine"}
            and math.isfinite(price.chaos_value)
            and price.chaos_value > 0
        ),
        None,
    )
    unit = "神圣石" if divine_price else "混沌石"
    divisor = divine_price or 1.0
    ranked_prices = sorted(snapshot.prices, key=lambda price: (-price.chaos_value, price.name))
    entries: list[str] = []
    for index, price in enumerate(ranked_prices[:IMAGE_ROWS], 1):
        value = price.chaos_value / divisor
        change = price.change_percent
        change_text = "—" if change is None else f"{change:+.1f}%"
        change_class = "flat" if change is None else ("up" if change >= 0 else "down")
        entries.append(
            "<tr>"
            f'<td class="rank">{index:02d}</td>'
            f'<td class="category">{_safe(price.category)}</td>'
            f'<td class="item-col">{_name_cell(price.name, price.icon_url)}</td>'
            f'<td class="value">{_format(value)} {_safe(unit)}</td>'
            f'<td class="trend"><span class="trend-inner">{_trend_svg(price.trend, change is not None and change >= 0)}'
            f'<span class="{change_class}">{change_text}</span></span></td>'
            "</tr>"
        )
    table = f'<table><thead><tr><th class="rank">#</th><th>分类</th><th>物品</th><th>价格（{_safe(unit)}）</th><th>七日趋势</th></tr></thead><tbody>' + "".join(entries) + "</tbody></table>"
    return _document(
        "国际服物价表",
        f"当前赛季：{snapshot.league} · 更新时间：{updated_at} · 以{unit}计价",
        table,
        min(len(ranked_prices), IMAGE_ROWS),
        "poe.ninja 公开经济 API",
    )


def render_national_html(
    snapshot: NationalPriceSnapshot,
    icons_by_english_name: dict[str, str] | None = None,
) -> str:
    icon_map = icons_by_english_name or {}
    entries: list[str] = []
    count = 0
    for unit in ("d", "e", "c"):
        prices = [price for price in snapshot.prices if price.currency_unit == unit]
        prices.sort(key=lambda price: (-max(price.buy_average, price.sell_average), price.name))
        if not prices:
            continue
        entries.append(f'<tr class="group"><td colspan="4">按{_safe(CURRENCY_NAMES[unit])}计价</td></tr>')
        for index, price in enumerate(prices[:NATIONAL_ROWS_PER_UNIT], 1):
            icon = icon_map.get(re.sub(r"[^a-z0-9]", "", price.english_name.casefold()))
            entries.append(
                "<tr>"
                f'<td class="rank">{index:02d}</td>'
                f'<td class="item-col">{_name_cell(price.name, icon)}</td>'
                f'<td class="value">买 { _format(price.buy_average) } { _safe(CURRENCY_NAMES[unit])}</td>'
                f'<td class="value">卖 { _format(price.sell_average) } { _safe(CURRENCY_NAMES[unit])}</td>'
                "</tr>"
            )
            count += 1
    table = '<table><thead><tr><th class="rank">#</th><th>物品</th><th>买入均价</th><th>卖出均价</th></tr></thead><tbody>' + "".join(entries) + "</tbody></table>"
    updated_at = snapshot.latest_update or "接口未提供更新时间"
    return _document(
        "国服物价表",
        f"PoE1 当前赛季 · 数据更新时间：{updated_at}",
        table,
        count,
        "poecurrency.top 国服行情（OCR 采集）",
    )
