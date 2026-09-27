# omsagent — Architecture & Design Decisions

> Source notes for the technical deep-dive deck. Prototype disclaimer: all
> market data is simulated; nothing here connects to a real venue.

## 1. Why an agentic layer over an OMS
A traditional OMS is a CRUD GUI over an order blotter. The agentic layer lets a
trader express intent in natural language ("buy 500 AAPL limit 230 gtc") and
have the system parse it, check compliance, execute against a venue, and write
an execution report — with every step recorded as tool calls that can be
audited. The agent never touches orders except through the MCP tool boundary,
so the OMS core stays a plain, testable Python domain model.

## 2. Package layout (`src/omsagent/`)
- `oms/` — pure domain logic: models, order book, compliance, fill simulator,
  simulated market. Zero I/O, zero ML dependencies → unit-testable.
- `servers/oms_mcp.py` — MCP server exposing the domain as 9 tools.
- `mcp_client/` — multi-server MCP client (stdio/SSE).
- `agent/` — intent parsing + staged workflow + ReAct loop.
- `inference/` — OpenAI-compatible FastAPI server (echo + openai_compatible).
- `context/` — priority-section context manager with token budgeting.
- `rag/` — chunking, embeddings, vector store; seeded with ops-manual docs.
- `search/` — web search → context (kept for parity; not central to OMS flows).

## 3. Order model: dataclass + enums, explicit state machine
`Order` is a dataclass; `Side`, `OrderType`, `TimeInForce`, `OrderStatus` are
str enums. Status transitions are explicit methods (`apply_fill`,
`acknowledge`, `cancel_order`) rather than free-form status assignment, so
illegal transitions (e.g. amending a FILLED order) raise instead of silently
corrupting state. `OPEN_STATUSES` / `TERMINAL_STATUSES` sets make "is this
order still working?" a one-line check everywhere.

## 4. Lifecycle: NEW → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED
Two-phase commit mirrors real venues: `create_order` stages the order
(running compliance), `run_matching` acknowledges then fills. Amendments to
quantity/limit re-run the full compliance suite — a size increase that would
breach a limit must be rejected even if the original order passed.

## 5. ComplianceEngine: fail-closed, config-driven
Seven rules (POSITIVE_QTY, RESTRICTED_SYMBOL, INVALID_TIF,
MAX_ORDER_NOTIONAL $5M, MAX_POSITION_NOTIONAL $25M, MAX_DAILY_NOTIONAL $100M,
PRICE_COLLAR ±10%), each returning a machine-readable `Violation(rule,
message)`. Rejections carry the rule codes so the agent can explain *why* and
suggest a fix (reduce size, move limit inside the collar). No override path
exists in the prototype — fail-closed by design; a real desk would add a
risk-committee override workflow.

## 6. FillSimulator + SimulatedMarket: determinism as a feature
The market is a seeded random walk per symbol (`seed:symbol:tick` hashed into
a PRNG), so quotes are reproducible across runs — demos and tests never flake.
Market orders fill at touch (ask/bid) split into ≤3 partial prints for
realism; limit orders fill only on price touch; stop orders trigger then fill
as market; IOC cancels the remainder; FOK is all-or-nothing. This is a
deliberate stand-in: the matching interface is isolated so a real venue
adapter (FIX/websocket) can replace it without touching compliance or the
agent.

## 7. Portfolio accounting
Average-cost basis: buys re-average, sells realize P&L against average cost.
`portfolio_summary()` reports cash, market value, unrealized/realized P&L and
total equity. Daily gross traded notional accumulates in the compliance
engine for the MAX_DAILY_NOTIONAL rule.

## 8. MCP server: tools as the only mutation path
`servers/oms_mcp.py` holds a process-global `OrderBook`; the 9 tools are thin
wrappers returning JSON strings (MCP transports text cleanly; the client
parses back to dicts). Decision: the agent cannot import the OMS core
directly in the reference deployment — it must go through tools, which is what
makes the execution trace auditable and what would let the OMS live on a
different host later. Trade-off: state is per server process; two clients
spawned via stdio each get their own blotter. A production version needs a
shared store (DB) behind the tools.

## 9. MCP client: multi-server, transport-agnostic
`MCPClientManager` reads `configs/mcp_servers.yaml`, spawns stdio servers or
dials SSE, discovers tools, and renders a `tools_prompt_block()` that the
ReAct system prompt injects — so the model always sees the true tool schema.
Pinned `mcp<2`: v2 removed `FastMCP`, which the server is written against.

## 10. Intent parsing: regex, not an LLM
`parse_intent` uses regexes for side/qty/symbol/limit/stop/TIF. Deliberate:
deterministic, instant, unit-testable, and it works with the echo backend.
An LLM extractor would be more flexible ("pick up five hundred Apple") but
adds latency, cost, and nondeterminism to the most safety-critical step —
turning words into orders. The staged pipeline keeps parsing outside the
model; ReAct exposes it as a `parse_intent` tool so the model can still use it.

## 11. Dual agent modes
- `run_order_workflow` (staged): parse → RAG ops-manual lookup → MCP
  create/match/inspect/portfolio → single inference call → execution report.
  Fully deterministic; runs against the echo backend for demos/tests.
- `run_react`: the model drives `parse_intent`, `rag_search`, `mcp.oms.*`
  round by round until it emits `final`. Needs a real model; this is where
  tool-calling behavior actually gets exercised.

## 12. Inference server: OpenAI-compatible, backend-swappable
`POST /v1/chat/completions` (plus `/v1/models`, `/health`, `/v1/summarize`)
with `OMSAGENT_BACKEND=echo|openai_compatible`. Echo returns a canned
response describing the prompt — enough to integration-test the whole loop
with no model. `openai_compatible` forwards to any OpenAI-schema server
(Ollama, vLLM, llama.cpp). Betting on the OpenAI schema maximizes backend
choice; the agent code never knows which model serves it.

## 13. Context manager: priority sections under a token budget
Sections (`order-intent` p100, `execution-trace` p90, `ops-manual` p80…)
are assembled highest-priority-first within `max_tokens`; on overflow it
summarizes then truncates. For OMS flows this matters because the execution
trace (full order JSON + fills) can dwarf the instruction — priorities keep
the intent and latest state while shedding older detail first.

## 14. RAG: zero-dependency default, upgrade path
Default embeddings are deterministic hashing (no model download); optional
sentence-transformers + FAISS via extras. Corpus is three sample ops-manual
docs (order types, compliance rules, lifecycle). Retrieval grounds the
agent's report in desk policy ("price collar ±10%") instead of model memory.

## 15. Testing: 18 tests, seeds fixed
`test_oms.py` (11): fill lifecycle, buy→sell realized P&L, all four
rejection rules, working limit order, amend/cancel, terminal-order guard,
stop trigger, portfolio shape. `test_agent_oms.py` (7): intent parsing
variants, RAG ingest, full staged workflow through a real MCP stdio server,
rejected-order trace. Market seeds are fixed so fills are deterministic.

## 16. Limitations & roadmap
In-memory only (no persistence); per-process blotter; simulated data;
single-threaded matching; no authentication on the inference server or MCP
transport; no partial-fill market impact. Roadmap: Postgres-backed order
store, real market-data/venue adapters (FIX), pre-trade risk service
separation, order-state event bus, authN/Z, latency metrics, and a proper
evaluation harness for the ReAct policy.
