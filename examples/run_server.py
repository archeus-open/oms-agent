"""Run the omsagent inference server.

Backend: OMSAGENT_BACKEND=echo (default, for tests/demos) or openai_compatible
(pointing at Ollama / vLLM / llama.cpp via OPENAI_* env vars).
"""

from omsagent.inference.server import main

if __name__ == "__main__":
    raise SystemExit(main())
