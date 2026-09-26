"""End-to-end OMS demo: natural-language order instructions -> execution reports.

Starts the inference server client (echo backend by default), ingests the
sample ops docs into RAG, connects the OMS MCP server over stdio, then runs
a few staged order workflows:

  python examples/run_demo.py [instruction ...]

Examples:
  python examples/run_demo.py "buy 500 AAPL"
  python examples/run_demo.py "buy 500 AAPL limit 200" "sell 100 TSLA"
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omsagent.agent import OMSAgent
from omsagent.context import ContextManager
from omsagent.inference import InferenceClient
from omsagent.mcp_client import MCPClientManager
from omsagent.rag import RAGPipeline


async def main(instructions: list[str]) -> None:
    inference = InferenceClient(base_url=os.getenv("OMSAGENT_URL", "http://127.0.0.1:8080"))
    context = ContextManager(max_tokens=6000)

    rag = RAGPipeline()
    docs_dir = os.path.join(os.path.dirname(__file__), "docs")
    rag.ingest_dir(docs_dir)
    print(f"[rag] ingested sample ops docs from {docs_dir}")

    mcp_config = {
        "servers": {
            "oms": {
                "transport": "stdio",
                "command": sys.executable,  # venv interpreter: package is importable
                "args": ["-m", "omsagent.servers.oms_mcp"],
                "env": {},
            }
        }
    }
    async with MCPClientManager(mcp_config) as mcp:
        tools = [t.qualified_name for t in await mcp.list_all_tools()]
        print(f"[mcp] connected tools: {tools}")

        agent = OMSAgent(inference=inference, context=context, rag=rag, mcp=mcp)
        for instruction in instructions:
            print("=" * 70)
            print(f"INSTRUCTION: {instruction}")
            print("=" * 70)
            try:
                report = await agent.run_order_workflow(instruction)
            except ValueError as exc:
                print(f"Could not execute: {exc}")
                continue
            print(report.report)
            print(f"\n(sources: {', '.join(report.sources)})")
            print(f"(orders: {', '.join(report.order_ids) or 'none'})\n")


if __name__ == "__main__":
    instructions = sys.argv[1:] or [
        "buy 500 AAPL",
        "buy 2000 AAPL limit 150",   # expect PRICE_COLLAR reject
        "sell 100 TSLA limit 300",
    ]
    asyncio.run(main(instructions))
