from __future__ import annotations

import json
import logging
import os
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
4. 优先了解出发日期、交通方式、体力或经验、预算、风景偏好；不要求每项都必须回答。
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
22. 和用户沟通选择路线时，必须先明确出行方式和出行时间，再确认其它筛选条件。出行方式应先在
    自驾、公共交通、报团中明确其一；出行时间应明确到具体出发日期，涉及交通估算时尽量确认出发时段或时间。
    在出行方式和出行时间都明确之前，不得继续追问预算、强度、风景、设施等其它筛选条件，也不得调用路线推荐、
    交通估算或天气估算工具。用户明确选择报团时，优先使用 recommend_commercial_tours，并遵守商团产品回答边界。
    若只能一次问一个问题，先问出行方式；已明确出行方式后，再问具体出行时间。
23. 输出普通路线推荐时，必须按固定顺序组织信息：推荐路线、推荐理由、天气参考、交通参考、费用参考、设施与风险、
    备选或下一步。每条路线先给路线名称和核心行程数据，再解释为什么推荐；天气参考先说官方预警，再说温度和简单天气现象；
    交通参考说明去程/返程耗时和数据类型；费用参考说明总费用范围和对应交通方式。缺少某一类工具结果时，说明暂无该项参考，
    不得自行补全。
24. 展示天气参考时，如果工具结果的 `data_sources`、`official_alerts.source` 或 `daily_weather.source`
    表明来自和风天气，必须明确写出天气来源，例如“官方预警来源：和风天气官方预警聚合”
    或“天气预报来源：和风天气每日天气预报”。如果工具结果没有提供来源，只能说明天气来源暂未提供，不得自行补充来源。"""


def _json_result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


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


def build_interview_guidance(messages: list[Any]) -> str:
    """Build turn-aware guidance for a natural hiking requirement interview."""
    user_turns = sum(_message_role(message) == "user" for message in messages)
    if user_turns <= 2:
        return (
            f"当前是第 {user_turns} 个用户轮次，处于探索阶段。"
            "先接住用户表达的兴趣或顾虑，再一次只问一个容易回答的问题。"
            "选择路线前，先补齐出行方式和出行时间：出行方式限定为自驾、公共交通、报团；"
            "若两者还没明确，不要先追问预算、强度、风景或设施。"
            "优先问最能缩小路线范围的前置条件，不要罗列缺失字段。"
        )
    if user_turns == 3:
        return (
            "当前处于收敛阶段。简短总结已知偏好，只确认一个仍会显著影响推荐结果的问题。"
            "如果出行方式或出行时间仍未明确，继续优先补齐其中一个；不要先进入其它筛选条件。"
            "如果信息已经足够，直接进入推荐，不要为了凑轮次继续提问。"
        )
    return (
        f"当前已交流 {user_turns} 个用户轮次，处于推荐阶段。"
        "进入推荐前再次检查：必须已有明确出行方式和具体出行时间；缺少任一项时先补问该项。"
        "信息基本可用时立即给出初步推荐，不要继续机械追问。"
        "缺失的次要条件采用保守默认值并明确说明；若缺少日期，只能先补问日期。"
    )


class GuidedHikingAssistant(Assistant):
    """Qwen Assistant with turn-aware hiking interview guidance."""

    def _run(self, messages: list[Any], **kwargs: Any) -> Any:
        guided_messages = deepcopy(messages)
        guidance = build_interview_guidance(guided_messages)
        if guided_messages and _message_role(guided_messages[0]) == SYSTEM:
            guided_messages[0].content = f"{guided_messages[0].content}\n\n# 当前对话策略\n{guidance}"
        return super()._run(messages=guided_messages, **kwargs)


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
    description = "访谈信息足够或用户要求立即推荐时，根据出发时间、交通方式、预算、体力和偏好推荐徒步路线。"
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


class RecommendCommercialToursTool(HikingTool):
    name = "recommend_commercial_tours"
    description = (
        "根据已收录、已审核的商团产品数据，推荐适合报商团的成都周边徒步路线。"
        "不得用于查询未收录商家、余位、成团状态、报名截止或联系方式。"
    )
    parameters = [
        {
            "name": "departure_date",
            "type": "string",
            "description": "出发日期，ISO 8601 日期；提供时只严格匹配当天团期",
        },
        {"name": "route_id", "type": "string", "description": "限定路线唯一标识"},
        {"name": "party_size", "type": "integer", "description": "出行人数，默认 1"},
        {
            "name": "max_budget_cny",
            "type": "number",
            "description": "整组最高总预算，按人数乘以单人套餐最高价过滤",
        },
        {"name": "max_distance_km", "type": "number", "description": "最大徒步距离，公里"},
        {"name": "max_ascent_m", "type": "integer", "description": "最大累计爬升，米"},
        {"name": "max_duration_days", "type": "integer", "description": "最大行程天数，默认 1"},
        {
            "name": "max_difficulty",
            "type": "string",
            "description": "最高难度，可选 easy、moderate、hard、expert",
        },
        {
            "name": "scenery_preferences",
            "type": "array",
            "items": {"type": "string"},
            "description": "风景偏好，用于商团路线适配排序",
        },
    ]

    def call(self, params: str | dict[str, Any], **kwargs: Any) -> str:
        query = self.verify_params(params)
        items = self.service.commercial_tours(query)
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
        "\n\n# 商团产品回答规则\n"
        "需要推荐或比较报商团产品时，必须调用 recommend_commercial_tours。"
        "商家、产品、集合点、价格、团期和包含服务必须来自工具结果；"
        "不得编造未收录商家、未收录团期、报名链接、联系方式、报名截止、成团状态或名额信息；"
        "回答商团推荐时必须展示商团名称，方便用户向相应商团咨询详细信息；"
        "不承诺余位或成团状态，必须提醒用户报名前二次确认价格、团期、名额和安全要求；"
        "用户确认某个已收录活动后，可以引导用户去该商团的小程序进行报名。"
    )
    generate_cfg: dict[str, Any] = {"max_retries": 3}
    if QWEN_SEED is not None:
        generate_cfg["seed"] = QWEN_SEED
    logger.info("构建 Qwen Agent model=%s seed=%s", model, QWEN_SEED)
    return GuidedHikingAssistant(
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
            RecommendCommercialToursTool(service),
            EstimateRouteTrafficTool(service),
            EstimateRouteWeatherTool(service),
            ResolveDepartureDateTool(service),
            ResolvePublicHolidayTool(service),
        ],
    )


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
                "本周六从成都出发，预算 300 元，推荐适合新手的路线",
                "路线不超过10公里、爬升不超过 1000 米的路线",
                "青城后山周末早上六点出发交通怎么样？",
                "本周六成都出发的商团路线推荐",
            ]
        },
    ).run(server_name=host, server_port=port)
