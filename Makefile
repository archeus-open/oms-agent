.PHONY: install test demo server clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[test]"

test:
	.venv/bin/python -m pytest tests/ -q

server:
	.venv/bin/python examples/run_server.py

demo:
	.venv/bin/python examples/run_oms_direct.py

agent-demo:
	OMSAGENT_URL=http://127.0.0.1:8080 .venv/bin/python examples/run_demo.py

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true
	rm -rf .pytest_cache src/*.egg-info
