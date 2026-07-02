from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS routes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    start_location TEXT NOT NULL,
    end_location TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    distance_km REAL NOT NULL CHECK(distance_km > 0),
    ascent_m INTEGER NOT NULL CHECK(ascent_m >= 0),
    highest_altitude_m INTEGER NOT NULL CHECK(highest_altitude_m >= 0),
    hiking_minutes INTEGER NOT NULL CHECK(hiking_minutes > 0),
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy','moderate','hard','expert')),
    duration_days INTEGER NOT NULL CHECK(duration_days > 0),
    route_type TEXT NOT NULL,
    is_traverse INTEGER NOT NULL DEFAULT 0 CHECK(is_traverse IN (0,1)),
    traverse_transfer_minutes INTEGER NOT NULL DEFAULT 0 CHECK(traverse_transfer_minutes >= 0),
    best_seasons_json TEXT NOT NULL,
    scenery_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    transport_modes_json TEXT NOT NULL,
    group_tour_search_terms_json TEXT NOT NULL DEFAULT '[]',
    cost_min_cny REAL NOT NULL,
    cost_max_cny REAL NOT NULL,
    parking TEXT,
    supplies TEXT,
    has_toilet INTEGER NOT NULL DEFAULT 0 CHECK(has_toilet IN (0,1)),
    has_supply_shop INTEGER NOT NULL DEFAULT 0 CHECK(has_supply_shop IN (0,1)),
    signal TEXT,
    camping TEXT,
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    reviewed INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0,1))
);

CREATE TABLE IF NOT EXISTS traffic_profiles (
    route_id TEXT PRIMARY KEY REFERENCES routes(id) ON DELETE CASCADE,
    base_one_way_minutes INTEGER NOT NULL,
    weekday_extra_min INTEGER NOT NULL DEFAULT 0,
    weekday_extra_max INTEGER NOT NULL DEFAULT 0,
    weekend_extra_min INTEGER NOT NULL DEFAULT 0,
    weekend_extra_max INTEGER NOT NULL DEFAULT 0,
    holiday_extra_min INTEGER NOT NULL DEFAULT 0,
    holiday_extra_max INTEGER NOT NULL DEFAULT 0,
    morning_extra_minutes INTEGER NOT NULL DEFAULT 0,
    evening_extra_minutes INTEGER NOT NULL DEFAULT 0,
    common_bottlenecks_json TEXT NOT NULL,
    best_departure_time TEXT,
    suggested_return_time TEXT,
    source_url TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1)
);

CREATE TABLE IF NOT EXISTS route_cost_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    cost_type TEXT NOT NULL CHECK(cost_type IN ('ticket','shuttle','waste','parking','other')),
    billing_unit TEXT NOT NULL CHECK(billing_unit IN ('person','vehicle','group')),
    min_cny REAL NOT NULL CHECK(min_cny >= 0),
    max_cny REAL NOT NULL CHECK(max_cny >= min_cny),
    source_url TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transport_cost_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    transport_mode TEXT NOT NULL CHECK(transport_mode IN ('self_drive','public_transit','carpool','group_tour')),
    name TEXT NOT NULL,
    cost_type TEXT NOT NULL CHECK(cost_type IN ('fuel','toll','train','bus','other')),
    billing_unit TEXT NOT NULL CHECK(billing_unit IN ('person','vehicle','group')),
    min_cny REAL NOT NULL CHECK(min_cny >= 0),
    max_cny REAL NOT NULL CHECK(max_cny >= min_cny),
    source_url TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    traveled_at TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('outbound','return')),
    actual_minutes INTEGER NOT NULL CHECK(actual_minutes > 0),
    congestion_level TEXT NOT NULL CHECK(congestion_level IN ('low','medium','high','severe')),
    source TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""

JSON_FIELDS = {
    "best_seasons",
    "scenery",
    "risks",
    "transport_modes",
    "group_tour_search_terms",
    "common_bottlenecks",
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    if logger.isEnabledFor(logging.DEBUG):
        connection.set_trace_callback(_log_sql_statement)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _log_sql_statement(statement: str) -> None:
    logger.debug("SQL: %s", statement)


def initialize(path: Path) -> None:
    with closing(connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA)
            _add_route_facility_columns(connection)
            _add_route_traverse_columns(connection)
            _add_group_tour_search_terms_column(connection)
            _migrate_route_cost_items(connection)
            _backfill_legacy_costs(connection)


def _add_route_facility_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(routes)")
    }
    if "has_toilet" not in columns:
        connection.execute(
            "ALTER TABLE routes ADD COLUMN has_toilet INTEGER NOT NULL DEFAULT 0 CHECK(has_toilet IN (0,1))"
        )
    if "has_supply_shop" not in columns:
        connection.execute(
            "ALTER TABLE routes ADD COLUMN has_supply_shop INTEGER NOT NULL DEFAULT 0 CHECK(has_supply_shop IN (0,1))"
        )


def _add_route_traverse_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(routes)")
    }
    if "is_traverse" not in columns:
        connection.execute(
            "ALTER TABLE routes ADD COLUMN is_traverse INTEGER NOT NULL DEFAULT 0 CHECK(is_traverse IN (0,1))"
        )
    if "traverse_transfer_minutes" not in columns:
        connection.execute(
            "ALTER TABLE routes ADD COLUMN traverse_transfer_minutes INTEGER NOT NULL DEFAULT 0 CHECK(traverse_transfer_minutes >= 0)"
        )


def _add_group_tour_search_terms_column(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(routes)")
    }
    if "group_tour_search_terms_json" not in columns:
        connection.execute(
            "ALTER TABLE routes ADD COLUMN group_tour_search_terms_json TEXT NOT NULL DEFAULT '[]'"
        )


def _migrate_route_cost_items(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'route_cost_items'"
    ).fetchone()
    if not row or ("'parking'" in row["sql"] and "'vehicle'" in row["sql"]):
        return
    connection.execute(
        """CREATE TABLE route_cost_items_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        cost_type TEXT NOT NULL CHECK(cost_type IN ('ticket','shuttle','waste','parking','other')),
        billing_unit TEXT NOT NULL CHECK(billing_unit IN ('person','vehicle','group')),
        min_cny REAL NOT NULL CHECK(min_cny >= 0),
        max_cny REAL NOT NULL CHECK(max_cny >= min_cny),
        source_url TEXT NOT NULL,
        updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO route_cost_items_new
        (id,route_id,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at)
        SELECT id,route_id,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at
        FROM route_cost_items"""
    )
    connection.execute("DROP TABLE route_cost_items")
    connection.execute("ALTER TABLE route_cost_items_new RENAME TO route_cost_items")


def _backfill_legacy_costs(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(routes)")
    }
    if not {"cost_min_cny", "cost_max_cny"} <= columns:
        return
    connection.execute(
        """INSERT INTO route_cost_items
        (route_id,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at)
        SELECT r.id,'历史汇总费用','other','group',r.cost_min_cny,r.cost_max_cny,
               r.source_url,r.updated_at
        FROM routes r
        WHERE NOT EXISTS (
            SELECT 1 FROM route_cost_items c WHERE c.route_id = r.id
        )"""
    )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in list(result):
        if key.endswith("_json"):
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    if "reviewed" in result:
        result["reviewed"] = bool(result["reviewed"])
    for field in ("has_toilet", "has_supply_shop", "is_traverse"):
        if field in result:
            result[field] = bool(result[field])
    return result


def upsert_route(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    route = item["route"]
    traffic = item["traffic"]
    route_columns = [
        "id", "name", "start_location", "end_location", "latitude", "longitude",
        "distance_km", "ascent_m", "highest_altitude_m", "hiking_minutes",
        "difficulty", "duration_days", "route_type", "is_traverse",
        "traverse_transfer_minutes", "best_seasons_json",
        "scenery_json", "risks_json", "transport_modes_json",
        "group_tour_search_terms_json", "cost_min_cny", "cost_max_cny",
        "parking", "supplies", "has_toilet", "has_supply_shop",
        "signal", "camping", "source_url",
        "source_name", "collected_at", "updated_at", "confidence", "reviewed",
    ]
    encoded = dict(route)
    all_costs = item["costs"]["route_fees"] + item["costs"]["transport_options"]
    encoded["cost_min_cny"] = sum(float(cost["min_cny"]) for cost in all_costs)
    encoded["cost_max_cny"] = sum(float(cost["max_cny"]) for cost in all_costs)
    for field in ("best_seasons", "scenery", "risks", "transport_modes"):
        encoded[f"{field}_json"] = json.dumps(route[field], ensure_ascii=False)
    encoded["group_tour_search_terms_json"] = json.dumps(
        route.get("group_tour_search_terms", []), ensure_ascii=False
    )
    values = [encoded.get(column) for column in route_columns]
    placeholders = ",".join("?" for _ in route_columns)
    updates = ",".join(f"{column}=excluded.{column}" for column in route_columns[1:])
    connection.execute(
        f"INSERT INTO routes ({','.join(route_columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    _replace_cost_items(connection, route["id"], item["costs"])

    traffic_columns = [
        "route_id", "base_one_way_minutes", "weekday_extra_min", "weekday_extra_max",
        "weekend_extra_min", "weekend_extra_max", "holiday_extra_min",
        "holiday_extra_max", "morning_extra_minutes", "evening_extra_minutes",
        "common_bottlenecks_json", "best_departure_time", "suggested_return_time",
        "source_url", "updated_at", "confidence",
    ]
    encoded_traffic = dict(traffic, route_id=route["id"])
    encoded_traffic["common_bottlenecks_json"] = json.dumps(
        traffic["common_bottlenecks"], ensure_ascii=False
    )
    traffic_values = [encoded_traffic.get(column) for column in traffic_columns]
    traffic_updates = ",".join(
        f"{column}=excluded.{column}" for column in traffic_columns[1:]
    )
    connection.execute(
        f"INSERT INTO traffic_profiles ({','.join(traffic_columns)}) "
        f"VALUES ({','.join('?' for _ in traffic_columns)}) "
        f"ON CONFLICT(route_id) DO UPDATE SET {traffic_updates}",
        traffic_values,
    )


def _replace_cost_items(
    connection: sqlite3.Connection,
    route_id: str,
    costs: dict[str, list[dict[str, Any]]],
) -> None:
    connection.execute("DELETE FROM route_cost_items WHERE route_id = ?", (route_id,))
    connection.execute("DELETE FROM transport_cost_items WHERE route_id = ?", (route_id,))
    for item in costs["route_fees"]:
        connection.execute(
            """INSERT INTO route_cost_items
            (route_id,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                route_id, item["name"], item["cost_type"], item["billing_unit"],
                item["min_cny"], item["max_cny"], item["source_url"], item["updated_at"],
            ),
        )
    for item in costs["transport_options"]:
        connection.execute(
            """INSERT INTO transport_cost_items
            (route_id,transport_mode,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                route_id, item["transport_mode"], item["name"], item["cost_type"],
                item["billing_unit"], item["min_cny"], item["max_cny"],
                item["source_url"], item["updated_at"],
            ),
        )


def import_routes(path: Path, items: Iterable[dict[str, Any]]) -> int:
    initialize(path)
    count = 0
    with closing(connect(path)) as connection:
        with connection:
            for item in items:
                upsert_route(connection, item)
                count += 1
    return count


def list_routes(path: Path, reviewed_only: bool = True) -> list[dict[str, Any]]:
    query = """
        SELECT r.*, t.base_one_way_minutes, t.weekday_extra_min, t.weekday_extra_max,
          t.weekend_extra_min, t.weekend_extra_max, t.holiday_extra_min,
          t.holiday_extra_max, t.morning_extra_minutes, t.evening_extra_minutes,
          t.common_bottlenecks_json, t.best_departure_time, t.suggested_return_time,
          t.source_url AS traffic_source_url, t.updated_at AS traffic_updated_at,
          t.confidence AS traffic_confidence,
          (SELECT AVG(f.actual_minutes) FROM trip_feedback f
            WHERE f.route_id = r.id) AS feedback_avg_minutes,
          (SELECT COUNT(*) FROM trip_feedback f
            WHERE f.route_id = r.id) AS feedback_count
        FROM routes r JOIN traffic_profiles t ON t.route_id = r.id
    """
    params: tuple[Any, ...] = ()
    if reviewed_only:
        query += " WHERE r.reviewed = ?"
        params = (1,)
    with closing(connect(path)) as connection:
        routes = [_decode(row) for row in connection.execute(query, params)]
        route_fees: dict[str, list[dict[str, Any]]] = {}
        for row in connection.execute(
            "SELECT route_id,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at FROM route_cost_items"
        ):
            item = dict(row)
            route_fees.setdefault(item.pop("route_id"), []).append(item)
        transport_options: dict[str, list[dict[str, Any]]] = {}
        for row in connection.execute(
            "SELECT route_id,transport_mode,name,cost_type,billing_unit,min_cny,max_cny,source_url,updated_at FROM transport_cost_items"
        ):
            item = dict(row)
            transport_options.setdefault(item.pop("route_id"), []).append(item)
        for route in routes:
            route.pop("cost_min_cny", None)
            route.pop("cost_max_cny", None)
            route["route_fees"] = route_fees.get(route["id"], [])
            route["transport_options"] = transport_options.get(route["id"], [])
        return routes


def get_route(path: Path, route_id: str) -> dict[str, Any] | None:
    routes = [route for route in list_routes(path, reviewed_only=False) if route["id"] == route_id]
    return routes[0] if routes else None


def find_routes_by_group_tour_search_term(
    path: Path,
    search_term: str,
    reviewed_only: bool = True,
) -> list[dict[str, Any]]:
    """Find routes by fuzzy matching only the stored group-tour search terms JSON."""
    normalized_term = search_term.strip()
    if not normalized_term:
        return []
    escaped_term = (
        normalized_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    query = "SELECT id FROM routes WHERE group_tour_search_terms_json LIKE ? ESCAPE '\\'"
    parameters: list[Any] = [f"%{escaped_term}%"]
    if reviewed_only:
        query += " AND reviewed = 1"
    with closing(connect(path)) as connection:
        route_ids = {
            str(row["id"])
            for row in connection.execute(query, parameters).fetchall()
        }
    return [route for route in list_routes(path, reviewed_only) if route["id"] in route_ids]
