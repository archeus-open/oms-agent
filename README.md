# omsagent — Agentic AI Order Management System (Prototype)

A prototype **order management system (OMS) for a hedge fund**, driven by an
agentic AI layer. The agent takes natural-language trader instructions
(`"buy 500 AAPL limit 230 gtc"`), runs them through pre-trade compliance,
executes them against a simulated venue, and writes an execution report.

> **Prototype disclaimer.** Market data is a deterministic simulation, fills
> are simulated, and nothing here touches a real venue. Do not use for real
> trading.

## Architecture

```
 trader instruction ("buy 500 AAPL limit 230")
        │
        ▼
 ┌─────────────┐   parse_intent    ┌──────────────────┐
 │  OMSAgent   │ ─────────────────▶│  OrderIntent       │
 │ (staged /   │                   │  BUY 500 AAPL     │
 │  ReAct)     │                   │  LIMIT @ 230 GTC  │
 └──────┬──────┘                   └──────────────────┘
        │  rag_search (ops manual: order types, compliance rules, lifecycle)
        │  mcp.oms.* tool calls
        ▼
 ┌─────────────────────────────────────────────────┐
 │ MCP server: oms                                 │
 │  create_order → ComplianceEngine (pre-trade)    │
 │  run_matching → FillSimulator (venue sim)       │
 │  amend_order / cancel_order / get_order /       │
 │  list_orders / get_positions / portfolio_summary │
 │  get_quote                                      │
 └──────────────────────┬──────────────────────────┘
                        ▼
        ┌───────────────────────────┐
        │ OrderBook: orders, fills, │
        │ positions, cash, P&L      │
        └───────────────────────────┘
        │
        ▼  context assembly (intent + ops-manual + execution trace)
 ┌─────────────┐
 │ Inference   │  OpenAI-compatible server (/v1/chat/completions)
 │ server      │  backends: echo (mock) | openai_compatible (Ollama/vLLM/…)
 └─────────────┘
        │
        ▼  execution report
```

### Components

| Component | Path | What it does |
|---|---|---|
| Inference server | `src/omsagent/inference/` | OpenAI-compatible FastAPI server (`/v1/chat/completions`, `/v1/summarize`), echo + openai_compatible backends |
| Context management | `src/omsagent/context/` | Priority sections, token budgeting, summarize-on-overflow |
| MCP client | `src/omsagent/mcp_client/` | Multi-server stdio/SSE client, tool discovery + calls |
| OMS MCP server | `src/omsagent/servers/oms_mcp.py` | 9 order-management tools over a stateful `OrderBook` |
| OMS core | `src/omsagent/oms/` | Order lifecycle, `ComplianceEngine`, `FillSimulator`, positions/P&L, simulated market feed |
| RAG pipeline | `src/omsagent/rag/` | Chunking, hashing/sentence-transformer embeddings, numpy/FAISS stores; seeded with ops-manual docs |
| Web search | `src/omsagent/search/` | ddgs finance search → context (optional; not needed for OMS flows) |
| Agent | `src/omsagent/agent/` | `run_order_workflow` (staged) + `run_react` (ReAct tool loop), natural-language intent parsing |

### Order lifecycle

`NEW → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED`, with `REJECTED`
(compliance), `CANCELLED`, `EXPIRED` as terminal alternatives. Only working
orders can be amended/cancelled; amendments re-run compliance.

### Pre-trade compliance (prototype policy)

`POSITIVE_QTY · RESTRICTED_SYMBOL · INVALID_TIF · MAX_ORDER_NOTIONAL ($5M) ·
MAX_POSITION_NOTIONAL ($25M) · MAX_DAILY_NOTIONAL ($100M) · PRICE_COLLAR (±10%)`

## Quickstart

```bash
make install        # create .venv and install
make test           # 18 pytest tests

# Pure-Python OMS demo (no server needed):
make demo

# Full agentic demo (needs the inference server running):
make server &                                   # echo backend by default
make agent-demo                                 # or pass instructions:
# OMSAGENT_URL=http://127.0.0.1:8080 .venv/bin/python examples/run_demo.py \
#   "buy 500 AAPL" "sell 100 TSLA limit 300 gtc"
```

With a real model (e.g. Ollama), point the server at it and use ReAct:

```bash
OMSAGENT_BACKEND=openai_compatible OPENAI_BASE_URL=http://localhost:11434/v1 \
  OPENAI_MODEL_NAME=llama3.1 make server
```

## Tool calling

Staged mode calls, in order: `create_order → run_matching → get_order →
portfolio_summary`, with a RAG lookup of the ops manual first. ReAct mode lets
the model drive the same tools (`mcp.oms.*`) plus `parse_intent` and
`rag_search` until it emits a final execution report.

## Layout

```
configs/mcp_servers.yaml   # MCP server config
examples/
  docs/                    # sample ops-manual RAG corpus
  run_server.py            # inference server entrypoint
  run_demo.py              # agentic end-to-end demo
  run_oms_direct.py        # direct OrderBook demo (no server)
src/omsagent/              # the package
tests/                     # 18 pytest tests
```

## License

MIT — prototype for research and education only.
