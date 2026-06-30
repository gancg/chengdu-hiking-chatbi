from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterator
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from qwen_agent.agents import Assistant
from qwen_agent.llm.schema import SYSTEM
from qwen_agent.tools.base import BaseTool

from .config import QWEN_SEED
from .service import ChatBIService
from .departure_dates import resolve_departure_date
from .holidays import HOLIDAY_CALENDARS, WEEKDAY_NAMES, resolve_public_holiday


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
20. 用户使用“本周末”“下周末”“本周六”“明天”等相对日期表达时，必须先调用相对出发日期查询工具，
    并采用工具返回的候选日期、星期和日期类型；不得自行推算具体日期或星期。
    不得在调用工具前先输出自行推算的日期、星期或节假日判断。
    如果用户给出的日期和星期不一致，以工具返回的日期和星期为准，并向用户说明已按工具核验结果处理。
    如果工具返回多个仍可出发的候选日期且日期会影响结果，应使用数字编号请用户选择。
    用户只说“周末出行”“周末早上出发”等未明确具体日期的表达时，必须先询问清楚具体是哪一天。
    涉及交通、天气或路线推荐估算前，不得自行选择周六或周日作为出发日期。
21. 所有路线推荐默认面向单日往返出行；调用推荐工具时未另有明确约束，应按单日路线理解。
    多日游路线暂未完整支持，后续补充（TODO）。用户请求多日游时，应说明当前暂不推荐多日游路线，
    不得把现有单日路线包装成多日游方案。
22. 和用户沟通选择路线时，前期先确认具体出发时间，再通过体力或经验、距离、爬升、难度、风景和设施等条件，
    筛选出符合用户预期的候选路线。前期对话不得询问或要求用户选择交通方式，也不得展示交通方式选项。
    形成候选路线时可以不传 `transport_modes`，不得为了调用推荐工具而虚构交通方式。
    给出候选路线后，必须先让用户明确选择其中一条路线，不得在同一轮追加交通方式问题。
    用户尚未明确选定路线时，不得询问或展示交通方式选项。用户明确选定某条路线后，下一步只确认交通方式：
    1. 自驾 2. 报团 3. 公共交通。如果用户提前主动提供交通方式，可以暂存，但仍须先完成路线选择。
23. 输出候选路线时，必须按固定顺序组织信息：推荐路线、推荐理由、天气参考、设施与风险、路线选择。
    每条路线先给路线名称和核心行程数据，再解释为什么推荐；天气参考先说官方预警，再说温度和简单天气现象。
    候选路线阶段不得展开交通和费用比较，结尾只让用户选择一条路线。选定路线并确认交通方式后，
    再补充去程与返程耗时、交通数据类型、费用范围和最终方案；缺少工具结果时说明暂无参考，不得自行补全。
24. 展示天气参考时，如果工具结果的 `data_sources`、`official_alerts.source` 或 `daily_weather.source`
    表明来自和风天气，必须明确写出天气来源，例如“官方预警来源：和风天气官方预警聚合”
    或“天气预报来源：和风天气每日天气预报”。如果工具结果没有提供来源，只能说明天气来源暂未提供，不得自行补充来源。
25. 用户选定路线并明确选择报团后，必须调用 `find_group_tour_links` 实时查询游侠客公开活动。
    只能展示工具返回的活动标题和链接，并提示用户进入游侠客核实及完成后续操作；不得展示或推断价格、团期、余位，
    也不得在查询失败时回退到静态报团费用或旧商团数据。
26. 用户明确点名想去的地方，且该地点命中已审核路线名称或检索词时，目的地已经足以限定候选路线。
    如果尚未确定具体出发日期，只确认日期，不得再询问人数、体力、经验、距离、爬升、难度、风景、设施或最晚返回时间。
    日期确定后立即调用所需工具并推荐命中的路线，不得为了补齐普通访谈字段继续追问。此规则优先于通用访谈轮次规则。"""


def _json_result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


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
        if has_route_selection and "报团" in content:
            return True
    return False


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


def build_interview_guidance(
    messages: list[Any], route_search_terms: list[str] | None = None
) -> str:
    """Build turn-aware guidance for a natural hiking requirement interview."""
    user_turns = sum(_message_role(message) == "user" for message in messages)
    if _has_group_tour_selection_after_route(messages):
        return (
            "用户已经选定路线并明确选择报团。请立即调用 find_group_tour_links，"
            "使用已选路线的 route_id 实时查询。只展示活动标题和链接，并提示用户"
            "进入游侠客核实及完成后续操作；不得推断价格、团期或余位。"
        )
    if _has_explicit_route_selection(messages):
        return (
            "用户已经明确选定路线。下一步只确认交通方式，不再追加路线筛选问题。"
            "请使用连续编号询问：1. 自驾 2. 报团 3. 公共交通。"
            "用户确认后，再补充所选路线的交通估算、费用比较或最终方案。"
        )
    named_route_terms = _find_named_route_terms(messages, route_search_terms or [])
    if named_route_terms:
        matched_terms = "、".join(named_route_terms)
        return (
            f"用户点名的目的地已命中已审核路线（匹配词：{matched_terms}）。"
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
            guidance = build_interview_guidance(
                guided_messages,
                getattr(self, "route_search_terms", []),
            )
            if guided_messages and _message_role(guided_messages[0]) == SYSTEM:
                guided_messages[0].content = (
                    f"{guided_messages[0].content}\n\n# 当前对话策略\n{guidance}"
                )
            for response in super()._run(messages=guided_messages, **kwargs):
                output_batches += 1
                yield response
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            exception_code = getattr(exc, "code", None) or "n/a"
            exception_message = getattr(exc, "message", None) or str(exc) or repr(exc)
            logger.exception(
                "Qwen Agent 对话调用失败 call_id=%s model=%s message_count=%s "
                "user_turns=%s last_user_chars=%s output_batches=%s elapsed_ms=%s "
                "exception_type=%s exception_code=%s exception_message=%s",
                call_id,
                model,
                len(messages),
                user_turns,
                last_user_chars,
                output_batches,
                elapsed_ms,
                type(exc).__name__,
                exception_code,
                exception_message,
            )
            raise
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Qwen Agent 对话调用完成 call_id=%s model=%s message_count=%s "
            "user_turns=%s last_user_chars=%s output_batches=%s elapsed_ms=%s",
            call_id,
            model,
            len(messages),
            user_turns,
            last_user_chars,
            output_batches,
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
        routes = self.service.routes()
        return _json_result({"count": len(routes), "items": routes})


class RecommendHikingRoutesTool(HikingTool):
    name = "recommend_hiking_routes"
    description = (
        "访谈信息足够或用户要求立即推荐时，根据出发时间、预算、体力和偏好推荐徒步路线。"
        "形成候选路线时交通方式可暂不提供，候选形成后再用于交通和费用比较。"
    )
    parameters = [
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
            "description": "交通方式，可选 self_drive、public_transit、carpool、group_tour",
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
            "description": "风景偏好，例如森林、雪山、湖泊",
        },
        {"name": "is_holiday", "type": "boolean", "description": "是否为节假日"},
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        items = self.service.recommendations(query)
        return _json_result({"count": len(items), "items": items})


class FindGroupTourLinksTool(HikingTool):
    name = "find_group_tour_links"
    description = "用户选定路线并选择报团后，实时查询游侠客相关一日游活动链接。"
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
    description = "根据当前日期解析本周末、下周末、本周六、明天等相对出发日期表达。"
    parameters = [
        {
            "name": "expression",
            "type": "string",
            "description": "相对日期表达，例如本周末、下周末、本周六、明天",
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


def build_qwen_agent(service: ChatBIService, model: str = "qwen-plus") -> GuidedHikingAssistant:
    """Build a Qwen Agent that can only call read-only hiking tools."""
    system_message = (
        f"{SYSTEM_PROMPT}\n\n# 当前日期上下文\n{build_departure_date_guidance()}"
        f"\n\n# 已收录节假日摘要\n{build_public_holiday_guidance()}"
    )
    generate_cfg: dict[str, Any] = {"max_retries": 3}
    if QWEN_SEED is not None:
        generate_cfg["seed"] = QWEN_SEED
    logger.info("构建 Qwen Agent model=%s seed=%s", model, QWEN_SEED)
    agent = GuidedHikingAssistant(
        llm={
            "model": model,
            "model_type": "qwen_dashscope",
            "generate_cfg": generate_cfg,
        },
        name="成都徒步 ChatBI 助手",
        description="根据用户约束查询和推荐成都周边徒步路线",
        system_message=system_message,
        function_list=[
            ListHikingRoutesTool(service),
            RecommendHikingRoutesTool(service),
            EstimateRouteTrafficTool(service),
            EstimateRouteWeatherTool(service),
            FindGroupTourLinksTool(service),
            ResolveDepartureDateTool(service),
            ResolvePublicHolidayTool(service),
        ],
    )
    agent.route_search_terms = build_route_search_terms(service.routes())
    return agent


def require_dashscope_api_key() -> str:
    """Return the configured DashScope key or raise an actionable error."""
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法启动 Qwen Agent")
    return api_key


def run_qwen_chat(service: ChatBIService, model: str = "qwen-plus") -> None:
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
    model: str = "qwen-plus",
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Run the Qwen Agent demonstration WebUI."""
    require_dashscope_api_key()
    logger.info("Qwen Agent WebUI 正在启动 host=%s port=%s model=%s", host, port, model)
    from qwen_agent.gui import WebUI

    WebUI(
        build_qwen_agent(service, model),
        chatbot_config={
            "prompt.suggestions": [
                "本周六从成都出发，推荐适合新手的路线",
                "路线不超过10公里或者爬升不超过 800 米的路线",
                "本周末出发，有森林的徒步路线推荐",
            ]
        },
    ).run(server_name=host, server_port=port)
