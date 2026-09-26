"""omsagent: prototype agentic AI order management system (OMS) for a hedge fund."""

from .agent import OMSAgent, ExecutionReport
from .context import ContextManager
from .inference import InferenceClient
from .oms import OrderBook, ComplianceEngine, FillSimulator
from .rag import RAGPipeline
from .search import WebSearch

__all__ = [
    "OMSAgent", "ExecutionReport",
    "ContextManager", "InferenceClient",
    "OrderBook", "ComplianceEngine", "FillSimulator",
    "RAGPipeline", "WebSearch",
]
__version__ = "0.1.0"
