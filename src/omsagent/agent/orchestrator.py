"""OMS agent orchestrator.

Two modes:
- ``run_order_workflow``: deterministic pipeline — parse the order intent from
  natural language -> RAG ops-manual lookup -> MCP tool calls
  (create_order -> run_matching -> get_order -> portfolio_summary) ->
  assemble context -> single inference call producing an execution report.
  Works with any backend (including the echo mock), ideal for demos/tests.
- ``run_react``: agentic ReAct loop. The model chooses tools
  (rag_search, mcp.oms.*) round by round until it emits a final report.
  Needs a real model behind the inference server.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..context.manager import ContextManager
from ..inference.client import InferenceClient
from . import prompts

_INTENT_RE = re.compile(
    r"(?i)\b(buy|sell)\b\s+(\d[\d,]*)\s+([A-Za-z]{1,5})\b"
)
_LIMIT_RE = re.compile(r"(?i)\blimit\s+(?:at\s+|@\s*)?(\d+(?:\.\d+)?)")
_STOP_RE = re.compile(r"(?i)\bstop\s+(?:at\s+|@\s*)?(\d+(?:\.\d+)?)")
_TIF_RE = re.compile(r"(?i)\b(day|gtc|ioc|fok)\b")
_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class OrderIntent:
    side: str
    quantity: int
    symbol: str
    order_type: str = "MARKET"
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "DAY"

    def to_tool_args(self) -> dict[str, Any]:
        args: dict[str, Any] = {
            "symbol": self.symbol, "side": self.side, "quantity": self.quantity,
            "order_type": self.order_type, "time_in_force": self.time_in_force,
        }
        if self.limit_price is not None:
            args["limit_price"] = self.limit_price
        if self.stop_price is not None:
            args["stop_price"] = self.stop_price
        return args

    def describe(self) -> str:
        px = ""
        if self.order_type == "LIMIT":
            px = f" @ limit {self.limit_price}"
        elif self.order_type == "STOP":
            px = f" @ stop {self.stop_price}"
        return f"{self.side} {self.quantity} {self.symbol} {self.order_type}{px} TIF={self.time_in_force}"


@dataclass
class ExecutionReport:
    instruction: str
    report: str
    sources: list[str] = field(default_factory=list)
    rounds: int = 0
    order_ids: list[str] = field(default_factory=list)
    context_stats: dict = field(default_factory=dict)


class OMSAgent:
    def __init__(
        self,
        inference: InferenceClient,
        context: ContextManager,
        rag: Any | None = None,
        mcp: Any | None = None,
        model: str = "oms-executor-v1",
        temperature: float = 0.2,
        max_tokens: int = 1200,
        rag_top_k: int = 4,
        react_max_rounds: int = 8,
        mcp_server: str = "oms",
    ) -> None:
        self.inference = inference
        self.context = context
        self.rag = rag
        self.mcp = mcp
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.rag_top_k = rag_top_k
        self.react_max_rounds = react_max_rounds
        self.mcp_server = mcp_server

    # -- intent parsing -------------------------------------------------
    @staticmethod
    def parse_intent(instruction: str) -> OrderIntent:
        """Parse 'buy 500 AAPL limit 230 gtc' style instructions."""
        m = _INTENT_RE.search(instruction)
        if not m:
            raise ValueError(
                "Could not parse an order intent. Expected e.g. "
                "'buy 500 AAPL', 'sell 100 TSLA limit 240', 'buy 1000 MSFT stop 420 gtc'."
            )
        side = m.group(1).upper()
        quantity = int(m.group(2).replace(",", ""))
        symbol = m.group(3).upper()
        limit_m = _LIMIT_RE.search(instruction)
        stop_m = _STOP_RE.search(instruction)
        tif_m = _TIF_RE.search(instruction)
        intent = OrderIntent(
            side=side, quantity=quantity, symbol=symbol,
            time_in_force=(tif_m.group(1).upper() if tif_m else "DAY"),
        )
        if limit_m:
            intent.order_type = "LIMIT"
            intent.limit_price = float(limit_m.group(1))
        elif stop_m:
            intent.order_type = "STOP"
            intent.stop_price = float(stop_m.group(1))
        return intent

    # -- MCP helpers ----------------------------------------------------
    async def _tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.mcp is None:
            raise RuntimeError("No MCP client configured.")
        data = await self.mcp.call_tool(self.mcp_server, tool, args)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return {"raw": data}
        return data if isinstance(data, dict) else {"raw": data}

    # -- staged pipeline ------------------------------------------------
    async def run_order_workflow(self, instruction: str) -> ExecutionReport:
        """Execute one natural-language order instruction end to end."""
        sources: list[str] = []
        order_ids: list[str] = []
        self.context.set_system(prompts.SYSTEM_EXECUTION)

        # 1. Parse intent.
        intent = self.parse_intent(instruction)
        self.context.add_section("order-intent",
                                 f"Parsed order intent: {intent.describe()}\n"
                                 f"Raw instruction: {instruction}",
                                 priority=100)

        # 2. RAG: pull relevant ops-manual guidance.
        if self.rag is not None:
            docs_md = self.rag.query_context(
                f"order lifecycle compliance {intent.order_type} {intent.time_in_force}",
                top_k=self.rag_top_k,
            )
            if docs_md:
                self.context.add_section("ops-manual", docs_md, priority=80)
                sources.append("[rag] ops manual (vector store)")

        # 3. Execute via MCP tools: create -> match -> inspect -> portfolio.
        tool_log: list[str] = []
        if self.mcp is not None:
            created = await self._tool("create_order", intent.to_tool_args())
            tool_log.append(f"[create_order]\n{json.dumps(created, indent=1)[:2500]}")
            order = (created.get("order") or {})
            if order.get("order_id"):
                order_ids.append(order["order_id"])
            sources.append("[mcp] oms.create_order")

            if order.get("status") != "REJECTED":
                matched = await self._tool("run_matching", {})
                tool_log.append(f"[run_matching]\n{json.dumps(matched, indent=1)[:2500]}")
                sources.append("[mcp] oms.run_matching")

            if order.get("order_id"):
                final = await self._tool("get_order", {"order_id": order["order_id"]})
                tool_log.append(f"[get_order]\n{json.dumps(final, indent=1)[:2500]}")
                sources.append("[mcp] oms.get_order")

            portfolio = await self._tool("portfolio_summary", {})
            tool_log.append(f"[portfolio_summary]\n{json.dumps(portfolio, indent=1)[:2500]}")
            sources.append("[mcp] oms.portfolio_summary")

            self.context.add_section("execution-trace", "\n\n".join(tool_log), priority=90)
        else:
            self.context.add_section("execution-trace",
                                     "(no MCP client: order was parsed but not executed)",
                                     priority=90)

        # 4. Single inference call -> execution report.
        messages = self.context.build_messages()
        messages.append({"role": "user",
                         "content": prompts.EXECUTION_USER_TEMPLATE.format(
                             instruction=instruction, intent=intent.describe())})
        report = await asyncio.to_thread(
            self.inference.chat, messages,
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
        )
        return ExecutionReport(
            instruction=instruction, report=report, sources=sources,
            rounds=1, order_ids=order_ids, context_stats=self.context.stats(),
        )

    # -- ReAct loop ------------------------------------------------------
    def _parse_action(self, text: str) -> dict[str, Any] | None:
        matches = _FENCE_RE.findall(text)
        if not matches:
            return None
        try:
            action = json.loads(matches[-1])
        except json.JSONDecodeError:
            return None
        return action if isinstance(action, dict) and "action" in action else None

    async def _execute_action(self, action: dict[str, Any]) -> str:
        name = action.get("action", "")
        args = action.get("args", {}) or {}
        try:
            if name == "rag_search" and self.rag is not None:
                return self.rag.query_context(args.get("query", ""), top_k=self.rag_top_k) or "(no hits)"
            if name == "parse_intent":
                intent = self.parse_intent(args.get("instruction", ""))
                return f"Parsed intent: {intent.describe()}\nTool args: {json.dumps(intent.to_tool_args())}"
            if name.startswith("mcp.") and self.mcp is not None:
                _, server, tool = name.split(".", 2)
                data = await self._tool(tool, args) if server == self.mcp_server \
                    else await self.mcp.call_tool(server, tool, args)
                return json.dumps(data, indent=1)[:3000]
            return f"(tool '{name}' unavailable)"
        except Exception as exc:  # noqa: BLE001
            return f"(tool '{name}' error: {exc})"

    async def run_react(self, instruction: str) -> ExecutionReport:
        self.context.set_system(prompts.REACT_SYSTEM)
        if self.mcp is not None:
            try:
                self.context.add_section("mcp-tools",
                                         await self.mcp.tools_prompt_block(), priority=95)
            except Exception:  # noqa: BLE001
                pass

        history: list[dict[str, str]] = [
            {"role": "user", "content": f"Trader instruction: {instruction}\nBegin."}
        ]
        sources: list[str] = []
        order_ids: list[str] = []
        rounds = 0
        final_answer = ""
        for rounds in range(1, self.react_max_rounds + 1):
            messages = self.context.build_messages() + history
            reply = await asyncio.to_thread(
                self.inference.chat, messages,
                model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            )
            action = self._parse_action(reply)
            if action is None:
                final_answer = reply
                break
            if action.get("action") == "final":
                final_answer = action.get("answer", "")
                break
            observation = await self._execute_action(action)
            history.append({"role": "assistant", "content": reply})
            history.append({"role": "user",
                            "content": f"Observation:\n{observation}\nContinue with the next json action."})
            sources.append(f"[round {rounds}] {action.get('action')}")
        else:
            final_answer = final_answer or "(max rounds reached without a final report)"

        return ExecutionReport(
            instruction=instruction, report=final_answer, sources=sources,
            rounds=rounds, order_ids=order_ids, context_stats=self.context.stats(),
        )
