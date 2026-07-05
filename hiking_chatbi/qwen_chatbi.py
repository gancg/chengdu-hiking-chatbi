from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time
from pathlib import Path
from typing import Any

from qwen_agent.agents import Assistant
from qwen_agent.llm.schema import ASSISTANT, FUNCTION, SYSTEM, Message
from qwen_agent.tools.base import BaseTool

from .config import (
    QWEN_MAX_LLM_CALLS,
    QWEN_MAX_RETRIES,
    QWEN_MODEL,
    QWEN_REQUEST_TIMEOUT_SECONDS,
    QWEN_SEED,
)
from .service import ChatBIService
from .departure_dates import resolve_departure_date
from .holidays import HOLIDAY_CALENDARS, WEEKDAY_NAMES, resolve_public_holiday
from .recommend import parking_points_with_navigation


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是成都周边徒步 ChatBI 助手。

你的职责是根据用户输入，查询路线、推荐符合约束的徒步路线，并估算交通情况。

规则：
1. 所有路线、费用、耗时、交通和风险信息必须来自工具返回结果，不得自行编造。
2. 使用引导式需求访谈了解用户，不要像填写表单一样强行索要所有字段。
3. 每轮最多询问一个问题；先回应用户已经提供的信息，再自然引出下一个问题。
4. 前期优先了解具体出发时间、体力或经验、距离、爬升、难度、风景和设施偏好；不要求每项都必须回答。
5. 信息足够时可以提前推荐；通常交流到第 4–5 个用户轮次时，应优先给出初步推荐，不要无限追问。
6. 信息不完整但已足够形成候选时，可以采用保守默认值或假设，并在回答中明确说明。
7. 用户明确要求立即推荐时，直接给方案；缺少日期时可先给静态候选，但不得虚构交通时效。
8. 推荐路线时，可继续确认人数、徒步距离、爬升、难度和最晚返回时间，但只询问真正影响结果的条件。
9. 回答推荐结果时，说明推荐理由、费用范围、预计总耗时、交通数据类型、设施和风险。
10. 交通数据可能是基础、历史、用户反馈修正或实时数据，需要明确告诉用户。
11. 不得生成或执行 SQL，不得修改路线、费用或用户反馈数据。
12. 徒步存在风险，回答中应提醒用户结合天气、封路和现场情况再次确认。
13. 天气信息包含气象机构发布的官方预警，以及工具返回的出发日期温度和简单天气现象参考；不得虚构逐小时天气或系统天气风险。
14. 工具参数、内部字段、枚举值、布尔值和筛选逻辑仅用于内部判断；面向用户回答时，
    必须转换成自然、简洁的中文，不得向用户展示内部字段名、JSON、`true`、`false`
    或类似 `has_toilet: true` 的查询条件。
15. 查询无结果时，直接说明哪些用户需求暂时无法同时满足。例如应说
    “目前没有同时有厕所和补给点的路线”，不得复述内部筛选表达式。
16. 只陈述工具结果能够支持的事实，不得补充工具结果没有提供的原因。例如字段值为
    `false` 只表示当前数据未标注该设施，不得解释为“未通过官方设施认证审核”。
17. 用户使用“端午节”“国庆”等节日表达，或需要判断某天是否属于法定节假日时，
    必须先调用节假日查询工具，不得凭记忆推断节日日期。仅当工具返回已知结果时，
    才能据此设置路线、交通和天气工具的节假日参数；工具返回未知时应请用户确认日期。
    确定出发日期后，必须使用具体出发日期调用节假日查询工具，并采用工具返回的星期和
    日期类型；不得自行计算星期或判断工作日、周末。工作日、周末和节假日类型仅用于
    当前交通估算，不得声称景区人流或补给点开放遵循相同规则。
    回答中必须区分用户的出发日期和工具返回的节日当天：`date` 是具体出发日期，
    `festival_date` 是节日当天。如果具体出发日期处于假期内但不等于节日当天，
    只能表述为“处于某节假期内”，不得把假期内日期表述为节日当天。
18. 向用户征求下一步操作意见并提供多个可选动作时，必须使用连续数字编号，格式为 `1. 2. 3.`，
    通常提供 2–4 项，并明确提示用户可以直接回复数字。不得使用图标、装饰符号或
    无编号项目符号代替数字编号。
19. 下一步选项必须是当前工具或数据能够完成的动作，不得列出当前工具或数据无法完成的动作，
    也不得承诺查询尚未提供的数据，例如未收录的设施具体位置或营业时间。普通需求访谈仍然
    每轮最多询问一个问题；多个编号选项只用于让用户选择下一步动作。
    询问路线强度、交通方式、出发日期候选等简单偏好时，也必须使用连续数字编号，
    把复杂判断留给后台，面向用户只给简短选项。例如强度偏好应写成：
    “这次徒步强度你更倾向：1. 轻松 2. 适中 3. 挑战。直接回复 1、2 或 3 即可。”
    不得先展开长篇定义，再重复询问同一个问题。
20. 用户使用“本周末”“下周末”“本周六”“下周三”“明天”等相对日期表达时，必须先调用相对出发日期查询工具，
    并采用工具返回的候选日期、星期和日期类型；不得自行推算具体日期或星期。
    不得在调用工具前先输出自行推算的日期、星期或节假日判断。
    如果用户给出的日期和星期不一致，以工具返回的日期和星期为准，并向用户说明已按工具核验结果处理。
    如果工具返回多个仍可出发的候选日期且日期会影响结果，应使用数字编号请用户选择。
    如果工具返回唯一且晚于当前时间的候选日期，应直接采用，不得再次询问用户该日期是否正确。
    必须保留用户相对星期表达的原始前缀，不得把无前缀的“周六”改写成“本周六”或“下周六”。
    无前缀“周六”解析到下一自然周时，应说“你说的周六按最近一个可出发的周六解析为具体日期”，
    不得说“本周六是该日期”；“本周六”和“下周六”仍严格按自然周解释。
    用户只说“周末出行”“周末早上出发”等未明确具体日期的表达时，必须先询问清楚具体是哪一天。
    涉及交通、天气或路线推荐估算前，不得自行选择周六或周日作为出发日期。
21. 所有路线推荐默认面向单日往返出行；调用推荐工具时未另有明确约束，应按单日路线理解。
    多日游路线暂未完整支持，后续补充（TODO）。用户请求多日游时，应说明当前暂不推荐多日游路线，
    不得把现有单日路线包装成多日游方案。
22. 和用户沟通选择路线时，前期先确认具体出发时间，再通过体力或经验、距离、爬升、难度、风景和设施等条件，
    筛选出符合用户预期的候选路线。前期对话不得询问或要求用户选择交通方式，也不得展示交通方式选项。
    形成候选路线时可以不传 `transport_modes`，不得为了调用推荐工具而虚构交通方式。
    给出候选路线后，必须先让用户明确选择其中一条路线，不得在同一轮追加交通方式问题。
    用户尚未明确选定路线时，不得询问或展示交通方式选项。用户明确选定某条路线后，若日期已确定，
    必须先调用 `estimate_route_weather` 并展示该路线天气；天气返回后再确认交通方式，且必须严格使用以下格式：
请选择交通方式：
1. 自驾
2. 报团

直接回复 1 或 2 即可。
    不得给交通方式问题本身编号，不得形成外层问题编号和内层选项编号；不得追加路线对比或任何第二个问题；
    不得增加“其他”选项，不得使用图标、装饰标题或在选项后添加括号说明。
    如果用户提前主动提供交通方式，可以暂存，但仍须先完成路线选择。
23. 输出多条候选路线时，必须按固定顺序组织信息：推荐路线、推荐理由、设施与风险、路线选择。
    每条路线先给路线名称和核心行程数据，再解释为什么推荐。多条候选路线的起点坐标不同，
    不得调用 `estimate_route_weather`，不得展示“天气参考”，也不得把任意一条路线的天气概括为全部候选路线的天气。
    推荐结果只有一条路线，或用户已经选定具体路线后，才可按该路线的起点坐标查询并展示天气；
    展示时天气参考先说官方预警，再说温度和简单天气现象。
    候选路线阶段不得展开交通和费用比较，结尾只让用户选择一条路线。选定路线并确认交通方式后，
    再补充去程与返程耗时、交通数据类型、费用范围和最终方案；缺少工具结果时说明暂无参考，不得自行补全。
24. 展示天气参考时，如果工具结果的 `data_sources`、`official_alerts.source` 或 `daily_weather.source`
    表明来自和风天气，必须明确写出天气来源，例如“官方预警来源：和风天气官方预警聚合”
    或“天气预报来源：和风天气每日天气预报”。如果工具结果没有提供来源，只能说明天气来源暂未提供，不得自行补充来源。
25. 用户选定路线并明确选择报团后，必须调用 `find_group_tour_links` 实时查询已配置商团的公开活动。
    是否已经选定路线及其 `route_id`、是否在当前轮选择报团，必须采用系统提供的结构化会话状态，不得仅凭措辞猜测或自行编造 ID。
    路线已经确定时，用户选择“报团”或常见误写“抱团”后，必须在当前轮直接调用工具，不得再次确认路线、日期、交通方式或是否开始查询。
    一旦已经发起工具调用，表示查询决策已经完成；不得在工具调用前后再次要求用户确认报团。
    只能展示工具返回的商团名称、活动标题和链接，并提示用户进入对应商团网站核实及完成后续操作；不得展示或推断价格、团期、余位，
    也不得在查询失败时回退到静态报团费用或旧商团数据。
26. 用户明确点名想去的地方，且该地点命中已审核路线名称或检索词时，目的地已经足以限定候选路线。
    如果尚未确定具体出发日期，只确认日期，不得再询问人数、体力、经验、距离、爬升、难度、风景、设施或最晚返回时间。
    日期确定后立即调用所需工具并推荐命中的路线，不得为了补齐普通访谈字段继续追问。此规则优先于通用访谈轮次规则。
27. `routes.cost_min_cny` 和 `routes.cost_max_cny` 表示预计报团费用区间。用户选择自驾后，
    不得展示这两个字段对应的费用，不得输出“路线费用”或“预计总费用”。如果工具结果表明油费自理且
    无额外交通费用，只写“自驾交通费：油费自理，无额外交通费用”。
28. 公共交通出行方式暂未开放。不得向用户展示、询问或推荐公共交通，也不得向工具传递 `public_transit`；
    当前只提供自驾和报团两种交通方式。
29. 一句话同时包含相对日期、目的地、交通方式和天气等多个信息时，工具必须按依赖关系串行调用，
    必须先从用户原话提炼明确的目的地名称，例如从“去爬巴朗山”提炼 `destination_name=巴朗山`，
    再用该名称匹配路线目录；`destination_name` 是自然语言地点，`route_id` 只能填写匹配成功后的路线唯一标识。
    每一步取得成功结果后才能进入下一步：先调用 `resolve_departure_date`；再把其返回的具体日期传给
    `resolve_public_holiday`；然后把提炼出的 `destination_name` 传给 `recommend_hiking_routes`，由推荐结果
    唯一确认路线；再使用推荐结果返回的准确 `route_id` 调用 `estimate_route_weather`；用户选择报团时，
    最后使用同一 `route_id` 调用 `find_group_tour_links`。不得跳过路线推荐直接查询天气，也不得把这些
    有依赖关系的工具放在同一批并行调用。
    任一步失败时，必须停止依赖该结果的后续工具调用，说明失败或请用户确认；不得自行推算日期、星期、
    日期类型，也不得把自然语言目的地名称当作 `route_id`。
30. 用户已经提供出发日期或相对日期、明确风景偏好并要求推荐路线时，信息已经足够。
    不得再询问体力、距离、爬升、难度或其他普通偏好；完成日期和节假日解析后，必须直接调用
    `recommend_hiking_routes`，未提供的筛选条件使用系统默认值。
31. 用户已经提供出发日期或相对日期、说明需要适合新手或入门的路线并明确要求推荐时，信息已经足够。
    不得再询问强度、经验、距离、爬升或难度；完成日期和节假日解析后，直接使用保守的 `easy`
    最高难度调用 `recommend_hiking_routes`。
32. 用户点名已审核目的地并询问天气，但没有提供具体或相对出发日期时，必须先询问用户计划哪一天出发。
    日期确认前不得调用任何工具，不得使用今天、周末或其他默认日期，也不得追加询问交通方式或路线偏好。"""


SYSTEM_PROMPT += """
32. 用户明确选择自驾后，如果停车点工具返回停车点，应展示首选停车点名称、导航链接和停车说明，并提醒用户以现场管制为准。没有已审核停车点但工具返回 `trailhead_reference` 时，应先明确暂无已审核停车场信息，再展示徒步起点参考；必须明确说明该位置仅供参考、不代表可以停车，请以现场停车标识和交通管制为准。不得把徒步起点称为推荐停车场，也不得自行编造停车位置。
33. 用户已经选定具体路线并确认自驾后，工具必须严格串行调用：先调用 `estimate_route_weather`，天气成功返回后再调用 `find_route_parking_points`。不得先查停车点再查天气，也不得把两个工具并行调用。停车点有数据时展示名称、经纬度、非空停车说明和导航链接；无数据时按工具返回展示徒步起点参考及风险提示。不得凭模型知识补全。
34. 已选路线的天气和停车点查询均完成后，必须直接输出最终路线总结。总结至少包含“路线信息”“天气信息”“推荐停车场”三部分：路线信息包含名称、起终点、距离、爬升、预计徒步时长、难度、设施和风险；天气信息包含官方预警、温度、天气现象和来源；推荐停车场包含名称、经纬度、停车说明和导航链接。工具未返回的内容必须明确说明暂无数据，不得自行补全。
35. 出发时间必须严格晚于当前本地时间，这是所有路线推荐、天气和交通查询的硬约束。日期已经过去，
    或日期为今天但用户没有提供能够验证为未来的具体时刻时，必须停止工具调用，只确认新的未来出发时间；
    不得替用户顺延日期，不得使用默认出发时间，也不得同时询问其他偏好。
"""


def _json_result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _has_multiple_recommendations(tool_name: str, tool_result: str) -> bool:
    """Return whether a recommendation result requires an explicit user choice."""
    if tool_name != "recommend_hiking_routes":
        return False
    try:
        payload = json.loads(tool_result)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("count", 0) > 1


def _requests_user_input(content: str) -> bool:
    """Return whether assistant text asks the user to provide an answer."""
    normalized = content.strip()
    if not normalized:
        return False
    return "？" in normalized or "?" in normalized or any(
        marker in normalized
        for marker in ("请回复", "直接回复", "请选择", "请告诉我", "请确认")
    )


def _has_challenge_preference(content: str) -> bool:
    """判断用户是否明确希望选择较高难度，并排除常见否定表达。"""
    normalized = content.replace(" ", "")
    negative_markers = (
        "不要太难",
        "不想太难",
        "不能太难",
        "别太难",
        "不要难的",
        "不选难的",
    )
    if any(marker in normalized for marker in negative_markers):
        return False
    return any(
        marker in normalized
        for marker in ("难一些", "难一点", "挑战", "高难度", "难度较高")
    )


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def _message_name(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("name", ""))
    return str(getattr(message, "name", ""))


def _has_tool_result(messages: list[Any], tool_name: str) -> bool:
    for message in messages:
        if _message_role(message) != FUNCTION or _message_name(message) != tool_name:
            continue
        try:
            payload = json.loads(_message_content(message))
        except (TypeError, ValueError):
            return True
        if not isinstance(payload, dict) or payload.get("blocked") is not True:
            return True
    return False


def _has_explicit_route_selection(messages: list[Any]) -> bool:
    selection_markers = ("我选", "我选择", "就选", "决定走", "选第", "选择第", "就这条")
    for message in reversed(messages):
        if _message_role(message) != "user":
            continue
        content = _message_content(message).replace(" ", "")
        return any(marker in content for marker in selection_markers)
    return False


def _has_group_tour_selection_after_route(messages: list[Any]) -> bool:
    selection_markers = ("我选", "我选择", "就选", "决定走", "选第", "选择第", "就这条")
    has_route_selection = False
    for message in messages:
        if _message_role(message) != "user":
            continue
        content = _message_content(message).replace(" ", "")
        if any(marker in content for marker in selection_markers):
            has_route_selection = True
        if has_route_selection and any(label in content for label in ("报团", "抱团")):
            return True
    return False


@dataclass(frozen=True)
class ConversationState:
    """Structured route and transport selections derived from conversation history."""

    selected_route_id: str | None = None
    transport_mode: str | None = None
    has_current_route_choice: bool = False
    has_current_transport_choice: bool = False


TRANSPORT_LABELS = {
    "自驾": "self_drive",
    "报团": "group_tour",
    "抱团": "group_tour",
    "公共交通": "public_transit",
}

WEB_CHATBOT_CONFIG = {
    "input.upload.enabled": False,
    "input.audio.enabled": False,
    "user.avatar": str(
        Path(__file__).resolve().parents[1]
        / "qwen_agent"
        / "gui"
        / "assets"
        / "akita-user-avatar.png"
    ),
    "agent.avatar": str(
        Path(__file__).resolve().parents[1]
        / "qwen_agent"
        / "gui"
        / "assets"
        / "hiking-logo.png"
    ),
    "header.title": "成都山野徒步助手",
    "header.subtitle": "查路线、看天气、估交通、查商团活动，让每一次成都周边徒步都更从容。",
    "input.placeholder": "想去哪里徒步？告诉我时间、难度或风景偏好…",
}


def _match_transport_mode(content: str) -> str | None:
    matches = {
        mode for label, mode in TRANSPORT_LABELS.items() if label in content
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _numbered_option_segments(content: str) -> dict[int, str]:
    markers = list(re.finditer(r"(?<!\d)(\d+)\s*[.、．)）:：]\s*", content))
    options: dict[int, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        options[int(marker.group(1))] = content[marker.end():end].strip()
    return options


def _ordered_transport_modes(content: str) -> list[str]:
    positions: list[tuple[int, str]] = []
    seen_modes: set[str] = set()
    for label, mode in TRANSPORT_LABELS.items():
        position = content.find(label)
        if position < 0 or mode in seen_modes:
            continue
        seen_modes.add(mode)
        positions.append((position, mode))
    return [mode for _, mode in sorted(positions)]


def _ordered_route_ids(
    content: str, routes: list[dict[str, Any]]
) -> list[str]:
    positions: list[tuple[int, str]] = []
    for route in routes:
        terms = [route.get("name", ""), *(route.get("group_tour_search_terms") or [])]
        matched_positions = [
            content.find(str(term))
            for term in terms
            if str(term).strip() and content.find(str(term)) >= 0
        ]
        if matched_positions:
            positions.append((min(matched_positions), str(route["id"])))
    return [route_id for _, route_id in sorted(positions)]


def _match_route_id(content: str, routes: list[dict[str, Any]]) -> str | None:
    normalized_content = content.replace(" ", "")
    matches: list[tuple[int, str]] = []
    for route in routes:
        terms = [route.get("name", ""), *(route.get("group_tour_search_terms") or [])]
        matched_lengths = [
            len(str(term).replace(" ", ""))
            for term in terms
            if str(term).strip() and str(term).replace(" ", "") in normalized_content
        ]
        if matched_lengths:
            matches.append((max(matched_lengths), str(route["id"])))
    if not matches:
        return None
    matches.sort(reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][1]


def _matched_group_tour_search_terms(
    content: str,
    routes: list[dict[str, Any]],
) -> list[str]:
    """Return stored search terms mentioned by the user without matching route names."""
    normalized_content = content.replace(" ", "")
    terms = {
        str(term).strip()
        for route in routes
        for term in (route.get("group_tour_search_terms") or [])
        if str(term).strip() and str(term).replace(" ", "") in normalized_content
    }
    return sorted(terms, key=len, reverse=True)


def _extract_scenery_preferences(
    content: str,
    routes: list[dict[str, Any]],
) -> list[str]:
    """Extract reviewed scenery labels explicitly mentioned in user text."""
    normalized_content = content.replace("日出发", "日 出发")
    preferences = {
        str(scenery).strip()
        for route in routes
        for scenery in (route.get("scenery") or [])
        if str(scenery).strip() and str(scenery).strip() in normalized_content
    }
    return sorted(preferences, key=len, reverse=True)


def _remove_unfounded_invalid_counts(
    query: dict[str, Any],
    user_content: str,
) -> None:
    """Restore count defaults when invalid optional values were model-generated."""
    count_markers = {
        "party_size": r"-?\d+\s*个?\s*(?:人|位)",
        "vehicle_count": r"-?\d+\s*(?:辆|台)(?:车)?",
    }
    for field, pattern in count_markers.items():
        if field not in query:
            continue
        value = query[field]
        is_positive_integer = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        )
        if not is_positive_integer and re.search(pattern, user_content) is None:
            query.pop(field)


def _remove_unfounded_optional_constraints(
    query: dict[str, Any],
    user_content: str,
) -> None:
    """删除模型生成、但在用户原话中找不到依据的数值筛选条件。"""
    if not user_content.strip():
        return
    evidence_patterns = {
        "max_distance_km": (
            r"(?:距离|路程|徒步).{0,12}\d+(?:\.\d+)?\s*(?:公里|千米|km)"
            r"|\d+(?:\.\d+)?\s*(?:公里|千米|km).{0,8}(?:以内|内|以下|距离|路程)"
        ),
        "max_ascent_m": (
            r"(?:爬升|累计爬升).{0,12}\d+(?:\.\d+)?\s*(?:米|m)"
            r"|\d+(?:\.\d+)?\s*(?:米|m).{0,8}(?:爬升|累计爬升)"
        ),
        "max_budget_cny": (
            r"(?:预算|费用|花费).{0,12}\d+(?:\.\d+)?\s*(?:元|块|人民币)?"
            r"|\d+(?:\.\d+)?\s*(?:元|块|人民币).{0,8}(?:预算|以内|内|以下)"
        ),
        "max_one_way_minutes": (
            r"(?:单程|车程|交通时间).{0,12}\d+(?:\.\d+)?\s*(?:分钟|小时)"
            r"|\d+(?:\.\d+)?\s*(?:分钟|小时).{0,8}(?:单程|车程|交通)"
        ),
    }
    normalized_content = user_content.lower()
    for field, pattern in evidence_patterns.items():
        if field in query and re.search(pattern, normalized_content) is None:
            query.pop(field)


def _resolve_numbered_choice(
    content: str,
    previous_assistant_content: str,
    routes: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    selected = re.fullmatch(r"\s*(\d+)\s*", content)
    if selected is None:
        return None, None
    selected_number = int(selected.group(1))
    option = _numbered_option_segments(previous_assistant_content).get(
        selected_number, ""
    )
    route_id = _match_route_id(option, routes) if option else None
    transport_mode = _match_transport_mode(option) if option else None
    if route_id is None:
        ordered_route_ids = _ordered_route_ids(previous_assistant_content, routes)
        if 1 <= selected_number <= len(ordered_route_ids):
            route_id = ordered_route_ids[selected_number - 1]
    if transport_mode is None:
        ordered_transport_modes = _ordered_transport_modes(previous_assistant_content)
        if 1 <= selected_number <= len(ordered_transport_modes):
            transport_mode = ordered_transport_modes[selected_number - 1]
    return route_id, transport_mode


def build_conversation_state(
    messages: list[Any], routes: list[dict[str, Any]]
) -> ConversationState:
    """Resolve the latest selected route and current transport action."""
    selected_route_id: str | None = None
    transport_mode: str | None = None
    has_current_route_choice = False
    has_current_transport_choice = False
    previous_assistant_content = ""
    user_indexes = [
        index for index, message in enumerate(messages) if _message_role(message) == "user"
    ]
    last_user_index = user_indexes[-1] if user_indexes else -1

    for index, message in enumerate(messages):
        role = _message_role(message)
        content = _message_content(message)
        if role == "assistant":
            if selected_route_id is None and any(
                marker in content for marker in ("已确认选择", "已选路线", "路线：")
            ):
                selected_route_id = _match_route_id(content, routes)
            previous_assistant_content = content
            continue
        if role != "user":
            continue

        numbered_route_id, numbered_transport = _resolve_numbered_choice(
            content, previous_assistant_content, routes
        )
        mentioned_route_id = _match_route_id(content, routes)
        new_route_id = numbered_route_id or mentioned_route_id
        is_explicit_route_choice = numbered_route_id is not None or (
            mentioned_route_id is not None
            and any(
                marker in content.replace(" ", "")
                for marker in ("我选", "我选择", "就选", "决定走", "选第", "选择第", "就这条", "改成", "换成")
            )
        )
        if new_route_id is not None and new_route_id != selected_route_id:
            selected_route_id = new_route_id
            transport_mode = None

        mentioned_transport = _match_transport_mode(content)
        new_transport = numbered_transport or mentioned_transport
        if new_transport is not None:
            transport_mode = new_transport

        if index == last_user_index:
            has_current_route_choice = is_explicit_route_choice
            has_current_transport_choice = new_transport is not None

    return ConversationState(
        selected_route_id=selected_route_id,
        transport_mode=transport_mode,
        has_current_route_choice=has_current_route_choice,
        has_current_transport_choice=has_current_transport_choice,
    )


def trim_completed_trip_context(
    messages: list[Any],
    routes: list[dict[str, Any]],
) -> list[Any]:
    """Start a fresh task at the first user message after a completed selection."""
    user_indexes = [
        index for index, message in enumerate(messages)
        if _message_role(message) == "user"
    ]
    reset_user_index: int | None = None
    for position, user_index in enumerate(user_indexes[:-1]):
        state = build_conversation_state(messages[:user_index + 1], routes)
        if state.selected_route_id is not None and state.has_current_transport_choice:
            reset_user_index = user_indexes[position + 1]
    if reset_user_index is None:
        return messages
    system_messages = [
        message for message in messages[:reset_user_index]
        if _message_role(message) == SYSTEM
    ]
    return [*system_messages, *messages[reset_user_index:]]


def _build_selected_route_context(
    routes: list[dict[str, Any]],
    route_id: str,
) -> str:
    """Build a compact, reviewed route snapshot for the final trip summary."""
    route = next(
        (item for item in routes if str(item.get("id")) == route_id),
        None,
    )
    if route is None:
        return "暂无已审核路线详情"
    fields = (
        "id", "name", "start_location", "end_location", "distance_km",
        "ascent_m", "highest_altitude_m", "hiking_minutes", "difficulty",
        "route_type", "has_toilet", "has_supply_shop", "risks",
    )
    return _json_result({field: route.get(field) for field in fields})


def build_route_search_terms(routes: list[dict[str, Any]]) -> list[str]:
    """Return unique user-facing terms for matching reviewed route destinations."""
    terms: list[str] = []
    seen: set[str] = set()
    for route in routes:
        candidates = [
            route.get("name", ""),
            *(route.get("group_tour_search_terms") or []),
        ]
        for candidate in candidates:
            term = str(candidate).strip()
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _find_named_route_terms(
    messages: list[Any], route_search_terms: list[str]
) -> list[str]:
    user_content = " ".join(
        _message_content(message).replace(" ", "")
        for message in messages
        if _message_role(message) == "user"
    )
    return [term for term in route_search_terms if term.replace(" ", "") in user_content]


def build_departure_date_guidance(current_date: date | None = None) -> str:
    """Build current-date context for interpreting departure dates."""
    today = current_date or datetime.now().astimezone().date()
    day_after_tomorrow = date.fromordinal(today.toordinal() + 2)
    return (
        f"当前日期是 {today.isoformat()}（{WEEKDAY_NAMES[today.weekday()]}），当前年度是 {today.year}。"
        f"后天是 {day_after_tomorrow.isoformat()}（{WEEKDAY_NAMES[day_after_tomorrow.weekday()]}）。"
        f"用户提供月日但没有明确年份时，一律理解为当前年度；"
        f"例如用户说“6.15 号出发”，应理解为 {today.year}-06-15。"
        "出发时间通常应晚于当前时间；如果按当前年度理解后日期已过，应向用户确认，"
        "不要自行推断为下一年度。用户明确提供年份时，以用户提供的年份为准。"
    )


def build_public_holiday_guidance() -> str:
    """Build a concise audited holiday calendar summary for model grounding."""
    lines = [
        "以下为本地已收录的中国大陆全国性节假日摘要，仅用于防止凭记忆编造日期；"
        "涉及节假日判断时仍必须优先调用节假日查询工具。",
        "不得输出未由节假日工具或本摘要支持的具体节假日日期。",
    ]
    for year in sorted(HOLIDAY_CALENDARS):
        for item in HOLIDAY_CALENDARS[year]:
            festival = date.fromisoformat(item["festival_date"])
            start = date.fromisoformat(item["start_date"])
            end = date.fromisoformat(item["end_date"])
            lines.append(
                f"{year} {item['name']}：节日当天 {item['festival_date']}"
                f"（{WEEKDAY_NAMES[festival.weekday()]}），假期 {item['start_date']}"
                f"（{WEEKDAY_NAMES[start.weekday()]}）至 {item['end_date']}"
                f"（{WEEKDAY_NAMES[end.weekday()]}）。"
            )
    return "\n".join(lines)


def _extract_departure_clock(content: str) -> clock_time | None:
    """从用户文本提取可明确判断先后的 24 小时或中文时刻。"""
    colon_match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", content)
    if colon_match:
        return clock_time(int(colon_match.group(1)), int(colon_match.group(2)))

    chinese_match = re.search(
        r"(上午|早上|下午|晚上)(\d{1,2})点(?:(半)|(\d{1,2})分?)?",
        content,
    )
    if not chinese_match:
        return None
    period, hour_text, half, minute_text = chinese_match.groups()
    hour = int(hour_text)
    if not 1 <= hour <= 12:
        return None
    if period in ("下午", "晚上") and hour < 12:
        hour += 12
    if period in ("上午", "早上") and hour == 12:
        hour = 0
    minute = 30 if half else int(minute_text or 0)
    if minute > 59:
        return None
    return clock_time(hour, minute)


def _build_non_future_departure_guidance(
    content: str, current_datetime: datetime
) -> str | None:
    """若用户时间无法满足严格未来约束，返回阻断后续工具的确认策略。"""
    current_date = current_datetime.date()
    selected_expression: str | None = None
    selected_date: date | None = None

    iso_datetime_match = re.search(
        r"\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?",
        content,
    )
    if iso_datetime_match:
        selected_expression = iso_datetime_match.group(0)
        parsed_datetime = datetime.fromisoformat(selected_expression.replace("Z", "+00:00"))
        if parsed_datetime.tzinfo is None and current_datetime.tzinfo is not None:
            parsed_datetime = parsed_datetime.replace(tzinfo=current_datetime.tzinfo)
        if parsed_datetime > current_datetime:
            return None
        selected_date = parsed_datetime.date()
    else:
        relative_matches = re.findall(
            r"本周末|下周末|[本下]?周[一二三四五六日天]|今天|明天|后天",
            content,
        )
        unique_relative = list(dict.fromkeys(relative_matches))
        if len(unique_relative) == 1:
            selected_expression = unique_relative[0]
            candidates = resolve_departure_date(
                selected_expression, current_date
            )["candidates"]
            if len(candidates) == 1:
                selected_date = date.fromisoformat(candidates[0]["date"])

        if selected_date is None:
            iso_date_match = re.search(r"\d{4}-\d{1,2}-\d{1,2}", content)
            chinese_date_match = re.search(r"(\d{1,2})月(\d{1,2})[日号]", content)
            if iso_date_match:
                selected_expression = iso_date_match.group(0)
                selected_date = date.fromisoformat(selected_expression)
            elif chinese_date_match:
                selected_expression = chinese_date_match.group(0)
                selected_date = date(
                    current_date.year,
                    int(chinese_date_match.group(1)),
                    int(chinese_date_match.group(2)),
                )

        if selected_date is None or selected_date > current_date:
            return None
        if selected_date == current_date:
            selected_clock = _extract_departure_clock(content)
            if selected_clock is not None:
                selected_datetime = datetime.combine(
                    selected_date, selected_clock, tzinfo=current_datetime.tzinfo
                )
                if selected_datetime > current_datetime:
                    return None

    return (
        f"用户填写的出发时间“{selected_expression}”不满足未来出行硬约束，时间设置可能有问题。"
        "出发时间必须严格晚于当前时间。本轮只确认新的未来出发时间，且每轮只问一个问题。"
        "明确提醒用户检查日期或时刻，并询问计划改为哪一天、几点出发。"
        "确认有效未来时间前不得调用任何工具，不得推荐路线，不得查询天气或交通，"
        "也不得询问体力、路线偏好或交通方式。"
    )


def build_interview_guidance(
    messages: list[Any],
    route_search_terms: list[str] | None = None,
    routes: list[dict[str, Any]] | None = None,
    current_datetime: datetime | None = None,
) -> str:
    """Build turn-aware guidance for a natural hiking requirement interview."""
    user_turns = sum(_message_role(message) == "user" for message in messages)
    state = build_conversation_state(messages, routes or [])
    latest_user_content = next(
        (
            _message_content(message)
            for message in reversed(messages)
            if _message_role(message) == "user"
        ),
        "",
    )
    user_content = " ".join(
        _message_content(message)
        for message in messages
        if _message_role(message) == "user"
    )
    if current_datetime is not None:
        non_future_guidance = _build_non_future_departure_guidance(
            latest_user_content, current_datetime
        )
        if non_future_guidance is not None:
            return non_future_guidance
    matched_route_id = _match_route_id(latest_user_content, routes or [])
    matched_destination_terms = _matched_group_tour_search_terms(
        latest_user_content,
        routes or [],
    )
    scenery_preferences = _extract_scenery_preferences(
        user_content,
        routes or [],
    )
    has_relative_date = re.search(
        r"本周末|下周末|[本下]?周[一二三四五六日天]|今天|明天|后天",
        user_content,
    ) is not None
    has_explicit_date = has_relative_date or re.search(
        r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[日号]",
        user_content,
    ) is not None
    has_weather_request = "天气" in latest_user_content
    has_group_tour_request = any(
        expression in latest_user_content for expression in ("报团", "抱团")
    )
    if (
        (matched_route_id is not None or matched_destination_terms)
        and has_weather_request
        and not has_explicit_date
    ):
        return (
            "用户点名了已审核目的地并询问天气，但没有提供具体或相对出发日期。"
            "本轮只询问用户计划哪一天出发，例如：‘你计划哪一天去巴朗山？’"
            "在用户确认具体出发日期前，不得调用任何工具，不得查询或概括天气，"
            "不得使用默认日期，也不得询问交通方式、体力、经验或其他路线偏好。"
        )
    if (
        matched_route_id is not None
        and has_relative_date
        and has_weather_request
        and has_group_tour_request
    ):
        destination_name = (
            matched_destination_terms[0]
            if matched_destination_terms
            else "用户原话中的目的地"
        )
        return (
            "用户在一句话中同时提供了相对日期、已审核目的地、报团方式和天气查询需求。"
            "必须从用户原话提炼自然语言目的地名称，并通过推荐工具匹配路线，不能把目的地名称当作 route_id。"
            f"本次提炼 destination_name={destination_name}。必须严格串行执行，不能并行调用："
            "第一步只调用 resolve_departure_date 解析用户的相对日期；成功后，第二步把其返回的具体日期"
            "传给 resolve_public_holiday；成功后，第三步调用 recommend_hiking_routes，并传入上述 destination_name，"
            "从推荐结果中取得唯一的准确 route_id；第四步只能使用该推荐结果的 route_id 调用 estimate_route_weather；"
            "最后使用同一个 route_id 调用 find_group_tour_links。不得跳过路线推荐。每一步必须等待上一步工具结果。"
            "任一步失败都要停止依赖该结果的后续调用，不得自行推算日期、星期或日期类型，"
            "也不得把自然语言目的地名称当作 route_id。全部成功后再统一回答天气和报团链接。"
        )
    has_recommendation_request = "推荐" in user_content
    if has_explicit_date and scenery_preferences and has_recommendation_request:
        scenery_text = "、".join(scenery_preferences)
        return (
            f"用户已经提供出发日期和明确风景偏好（风景偏好：{scenery_text}），并要求推荐路线，"
            "现有信息已经足够。不得再询问体力、距离、爬升或难度，也不得要求用户确认是否使用默认值。"
            "如果日期是相对日期，先调用 resolve_departure_date；取得具体日期后调用 resolve_public_holiday；"
            "随后直接调用 recommend_hiking_routes，并传入 scenery_preferences。未提供的筛选条件使用系统默认值。"
            "推荐出多条路线后只展示候选并请用户选择，不得替用户选择。"
        )
    is_beginner_request = any(
        marker in user_content for marker in ("新手", "入门", "第一次徒步")
    )
    if has_explicit_date and is_beginner_request and has_recommendation_request:
        return (
            "用户已经提供出发日期，并明确要求推荐适合新手的路线，现有信息已经足够。"
            "不得再询问强度、经验、距离、爬升或难度，也不得要求用户选择轻松、适中或挑战。"
            "如果日期是相对日期，先调用 resolve_departure_date；取得具体日期后调用 resolve_public_holiday；"
            "随后直接调用 recommend_hiking_routes，并使用 max_difficulty=easy。"
            "未提供的其他条件使用系统默认值。推荐出多条路线后只展示候选并请用户选择。"
        )
    if (
        has_explicit_date
        and _has_challenge_preference(user_content)
        and has_recommendation_request
    ):
        return (
            "用户已经提供出发日期、明确挑战偏好并要求推荐路线，现有信息已经足够。"
            "不得再询问强度、体力、经验、距离、爬升或难度，也不得要求用户重复选择适中或挑战。"
            "如果日期是相对日期，先调用 resolve_departure_date；取得具体日期后调用 resolve_public_holiday；"
            "随后直接调用 recommend_hiking_routes，并使用 max_difficulty=hard。"
            "未提供的其他筛选条件使用系统默认值。推荐出多条路线后只展示候选并请用户选择。"
        )
    if state.transport_mode == "public_transit" and state.has_current_transport_choice:
        return (
            "用户当前选择了公共交通，但该出行方式暂未开放。请简短说明暂不提供公共交通方案，"
            "并只请用户重新选择：\n"
            "1. 自驾\n"
            "2. 报团\n\n"
            "直接回复 1 或 2 即可。不得查询、推荐或整合公共交通信息。"
        )
    if (
        routes is not None
        and state.transport_mode == "group_tour"
        and state.has_current_transport_choice
    ):
        if state.selected_route_id is None:
            return (
                "用户当前选择了报团，但尚未确定具体路线。不得调用 find_group_tour_links，"
                "也不得猜测 route_id；只请用户先选定一条路线。"
            )
        return (
            "用户已经选定路线并明确选择报团。请立即调用 find_group_tour_links，"
            f"使用结构化会话状态给出的 route_id={state.selected_route_id} 实时查询。"
            "不得改用其他路线 ID，也不得再次向用户确认路线、日期、交通方式或是否开始查询。"
            "只展示商团名称、活动标题和链接，并提示用户"
            "进入对应商团网站核实及完成后续操作；不得推断价格、团期或余位。"
        )
    if (
        routes is not None
        and state.transport_mode == "group_tour"
        and not state.has_current_transport_choice
    ):
        return (
            "会话中保留了此前的报团方式，但用户当前轮没有重新选择报团。"
            "本轮不得调用 find_group_tour_links；应根据用户当前问题正常回答，"
            "不得把历史报团选择误当成新的在线查询指令。"
        )
    if (
        routes is not None
        and state.selected_route_id is not None
        and state.transport_mode == "self_drive"
        and state.has_current_transport_choice
    ):
        route_id = state.selected_route_id
        route_context = _build_selected_route_context(routes, route_id)
        cost_guidance = (
            "用户已经选择自驾。routes.cost_min_cny 和 routes.cost_max_cny 是预计报团费用区间，"
            "自驾方案不得展示这两个字段对应的费用，不得展示“路线费用”，不得展示“预计总费用”。"
            "若工具结果表明油费自理且无额外交通费用，只写“自驾交通费：油费自理，无额外交通费用”。"
        )
        if not _has_tool_result(messages, "estimate_route_weather"):
            return (
                "用户已经选定路线并在当前轮明确确认自驾，"
                f"准确 route_id={route_id}。用户已经明确选择自驾，不得重复询问交通方式。"
                "检查对话中已解析的具体出发日期；日期存在时必须先调用 estimate_route_weather，"
                "并使用上述 route_id 和具体日期。天气返回后再调用 "
                "find_route_parking_points 查询同一路线的已审核停车点。"
                "两个工具必须串行调用，不得并行，不得用泛化天气提醒代替工具查询；"
                "若尚无具体日期，只确认日期，不得猜测。停车点返回后直接输出路线总结。"
                f"最终总结使用以下已审核路线信息，不得自行补全：{route_context}。"
                f"{cost_guidance}"
            )
        if not _has_tool_result(messages, "find_route_parking_points"):
            return (
                "用户已经选定路线、确认自驾且天气查询已经完成，"
                f"准确 route_id={route_id}。立即调用 find_route_parking_points 查询该路线已审核停车点。"
                "不得把徒步起点冒充停车点，不得重复查询天气，也不得再次询问路线、日期或交通方式。"
                "停车点返回后直接输出路线总结；即使停车点数量为零，也应进入总结，明确暂无已审核停车场信息，"
                "并在工具提供 trailhead_reference 时将其作为徒步起点参考展示，强调不代表可以停车。"
                f"最终总结使用以下已审核路线信息，不得自行补全：{route_context}。"
                f"{cost_guidance}"
            )
        return (
            "已选路线的天气和停车点查询均已完成。不要继续调用工具，不要再次询问路线、日期或交通方式，"
            "直接输出最终路线总结，并严格包含以下部分："
            "路线信息（名称、起终点、距离、爬升、预计徒步时长、难度、设施与风险）；"
            "天气信息（官方预警、温度、天气现象与来源）；"
            "推荐停车场（名称、经纬度、停车说明与导航链接）。"
            "停车点结果为空时明确写暂无已审核停车场信息；若工具返回 trailhead_reference，"
            "另行展示为徒步起点参考并强调仅供参考、不代表可以停车。任何工具未返回的信息都说明暂无数据，不得凭模型知识补全。"
            f"路线部分只能使用以下已审核路线信息：{route_context}。"
            f"{cost_guidance}"
        )
    if routes is not None and state.transport_mode == "self_drive":
        cost_guidance = (
            "用户已经选择自驾。routes.cost_min_cny 和 routes.cost_max_cny 是预计报团费用区间，"
            "自驾方案不得展示这两个字段对应的费用，不得展示“路线费用”，不得展示“预计总费用”。"
            "若工具结果表明油费自理且无额外交通费用，只写“自驾交通费：油费自理，无额外交通费用”。"
        )
        if (
            state.selected_route_id is not None
            and not _has_tool_result(messages, "estimate_route_weather")
        ):
            return (
                f"用户已经选定路线并确认自驾，准确 route_id={state.selected_route_id}。"
                "用户已经明确选择自驾，不得重复询问交通方式。"
                "检查对话中已解析的具体出发日期；日期存在时必须先调用 estimate_route_weather，"
                "并使用上述 route_id 和具体日期。不得用泛化天气提醒代替工具查询；"
                "若尚无具体日期，只确认日期，不得猜测。天气工具成功返回后再输出最终方案。"
                f"{cost_guidance}"
            )
        return cost_guidance
    if routes is None and _has_group_tour_selection_after_route(messages):
        return (
            "用户已经选定路线并明确选择报团。请立即调用 find_group_tour_links，"
            "使用已选路线的 route_id 实时查询。不得再次向用户确认。"
            "只展示商团名称、活动标题和链接，并提示用户"
            "进入对应商团网站核实及完成后续操作；不得推断价格、团期或余位。"
        )
    if state.has_current_route_choice or (routes is None and _has_explicit_route_selection(messages)):
        if (
            routes is not None
            and state.selected_route_id is not None
            and not _has_tool_result(messages, "estimate_route_weather")
        ):
            if state.transport_mode is None:
                transport_followup = (
                    "用户尚未明确出行方式。天气返回后先展示天气，再询问交通方式，"
                    "并严格输出以下内容，不得增删：\n"
                    "请选择交通方式：\n"
                    "1. 自驾\n"
                    "2. 报团\n\n"
                    "直接回复 1 或 2 即可。不得替用户选择。"
                )
            else:
                transport_name = (
                    "自驾" if state.transport_mode == "self_drive" else "报团"
                )
                transport_followup = (
                    f"用户已经明确选择{transport_name}。天气返回后沿用该出行方式，"
                    "不得重复询问交通方式。"
                )
            return (
                "用户已经明确选定路线，"
                f"准确 route_id={state.selected_route_id}。检查对话中已解析的具体出发日期；"
                "日期存在时立即调用 estimate_route_weather，使用上述 route_id 和具体日期，"
                "不得等待用户先选择交通方式，也不得用泛化天气提醒代替查询。"
                f"{transport_followup}"
                "若尚无具体日期，只确认日期，不得猜测。"
            )
        return (
            "用户已经明确选定路线且天气查询已经完成。下一步只确认交通方式。"
            "本轮不得给问题本身编号，不得形成嵌套编号；"
            "不得追加路线对比或任何第二个问题；不得增加“其他”选项；"
            "不得使用图标、装饰标题或括号说明。请严格输出以下内容，不得增删：\n"
            "请选择交通方式：\n"
            "1. 自驾\n"
            "2. 报团\n\n"
            "直接回复 1 或 2 即可。"
        )
    named_route_terms = _find_named_route_terms(messages, route_search_terms or [])
    if named_route_terms:
        matched_terms = "、".join(named_route_terms)
        route_id = _match_route_id(
            " ".join(
                _message_content(message)
                for message in messages
                if _message_role(message) == "user"
            ),
            routes or [],
        )
        route_reference = (
            f"已匹配的准确 route_id={route_id}。"
            if route_id is not None
            else "尚未得到唯一的路线 ID，不得猜测 route_id。"
        )
        return (
            f"用户点名的目的地已命中已审核路线（匹配词：{matched_terms}）。"
            f"{route_reference}"
            "该目的地已经足以限定候选路线，不再执行通用的偏好访谈。"
            "若尚未确定具体出发日期，只确认具体出发日期；不得询问体力、经验、人数、距离、爬升、难度、风景、设施或最晚返回时间。"
            "日期确定后立即推荐命中的路线：先按具体日期调用节假日查询工具，再调用推荐及天气等所需工具；"
            "不得继续追问普通筛选条件，也不得转而推荐其他未点名路线。"
        )
    if user_turns <= 2:
        return (
            f"当前是第 {user_turns} 个用户轮次，处于探索阶段。"
            "先接住用户表达的兴趣或顾虑，再一次只问一个容易回答的问题。"
            "前期先确认具体出发时间；时间明确后，再一次询问一个最能缩小范围的路线偏好。"
            "路线偏好可以是体力或经验、距离、爬升、难度、风景或设施。"
            "候选路线形成前不要询问交通方式，也不要展示交通方式选项。"
        )
    if user_turns == 3:
        return (
            "当前处于收敛阶段。简短总结已知偏好，只确认一个仍会显著影响路线筛选结果的问题。"
            "如果具体出发时间仍未明确，先补问出发时间；否则继续收敛路线偏好。"
            "前期不要询问交通方式。如果信息已经足够，先给出候选路线并让用户选择一条，"
            "这一轮不得询问交通方式。"
        )
    return (
        f"当前已交流 {user_turns} 个用户轮次，处于推荐阶段。"
        "若缺少具体出发时间，先补问时间；否则根据已有路线偏好形成候选路线，"
        "调用推荐工具时可以暂不提供交通方式。给出候选路线后，先让用户明确选择一条路线，"
        "这一轮不得询问交通方式，也不得展示交通方式选项。只有用户明确选定路线后，"
        "下一轮才确认自驾、报团或公共交通。不要继续机械追问。"
    )


class GuidedHikingAssistant(Assistant):
    """Qwen Assistant with turn-aware hiking interview guidance."""

    def _required_self_drive_tool(self, messages: list[Any]) -> str | None:
        """Return the next mandatory tool for a confirmed self-drive trip."""
        state = build_conversation_state(
            messages,
            getattr(self, "route_catalog", []),
        )
        if state.selected_route_id is None or state.transport_mode != "self_drive":
            return None
        if not _has_tool_result(messages, "estimate_route_weather"):
            return "estimate_route_weather"
        if not _has_tool_result(messages, "find_route_parking_points"):
            return "find_route_parking_points"
        return None

    def _run_one_tool_at_a_time(
        self,
        messages: list[Any],
        lang: str,
        **kwargs: Any,
    ) -> Iterator[list[Any]]:
        """Execute at most one model-generated tool call before asking the model again."""
        response: list[Any] = []
        remaining_calls = QWEN_MAX_LLM_CALLS
        self._last_model_call_count = 0
        self._last_tool_call_count = 0
        is_waiting_for_route_choice = False
        while remaining_calls > 0:
            remaining_calls -= 1
            self._last_model_call_count += 1
            extra_generate_cfg: dict[str, Any] = {"lang": lang}
            if kwargs.get("seed") is not None:
                extra_generate_cfg["seed"] = kwargs["seed"]
            output: list[Any] = []
            has_requested_user_input_in_stream = False
            pending_user_input_output: list[Any] = []
            for streamed_output in self._call_llm(
                messages=messages,
                functions=[tool.function for tool in self.function_map.values()],
                extra_generate_cfg=extra_generate_cfg,
            ):
                output = streamed_output
                streamed_visible_output: list[Any] = []
                has_streamed_tool = False
                is_streamed_requesting_user_input = any(
                    not self._detect_tool(item)[0]
                    and _requests_user_input(_message_content(item))
                    for item in streamed_output
                )
                if is_streamed_requesting_user_input:
                    has_requested_user_input_in_stream = True
                    pending_user_input_output = [
                        item
                        for item in streamed_output
                        if not self._detect_tool(item)[0]
                    ]
                for item in streamed_output:
                    use_tool, _, _, _ = self._detect_tool(item)
                    if use_tool:
                        if (
                            is_waiting_for_route_choice
                            or has_requested_user_input_in_stream
                        ):
                            continue
                        if has_streamed_tool:
                            continue
                        has_streamed_tool = True
                    streamed_visible_output.append(item)
                if streamed_visible_output:
                    yield response + streamed_visible_output
            if not output:
                break

            first_tool: tuple[Any, str, str] | None = None
            visible_output: list[Any] = []
            is_requesting_user_input = any(
                not self._detect_tool(item)[0]
                and _requests_user_input(_message_content(item))
                for item in output
            ) or has_requested_user_input_in_stream
            for item in output:
                use_tool, tool_name, tool_args, _ = self._detect_tool(item)
                if use_tool:
                    if is_waiting_for_route_choice or is_requesting_user_input:
                        continue
                    if first_tool is None:
                        first_tool = (item, tool_name, tool_args)
                        visible_output.append(item)
                    continue
                visible_output.append(item)

            if is_requesting_user_input and not visible_output:
                visible_output = pending_user_input_output

            response.extend(visible_output)
            messages.extend(visible_output)
            yield response
            if is_waiting_for_route_choice or is_requesting_user_input:
                break
            if first_tool is None:
                required_tool = self._required_self_drive_tool(messages)
                if required_tool is None:
                    break
                messages.append(Message(
                    role=SYSTEM,
                    content=(
                        f"当前自驾行程尚未完成。不要输出‘请稍等’或承诺稍后查询；"
                        f"现在必须立即调用 {required_tool}。"
                    ),
                ))
                continue

            tool_message, tool_name, tool_args = first_tool
            if (
                tool_name == "find_route_parking_points"
                and not _has_tool_result(messages, "estimate_route_weather")
            ):
                tool_result = _json_result({
                    "blocked": True,
                    "error": "停车点查询依赖天气结果，必须先查询天气",
                    "required_next_tool": "estimate_route_weather",
                })
            else:
                tool_result = self._call_tool(
                    tool_name,
                    tool_args,
                    messages=messages,
                    **kwargs,
                )
                self._last_tool_call_count += 1
            function_message = Message(
                role=FUNCTION,
                name=tool_name,
                content=tool_result,
                extra={"function_id": (tool_message.extra or {}).get("function_id", "1")},
            )
            messages.append(function_message)
            response.append(function_message)
            yield response
            is_waiting_for_route_choice = _has_multiple_recommendations(
                tool_name,
                tool_result,
            )

        yield response

    def _run(self, messages: list[Any], **kwargs: Any) -> Iterator[list[Any]]:
        call_id = uuid.uuid4().hex[:12]
        started_at = time.perf_counter()
        user_turns = sum(_message_role(message) == "user" for message in messages)
        last_user_chars = 0
        for message in reversed(messages):
            if _message_role(message) == "user":
                last_user_chars = len(_message_content(message))
                break
        model = str(getattr(getattr(self, "llm", None), "model", "unknown"))
        output_batches = 0
        logger.info(
            "Qwen Agent 对话调用开始 call_id=%s model=%s message_count=%s "
            "user_turns=%s last_user_chars=%s",
            call_id,
            model,
            len(messages),
            user_turns,
            last_user_chars,
        )
        try:
            guided_messages = deepcopy(messages)
            guided_messages = trim_completed_trip_context(
                guided_messages,
                getattr(self, "route_catalog", []),
            )
            current_datetime_provider = getattr(
                self, "current_datetime_provider", None
            )
            current_datetime = (
                current_datetime_provider()
                if callable(current_datetime_provider)
                else datetime.now().astimezone()
            )
            guidance = build_interview_guidance(
                guided_messages,
                getattr(self, "route_search_terms", []),
                getattr(self, "route_catalog", []),
                current_datetime=current_datetime,
            )
            if "时间设置可能有问题" in guidance:
                invalid_time_match = re.search(
                    r"出发时间“([^”]+)”", guidance
                )
                invalid_time = (
                    invalid_time_match.group(1)
                    if invalid_time_match is not None
                    else "该时间"
                )
                output_batches += 1
                yield [Message(
                    role=ASSISTANT,
                    name=self.name,
                    content=(
                        f"你填写的出发时间“{invalid_time}”有问题：“{invalid_time}”"
                        "对应的时间早于或等于当前时间。"
                        "出发时间必须晚于当前时间，请确认一下新的出发日期和时间。"
                    ),
                )]
                return
            if guided_messages and _message_role(guided_messages[0]) == SYSTEM:
                guided_messages[0].content = (
                    f"{guided_messages[0].content}\n\n# 当前对话策略\n{guidance}"
                )
            if not hasattr(self, "mem"):
                for response in super()._run(messages=guided_messages, **kwargs):
                    output_batches += 1
                    yield response
            else:
                lang = str(kwargs.pop("lang", "zh"))
                guided_messages = self._prepend_knowledge_prompt(
                    messages=guided_messages,
                    lang=lang,
                    **kwargs,
                )
                for response in self._run_one_tool_at_a_time(
                    messages=guided_messages,
                    lang=lang,
                    **kwargs,
                ):
                    output_batches += 1
                    yield response
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            exception_code = getattr(exc, "code", None) or "n/a"
            exception_message = getattr(exc, "message", None) or str(exc) or repr(exc)
            logger.exception(
                "Qwen Agent 对话调用失败 call_id=%s model=%s message_count=%s "
                "user_turns=%s last_user_chars=%s output_batches=%s model_calls=%s "
                "tool_calls=%s elapsed_ms=%s "
                "exception_type=%s exception_code=%s exception_message=%s",
                call_id,
                model,
                len(messages),
                user_turns,
                last_user_chars,
                output_batches,
                getattr(self, "_last_model_call_count", 0),
                getattr(self, "_last_tool_call_count", 0),
                elapsed_ms,
                type(exc).__name__,
                exception_code,
                exception_message,
            )
            raise
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Qwen Agent 对话调用完成 call_id=%s model=%s message_count=%s "
            "user_turns=%s last_user_chars=%s output_batches=%s model_calls=%s "
            "tool_calls=%s elapsed_ms=%s",
            call_id,
            model,
            len(messages),
            user_turns,
            last_user_chars,
            output_batches,
            getattr(self, "_last_model_call_count", 0),
            getattr(self, "_last_tool_call_count", 0),
            elapsed_ms,
        )


class HikingTool(BaseTool):
    service: ChatBIService

    def __init__(self, service: ChatBIService):
        self.service = service
        super().__init__()

    def verify_params(self, params: str | dict[str, Any]) -> dict[str, Any]:
        """Validate tool arguments and expose clear Chinese errors."""
        try:
            return self._verify_json_format_args(params)
        except ValueError as exc:
            message = str(exc)
            if message.startswith("Parameters ") and message.endswith(" is required!"):
                field = message.removeprefix("Parameters ").removesuffix(" is required!")
                raise ValueError(f"缺少 {field}") from exc
            raise ValueError(f"工具参数无效: {message}") from exc


class ListHikingRoutesTool(HikingTool):
    name = "list_hiking_routes"
    description = "查询当前所有已审核徒步路线，包括设施、风险、支持的交通方式和费用明细。"
    parameters: list[dict[str, Any]] = []

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        self.verify_params(params)
        routes = [
            {
                key: route.get(key)
                for key in (
                    "id", "name", "distance_km", "ascent_m", "highest_altitude_m",
                    "hiking_minutes", "difficulty", "duration_days", "scenery", "risks",
                    "transport_modes", "has_toilet", "has_supply_shop",
                )
            }
            for route in self.service.routes()
        ]
        return _json_result({"count": len(routes), "items": routes})


class RecommendHikingRoutesTool(HikingTool):
    name = "recommend_hiking_routes"
    description = (
        "访谈信息足够或用户要求立即推荐时，根据出发时间、预算、体力和偏好推荐徒步路线。"
        "形成候选路线时交通方式可暂不提供，候选形成后再用于交通和费用比较。"
    )
    parameters = [
        {
            "name": "route_id",
            "type": "string",
            "description": "路线目录匹配成功后的唯一标识；不得填写自然语言目的地",
        },
        {
            "name": "destination_name",
            "type": "string",
            "description": "从用户原话提炼的明确目的地名称，例如从“去爬巴朗山”提炼“巴朗山”",
        },
        {
            "name": "departure_at",
            "type": "string",
            "description": "出发时间，必须是带日期的 ISO 8601 时间，例如 2026-06-13T06:30:00+08:00",
            "required": True,
        },
        {"name": "origin", "type": "string", "description": "出发地，默认成都"},
        {
            "name": "transport_modes",
            "type": "array",
            "items": {"type": "string"},
            "description": "交通方式，当前仅可选 self_drive、group_tour；公共交通暂未开放",
        },
        {"name": "party_size", "type": "integer", "description": "出行人数"},
        {"name": "vehicle_count", "type": "integer", "description": "车辆数"},
        {"name": "max_distance_km", "type": "number", "description": "最大徒步距离，公里"},
        {"name": "max_ascent_m", "type": "integer", "description": "最大累计爬升，米"},
        {"name": "max_budget_cny", "type": "number", "description": "最高总预算，人民币"},
        {"name": "max_one_way_minutes", "type": "integer", "description": "最长单程交通时间，分钟"},
        {"name": "max_duration_days", "type": "integer", "description": "最大行程天数"},
        {
            "name": "max_difficulty",
            "type": "string",
            "description": "最高难度，可选 easy、moderate、hard、expert",
        },
        {
            "name": "latest_return_at",
            "type": "string",
            "description": "最晚返回时间，ISO 8601 时间",
        },
        {
            "name": "traffic_tolerance",
            "type": "string",
            "description": "最高拥堵容忍度，可选 low、medium、high、severe",
        },
        {
            "name": "scenery_preferences",
            "type": "array",
            "items": {"type": "string"},
            "description": "风景偏好，例如森林、雪山、湖泊、草甸",
        },
        {"name": "is_holiday", "type": "boolean", "description": "是否为节假日"},
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        if "public_transit" in query.get("transport_modes", []):
            raise ValueError("公共交通出行方式暂未开放，请选择自驾或报团")
        routes = self.service.routes()
        known_ids = {str(route["id"]) for route in routes}
        latest_user_content = next(
            (
                _message_content(message)
                for message in reversed(kwargs.get("messages", []))
                if _message_role(message) == "user"
            ),
            "",
        )
        user_content = " ".join(
            _message_content(message)
            for message in kwargs.get("messages", [])
            if _message_role(message) == "user"
        )
        _remove_unfounded_invalid_counts(query, user_content)
        _remove_unfounded_optional_constraints(query, user_content)
        if any(
            marker in latest_user_content
            for marker in ("新手", "入门", "第一次徒步")
        ):
            query["max_difficulty"] = "easy"
        elif _has_challenge_preference(user_content):
            query["max_difficulty"] = "hard"
        extracted_scenery = _extract_scenery_preferences(
            user_content,
            routes,
        )
        if extracted_scenery:
            query["scenery_preferences"] = sorted({
                *query.get("scenery_preferences", []),
                *extracted_scenery,
            })
        destination_name = str(query.pop("destination_name", "")).strip()
        if destination_name:
            destination_matches = self.service.routes_by_group_tour_search_term(
                destination_name,
            )
            destination_route_ids = {
                str(route["id"])
                for route in destination_matches
            }
            if len(destination_route_ids) == 1:
                query["route_id"] = next(iter(destination_route_ids))
            elif len(destination_route_ids) > 1:
                raise ValueError("目的地名称命中多条路线，请用户进一步确认具体路线")
            else:
                raise ValueError("目的地名称未匹配到已审核路线，请用户确认目的地")
        requested_route_id = str(query.get("route_id", "")).strip()
        if requested_route_id and requested_route_id not in known_ids:
            parameter_matches = self.service.routes_by_group_tour_search_term(
                requested_route_id,
            )
            parameter_route_ids = {
                str(route["id"])
                for route in parameter_matches
            }
            if len(parameter_route_ids) == 1:
                query["route_id"] = next(iter(parameter_route_ids))
            elif len(parameter_route_ids) > 1:
                raise ValueError("目的地检索词命中多条路线，请用户进一步确认具体路线")
        matched_route_ids = {
            str(route["id"])
            for term in _matched_group_tour_search_terms(user_content, routes)
            for route in self.service.routes_by_group_tour_search_term(term)
        }
        if len(matched_route_ids) == 1:
            query["route_id"] = next(iter(matched_route_ids))
        elif len(matched_route_ids) > 1:
            raise ValueError("目的地检索词命中多条路线，请用户进一步确认具体路线")
        items = self.service.recommendations(query)
        if len(items) > 1:
            items = [
                {
                    key: value for key, value in item.items()
                    if key in {"route", "score", "reasons"}
                }
                for item in items
            ]
        return _json_result({"count": len(items), "items": items})


class FindGroupTourLinksTool(HikingTool):
    name = "find_group_tour_links"
    description = "用户选定路线并选择报团后，实时查询已配置商团的相关活动链接。"
    parameters = [
        {
            "name": "route_id",
            "type": "string",
            "description": "用户已经选定的路线唯一标识",
            "required": True,
        },
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        items = self.service.group_tour_links(query["route_id"])
        return _json_result({"count": len(items), "items": items})


class FindRouteParkingPointsTool(HikingTool):
    name = "find_route_parking_points"
    description = "用户选定路线并确认自驾后，查询该路线已审核停车点、位置和停车说明。"
    parameters = [
        {
            "name": "route_id",
            "type": "string",
            "description": "用户已经选定的路线唯一标识",
            "required": True,
        },
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        route_id = str(query["route_id"])
        items = parking_points_with_navigation(
            self.service.parking_points(route_id)
        )
        result: dict[str, Any] = {"count": len(items), "items": items}
        if items:
            return _json_result(result)

        route = next(
            (item for item in self.service.routes() if str(item["id"]) == route_id),
            None,
        )
        if route is None:
            raise ValueError("路线不存在或未审核")
        reference: dict[str, Any] = {
            "name": str(route["start_location"]),
            "latitude": route.get("latitude"),
            "longitude": route.get("longitude"),
            "is_parking_point": False,
            "reference_only": True,
        }
        if route.get("latitude") is not None and route.get("longitude") is not None:
            reference = parking_points_with_navigation([reference])[0]
        warning = (
            "暂无已审核停车场信息。该位置仅为徒步起点参考，不代表可以停车，"
            "请以现场停车标识和交通管制为准。"
        )
        reference["note"] = warning
        result["trailhead_reference"] = reference
        result["warning"] = warning
        return _json_result(result)


class EstimateRouteTrafficTool(HikingTool):
    name = "estimate_route_traffic"
    description = "估算指定徒步路线在指定出发时间的交通情况。"
    parameters = [
        {"name": "route_id", "type": "string", "description": "路线唯一标识", "required": True},
        {
            "name": "departure_at",
            "type": "string",
            "description": "出发时间，ISO 8601 时间",
            "required": True,
        },
        {"name": "origin", "type": "string", "description": "出发地，默认成都"},
        {
            "name": "direction",
            "type": "string",
            "description": "方向，可选 outbound 或 return",
        },
        {"name": "is_holiday", "type": "boolean", "description": "是否为节假日"},
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        return _json_result(self.service.traffic(query))


class EstimateRouteWeatherTool(HikingTool):
    name = "estimate_route_weather"
    description = "获取指定路线在出发日期当天 08:30–19:00 安全覆盖时段内生效的官方天气预警，并返回出发日期温度和简单天气现象参考。"
    parameters = [
        {"name": "route_id", "type": "string", "description": "路线唯一标识", "required": True},
        {
            "name": "departure_at",
            "type": "string",
            "description": "从成都出发的 ISO 8601 时间",
            "required": True,
        },
        {"name": "origin", "type": "string", "description": "出发地，默认成都"},
        {"name": "is_holiday", "type": "boolean", "description": "是否为节假日"},
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        routes = self.service.routes()
        known_ids = {str(route["id"]) for route in routes}
        if str(query["route_id"]) not in known_ids:
            matched_route_id = _match_route_id(str(query["route_id"]), routes)
            if matched_route_id is not None:
                query["route_id"] = matched_route_id
        return _json_result(self.service.weather(query))


class ResolvePublicHolidayTool(HikingTool):
    name = "resolve_public_holiday"
    description = "查询中国大陆全国性法定节假日日期，或判断具体日期是否处于节假日假期。"
    parameters = [
        {"name": "name", "type": "string", "description": "节日名称，例如端午节、国庆节"},
        {"name": "year", "type": "integer", "description": "查询年份，按节日名称查询时使用"},
        {"name": "date", "type": "string", "description": "需要判断的 ISO 8601 日期，例如 2026-06-19"},
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        result = resolve_public_holiday(
            name=query.get("name"),
            year=query.get("year"),
            date_value=query.get("date"),
        )
        return _json_result(result)


class ResolveDepartureDateTool(HikingTool):
    name = "resolve_departure_date"
    description = "按中文自然周解析本周末、下周末、下周三、明天等相对出发日期表达。"
    parameters = [
        {
            "name": "expression",
            "type": "string",
            "description": "相对日期表达，例如本周末、下周末、下周三、本周六、明天",
            "required": True,
        },
        {
            "name": "reference_date",
            "type": "string",
            "description": "当前本地 ISO 8601 日期；应使用系统提示提供的当前日期",
        },
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        reference_value = query.get("reference_date")
        try:
            reference = (
                date.fromisoformat(reference_value)
                if reference_value
                else datetime.now().astimezone().date()
            )
        except ValueError as exc:
            raise ValueError("reference_date 必须是 ISO 8601 日期") from exc
        return _json_result(resolve_departure_date(query["expression"], reference))


def build_qwen_agent(service: ChatBIService, model: str = QWEN_MODEL) -> GuidedHikingAssistant:
    """Build a Qwen Agent that can only call read-only hiking tools."""
    system_message = (
        f"{SYSTEM_PROMPT}\n\n# 当前日期上下文\n{build_departure_date_guidance()}"
        f"\n\n# 已收录节假日摘要\n{build_public_holiday_guidance()}"
    )
    generate_cfg: dict[str, Any] = {
        "max_retries": QWEN_MAX_RETRIES,
        "request_timeout": QWEN_REQUEST_TIMEOUT_SECONDS,
    }
    if QWEN_SEED is not None:
        generate_cfg["seed"] = QWEN_SEED
    logger.info("构建 Qwen Agent model=%s seed=%s", model, QWEN_SEED)
    agent = GuidedHikingAssistant(
        llm={
            "model": model,
            "model_type": "qwen_dashscope",
            "generate_cfg": generate_cfg,
        },
        name="ChatBI",
        description="根据用户要求查询和推荐成都周边徒步路线",
        system_message=system_message,
        function_list=[
            ListHikingRoutesTool(service),
            RecommendHikingRoutesTool(service),
            EstimateRouteTrafficTool(service),
            EstimateRouteWeatherTool(service),
            FindGroupTourLinksTool(service),
            FindRouteParkingPointsTool(service),
            ResolveDepartureDateTool(service),
            ResolvePublicHolidayTool(service),
        ],
    )
    agent.route_catalog = service.routes()
    agent.route_search_terms = build_route_search_terms(agent.route_catalog)
    return agent


def require_dashscope_api_key() -> str:
    """Return the configured DashScope key or raise an actionable error."""
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法启动 Qwen Agent")
    return api_key


def run_qwen_chat(service: ChatBIService, model: str = QWEN_MODEL) -> None:
    """Run a continuous terminal conversation with the hiking agent."""
    require_dashscope_api_key()
    agent = build_qwen_agent(service, model)
    messages: list[Any] = []
    logger.info("成都徒步 ChatBI 终端对话已启动 model=%s", model)
    while True:
        query = input("用户：").strip()
        if query.lower() in {"exit", "quit"}:
            logger.info("成都徒步 ChatBI 终端对话已退出")
            return
        if not query:
            logger.warning("终端对话收到空输入")
            continue
        messages.append({"role": "user", "content": query})
        response: list[Any] = []
        for response in agent.run(messages=messages, lang="zh"):
            pass
        messages.extend(response)
        answer = "\n".join(
            str(message.content)
            for message in response
            if getattr(message, "role", "") == "assistant" and getattr(message, "content", "")
        )
        logger.info("助手：%s", answer or "未生成可显示的回答")


def run_qwen_web(
    service: ChatBIService,
    model: str = QWEN_MODEL,
    host: str | None = None,
    port: int | None = None,
    *,
    prevent_thread_lock: bool = False,
) -> Any:
    """Run the Qwen Agent demonstration WebUI."""
    require_dashscope_api_key()
    logger.info("Qwen Agent WebUI 正在启动 host=%s port=%s model=%s", host, port, model)
    from qwen_agent.gui import WebUI

    return WebUI(
        build_qwen_agent(service, model),
        chatbot_config={
            **WEB_CHATBOT_CONFIG,
            "prompt.suggestions": [
                "本周六从成都出发，推荐适合新手的路线",
                "路程不超过10公里或者爬升不超过 800 米的路线",
                "本周日出发，有草甸的徒步路线推荐",
                "周六想去爬巴朗山，不知道天气怎么样",
            ]
        },
    ).run(
        server_name=host,
        server_port=port,
        prevent_thread_lock=prevent_thread_lock,
    )


def run_qwen_h5(
    service: ChatBIService,
    model: str = QWEN_MODEL,
    host: str | None = None,
    port: int | None = None,
) -> Any:
    """Run the independent mobile H5 chat page."""
    require_dashscope_api_key()
    logger.info("Qwen Agent H5 正在启动 host=%s port=%s model=%s", host, port, model)
    from qwen_agent.gui import H5WebUI

    return H5WebUI(
        build_qwen_agent(service, model),
        chatbot_config={
            **WEB_CHATBOT_CONFIG,
            "header.title": "成都徒步ChatBI助手",
            "header.subtitle": "成都周边徒步路线、天气与出行助手",
            "prompt.suggestions": [
                "本周六从成都出发，推荐适合新手的路线",
                "路程不超过10公里或者爬升不超过 800 米的路线",
                "想去爬巴朗山，不知道天气怎么样",
            ],
        },
    ).run(server_name=host, server_port=port)
