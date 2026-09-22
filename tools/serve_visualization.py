"""Serve the interactive demo and expose its optional realtime LLM boundary.

The static page and generated catalog are intentionally kept separate from the
LLM credentials.  The endpoint reuses the real-data-derived controlled stress
scenario so a request exercises the same decision-tree-first controller used by
the saved audit.  It does not persist request bodies, prompts, or credentials.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Running this file directly puts ``tools/`` on sys.path; the scheduling
# package and the sibling scenario module both live one level above it.
ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = Path(__file__).resolve().parent
for import_root in (ROOT, TOOLS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from ladle_preallocation.llm.react_agent import ReActRescheduler
from ladle_preallocation.offline_scenarios import ScenarioRepository
from ladle_preallocation.offline_scenarios.validation import ScenarioValidationPolicy, ScenarioValidator
from ladle_preallocation.real_data.audit import load_location_aware_audit
from ladle_preallocation.response import TieredResponseController

from real_data_codex_stress_demo import SOURCE_AUDIT, build_scenario


STATIC_ROOT = ROOT / "visualization"
DEFAULT_SCENARIO_DB = ROOT / "outputs/offline_scenarios/ladle_scenarios.sqlite3"
LOGGER = logging.getLogger("visualization-server")


def _runtime_config() -> dict[str, str]:
    """Read runtime-only LLM settings without exposing secret values."""
    return {
        "api_key": os.environ.get("LLM_API_KEY", "").strip(),
        "api_base": os.environ.get("LLM_API_BASE", "https://api.deepseek.com").strip(),
        "model": os.environ.get("LLM_MODEL", "deepseek-v4-flash").strip(),
    }


def _result_payload(result: Any, scenario: Any, *, api_configured: bool) -> dict[str, Any]:
    """Return the minimal redacted response needed by the browser."""
    return {
        "path": result.path.value,
        "success": bool(result.success),
        "num_assigned": result.num_assigned,
        "num_total": len(scenario.heats_needing_reallocation),
        "elapsed_seconds": round(float(result.elapsed_seconds), 3),
        "remaining_budget_seconds": result.remaining_budget_seconds,
        "reason": result.reason,
        "human_review_required": bool(result.human_review_required),
        "api_configured": api_configured,
        "validation_feedback": result.validation_feedback,
        "affected_heat_ids": list(scenario.affected_heat_ids),
    }


def simulate(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run one request through the production response controller."""
    scenario_id = str(payload.get("scenario_id") or "real_window_1100_1120_codex_stress_001")
    if scenario_id != "real_window_1100_1120_codex_stress_001":
        return HTTPStatus.BAD_REQUEST, {
            "error": "当前实时接口只开放真实快照派生的受控压力场景",
            "supported_scenario_ids": ["real_window_1100_1120_codex_stress_001"],
        }

    try:
        source = load_location_aware_audit(SOURCE_AUDIT)
        scenario, _ = build_scenario(source)
        config = _runtime_config()
        llm = ReActRescheduler(
            api_base=config["api_base"],
            api_key=config["api_key"],
            model=config["model"],
            max_rounds=5,
        )
        # The controller always executes the decision tree first.  The LLM
        # object is only invoked after that path fails and budget remains.
        first_heat = scenario.heats_needing_reallocation[0]
        validator = ScenarioValidator(ScenarioValidationPolicy(
            allowed_routes_by_heat={str(first_heat["heat_id"]): (str(first_heat.get("refining_route") or "").strip(),)},
        ))
        result, llm_result = TieredResponseController(llm, validator=validator).handle_disturbance(scenario)
        response = _result_payload(result, scenario, api_configured=bool(config["api_key"]))
        response["llm_attempted"] = llm_result is not None
        response["llm_path"] = llm_result.path.value if llm_result is not None else None
        response["scenario_id"] = scenario_id
        if not config["api_key"] and llm_result is not None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                **response,
                "error": "LLM_API_KEY 未配置；实时请求未伪造成功结果，已返回 Frozen + 人工路径",
            }
        return HTTPStatus.OK, response
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        LOGGER.exception("simulation failed: %s", type(exc).__name__)
        return HTTPStatus.INTERNAL_SERVER_ERROR, {
            "error": "实时模拟失败，请查看本地服务端错误类型",
            "error_type": type(exc).__name__,
        }


class DemoHandler(SimpleHTTPRequestHandler):
    """Static handler plus a small JSON API."""

    scenario_database = DEFAULT_SCENARIO_DB

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not path.startswith("/api/scenarios"):
            super().do_GET()
            return
        try:
            repository = ScenarioRepository(self.scenario_database)
            if path == "/api/scenarios/summary":
                self._send_json(HTTPStatus.OK, repository.summary())
                return
            if path == "/api/scenarios":
                category = None
                for pair in parsed.query.split("&"):
                    if pair.startswith("category="):
                        category = pair.split("=", 1)[1] or None
                self._send_json(HTTPStatus.OK, {"scenarios": repository.list_scenarios(category)})
                return
            scenario_id = path.removeprefix("/api/scenarios/")
            scenario = repository.get_scenario(scenario_id)
            if scenario is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "离线场景不存在", "scenario_id": scenario_id})
                return
            self._send_json(HTTPStatus.OK, scenario)
        except FileNotFoundError:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "离线场景库尚未生成，请先运行 build_offline_scenario_db.py"})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (OSError, sqlite3.Error) as exc:
            LOGGER.exception("offline scenario query failed: %s", type(exc).__name__)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "离线场景查询失败", "error_type": type(exc).__name__})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if urlparse(self.path).path != "/api/simulate":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("request body size out of range")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"请求格式错误：{type(exc).__name__}"})
            return
        status, body = simulate(payload)
        self._send_json(status, body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the interactive ladle allocation demo")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--scenario-db", type=Path, default=DEFAULT_SCENARIO_DB)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    DemoHandler.scenario_database = args.scenario_db
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    LOGGER.info("serving %s at http://127.0.0.1:%s/", STATIC_ROOT, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
