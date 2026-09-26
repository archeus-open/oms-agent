"""Tests for the OMS agent: intent parsing, staged workflow, RAG docs."""

import os
import sys

import pytest

from omsagent.agent import OMSAgent
from omsagent.context import ContextManager
from omsagent.inference import InferenceClient
from omsagent.mcp_client import MCPClientManager
from omsagent.rag import RAGPipeline

DOCS = os.path.join(os.path.dirname(__file__), "..", "examples", "docs")

# Point the MCP stdio server at this interpreter so the venv-installed
# package is importable inside the spawned server process.
MCP_CONFIG = {
    "servers": {
        "oms": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "omsagent.servers.oms_mcp"],
            "env": {},
        }
    }
}


def _agent(**kw):
    inference = InferenceClient(base_url="http://127.0.0.1:1")  # unused; echo not needed
    # monkeypatch chat to avoid network: return canned text
    inference.chat = lambda messages, **k: "EXECUTION-REPORT-OK"
    return OMSAgent(inference=inference, context=ContextManager(max_tokens=4000), **kw)


def test_parse_intent_market():
    intent = OMSAgent.parse_intent("buy 500 AAPL")
    assert (intent.side, intent.quantity, intent.symbol) == ("BUY", 500, "AAPL")
    assert intent.order_type == "MARKET" and intent.time_in_force == "DAY"


def test_parse_intent_limit_gtc():
    intent = OMSAgent.parse_intent("sell 100 TSLA limit 240 gtc")
    assert intent.order_type == "LIMIT" and intent.limit_price == 240.0
    assert intent.time_in_force == "GTC" and intent.side == "SELL"


def test_parse_intent_stop():
    intent = OMSAgent.parse_intent("buy 1000 MSFT stop 420")
    assert intent.order_type == "STOP" and intent.stop_price == 420.0


def test_parse_intent_invalid():
    with pytest.raises(ValueError):
        OMSAgent.parse_intent("what is the weather?")


def test_rag_ingests_ops_docs():
    rag = RAGPipeline()
    n = rag.ingest_dir(DOCS)
    assert n > 0
    ctx = rag.query_context("pre-trade compliance rules", top_k=2)
    assert ctx and "compliance" in ctx.lower()


@pytest.mark.asyncio
async def test_staged_workflow_via_mcp():
    rag = RAGPipeline()
    rag.ingest_dir(DOCS)
    agent = _agent(rag=rag)
    async with MCPClientManager(MCP_CONFIG) as mcp:
        agent.mcp = mcp
        report = await agent.run_order_workflow("buy 100 AAPL")
    assert report.report == "EXECUTION-REPORT-OK"
    assert len(report.order_ids) == 1
    assert any("mcp" in s for s in report.sources)
    assert any("rag" in s for s in report.sources)


@pytest.mark.asyncio
async def test_staged_workflow_rejected_order():
    agent = _agent()
    async with MCPClientManager(MCP_CONFIG) as mcp:
        agent.mcp = mcp
        report = await agent.run_order_workflow("buy 100 GME")  # restricted
    assert report.order_ids, "rejected orders still get an id"
    # trace should mention REJECTED
    trace = agent.context._sections["execution-trace"].content
    assert "REJECTED" in trace
