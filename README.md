# EVOLVE

<p align="center">
  <a href="figure/EVOLVE.pdf"><img src="https://img.shields.io/badge/overview-EVOLVE.pdf-red" alt="EVOLVE overview"></a>
</p>

**EVOLVE** is a lifelong tool evolution framework for AI agent safety. As the agent encounters risky scenarios one by one, EVOLVE continuously (1) analyzes potential risks, (2) reuses / retrieves previously evolved security tools from a lifelong library, (3) generates new tools when none match, (4) fuses them with existing ones, (5) executes the tool to verify, and (6) audits the result to decide whether the tool should be kept. The library accumulates over time and improves both accuracy and efficiency on subsequent samples.

## Pipeline

Each sample flows through five stages:

1. **Analysis** — `AnalysisAgent` reasons about the scenario and decides whether external tool-checking is needed (`need_tools: yes/no`).
2. **Retrieval / Generation** — if needed, retrieve the most-similar tool from the lifelong library; if no good match exists, generate a new tool.
3. **Fusion** — `FusionAgent` merges newly generated tools with retrieved ones to avoid duplication.
4. **Execute** — `ExecutorAgent` runs the selected tool against `(request, agent_actions)`.
5. **Audit** — `AuditorAgent` reviews the tool's correctness and risk, deciding whether to keep it in the lifelong library.

## Repository layout

```
agents/            # Analysis / Fusion / Executor / Auditor / Simulate agents
prompts/           # Base prompts + benchmark-specific prompts (R-Judge, ASSEBench, AgentHarm)
data/              # Benchmark data (R-Judge Application, ASSEBench, AgentHarm, …)
pipeline.py        # End-to-end EVOLVE pipeline entrypoint
configs.py         # Model / API config (reads keys from env vars)
utils.py           # Data IO, lifelong library update, token tracking helpers
figure/EVOLVE.pdf  # Framework overview figure
script/            # Shell scripts for running benchmarks
```

The following are gitignored (large / regeneratable / separate):
`results/`, `logs/`, `lifelong_library/` (runtime snapshots), `DEFEND/` (baseline comparison code), `tool_eval/`, `demo/`, `run_evolution.{py,sh}`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # if present
```

API keys are read from environment variables (see [configs.py](configs.py)):

```bash
export DEEPSEEK_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export OPENAI_API_KEY=...
```

## Run

```bash
python pipeline.py --benchmark rjudge --domain Application
```

See `script/` for per-benchmark entrypoints.

## License

See repository for license details.
