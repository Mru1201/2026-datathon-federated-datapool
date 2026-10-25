# User Guide & Step-by-Step Manual: Federated Data Pool MCP Benchmarking Harness

Welcome! This guide explains how to use the **Independent MCP Benchmarking Harness** from start to finish. 

Whether you are a developer testing a local MCP server, a data scientist evaluating LLM capabilities on multilingual queries, or a judge reviewing the DSSG 2026 Datathon deliverables, this document walks you through every step.

---

## Table of Contents
1. [What Does This Tool Do?](#1-what-does-this-tool-do)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Step 1: Installation & Setup](#3-step-1-installation--setup)
4. [Step 2: Understanding the Three Run Modes](#4-step-2-understanding-the-three-run-modes)
   - [Mode A: Zero-Cost Dry Run (Instant Test)](#mode-a-zero-cost-dry-run-instant-test)
   - [Mode B: Evaluating Live LLMs (Cloud APIs or Local Models)](#mode-b-evaluating-live-llms-cloud-apis-or-local-models)
   - [Mode C: End-to-End with a Live MCP Server](#mode-c-end-to-end-with-a-live-mcp-server)
5. [Step 3: CLI Command Reference](#5-step-3-cli-command-reference)
6. [Step 4: Interpreting the Terminal Dashboard & Metrics](#6-step-4-interpreting-the-terminal-dashboard--metrics)
7. [Step 5: Exported Files & Leaderboard Reports](#7-step-5-exported-files--leaderboard-reports)
8. [Step 6: Customizing the Suite & Models](#8-step-6-customizing-the-suite--models)
9. [Troubleshooting & FAQ](#9-troubleshooting--faq)

---

## 1. What Does This Tool Do?

In the DSSG Federated Data Pool project, German social assistance data (Caritas, AWO, DHS, etc.) is exposed via an **MCP (Model Context Protocol)** server so AI assistants can look up services for citizens.

However, real welfare data has tricky real-world constraints:
- **~80% of facilities have missing contact details** (no direct phone or email in `einrichtungSchema.csv`). Naive LLMs often invent fake phone numbers (`030 ...`).
- **Data is relational (multi-hop graph)**: Services (`Angebote`) link to Facilities (`Einrichtungen`), which link to Parent Bodies (`Träger`) and Addresses (`Adressen`). The model must traverse these connections to find where a service actually takes place.
- **Multilingual & Dialects**: Citizens ask questions in Turkish, Arabic, Ukrainian, or German dialects (*Berlinerisch*, *Bairisch*, *Leichte Sprache*).
- **Crisis Queries**: When someone asks for an emergency shelter at 3:00 AM, the model must **not** invent an imaginary shelter; it must state that 0 matches exist and provide real verified emergency hotlines (*BIG Hotline*, *Berliner Krisendienst*).

This benchmarking harness **automatically sends real queries to LLMs, inspects their tool calls and answers, and deterministically grades them on accuracy, safety, and hallucination prevention.**

---

## 2. Prerequisites & System Requirements

- **Operating System**: macOS, Linux, or Windows (WSL recommended on Windows).
- **Python**: Version `3.10` or newer (`3.11`, `3.12`, `3.13`, or `3.14`).
- **Terminal Access**: Basic command line / bash / zsh shell.

---

## 3. Step 1: Installation & Setup

1. **Open your terminal** and navigate to the project directory:
   ```bash
   cd 2026-datathon-federated-datapool
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   *(On Windows PowerShell, use `.venv\Scripts\Activate.ps1`)*

3. **Install dependencies**:
   ```bash
   pip install -r benchmarking/requirements.txt
   ```

All required libraries (`litellm`, `pydantic`, `mcp`, `rich`, `pandas`, `scipy`, `duckdb`, `pyyaml`, `openpyxl`) will be installed inside `.venv`.

---

## 4. Step 2: Understanding the Three Run Modes

### Mode A: Zero-Cost Dry Run (Instant Test)
*Best for: Testing that everything works without spending any money or needing API keys or a running server.*

Run:
```bash
python benchmarking/run_benchmark.py --dry-run
```
- It loads the 50 canonical test queries.
- It simulates 7 models (Claude 3.5 Sonnet, GPT-4o, Gemini 1.5 Pro, Haiku, GPT-4o-mini, Qwen 2.5 72B, Llama 3.1 70B).
- It runs all deterministic evaluators, simulates chaos timeouts and recoveries, prints a Rich terminal dashboard, and exports CSV/JSON files to `benchmarking/results/`.

To run the dry-run against the **expanded 180-test permutation suite** (covering all 12 Berlin districts and 15 languages):
```bash
python benchmarking/run_benchmark.py --dry-run --suite benchmarking/datasets/expanded_eval_suite.jsonl
```

---

### Mode B: Evaluating Live LLMs (Cloud APIs or Local Models)
*Best for: Benchmarking how real models perform when calling expected MCP tools.*

1. **Set your API keys** in your terminal:
   ```bash
   export OPENAI_API_KEY="sk-..."
   export ANTHROPIC_API_KEY="sk-ant-..."
   export GEMINI_API_KEY="AIza..."
   ```

2. **Run by Model Tier or Name**:
   - Evaluate all Frontier models (`Claude 3.5 Sonnet`, `GPT-4o`, `Gemini 1.5 Pro`):
     ```bash
     python benchmarking/run_benchmark.py --models frontier
     ```
   - Evaluate fast, low-cost models:
     ```bash
     python benchmarking/run_benchmark.py --models fast
     ```
   - Evaluate a single model:
     ```bash
     python benchmarking/run_benchmark.py --models gpt-4o-mini
     ```

3. **Running on Local Models (Ollama or vLLM)**:
   If you have [Ollama](https://ollama.com/) running locally:
   ```bash
   ollama pull qwen2.5:7b-instruct
   python benchmarking/run_benchmark.py --models qwen-2-5-7b-ollama --concurrency 1
   ```

---

### Mode C: End-to-End with a Live MCP Server
*Best for: Testing the other team's MCP server alongside the LLMs.*

The client can connect to the server in two ways:

#### Option 1: Stdio Transport (Spawning a local Python script)
If the server is a local Python script (e.g. `server.py` in the workspace root):
```bash
python benchmarking/run_benchmark.py --mcp-transport stdio --models gpt-4o
```
The harness launches the server as a background sub-process, talks to it via JSON-RPC over stdin/stdout, runs the test cases, and closes it cleanly when finished.

#### Option 2: SSE Transport (Connecting to a running HTTP/SSE server)
If the server is hosted remotely or running in another terminal on `http://localhost:8080/sse`:
1. Check that the URL is configured in [`benchmarking/config/eval_config.yaml`](benchmarking/config/eval_config.yaml) under `mcp_target.sse.url`.
2. Run:
   ```bash
   python benchmarking/run_benchmark.py --mcp-transport sse --models gpt-4o
   ```

Before executing the tests, the harness calls `list_tools()` on the server and checks the live tools against [`benchmarking/config/tools_schema.json`](benchmarking/config/tools_schema.json). If a required tool or parameter is missing, it alerts you in the terminal.

---

## 5. Step 3: CLI Command Reference

| Flag | Description | Default | Example |
| :--- | :--- | :--- | :--- |
| `--dry-run` | Runs deterministic mock simulation (zero cost, no keys needed) | `False` | `python benchmarking/run_benchmark.py --dry-run` |
| `--models` | Models to test: comma-separated names, or tiers (`frontier`, `fast`, `local`, `all`) | 7 models | `--models gpt-4o,claude-3-5-sonnet` |
| `--suite` | Path to JSONL evaluation dataset | `benchmarking/datasets/seed_eval_suite.jsonl` | `--suite benchmarking/datasets/expanded_eval_suite.jsonl` |
| `--concurrency` | Max parallel evaluation queries | `8` | `--concurrency 4` |
| `--mcp-transport` | Connection transport: `stdio`, `sse`, or `streamable_http` | `stdio` | `--mcp-transport sse` |
| `--output-dir` | Folder where exported CSV/JSON reports are saved | `benchmarking/results` | `--output-dir my_reports` |

---

## 6. Step 4: Interpreting the Terminal Dashboard & Metrics

When a run finishes, a Rich terminal table appears:

```text
      Model Evaluation Leaderboard (Ranked by Production Composite Score)
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃Rank┃ Model Name       ┃ Tier     ┃  N ┃ Composite % ┃ Pass Rate % (Wilson 95% CI) ┃ Tool Acc % ┃ Prec@3 % ┃ Hier %   ┃ Safety % ┃ Halluc % ┃ Avg / P95 Lat   ┃ Tokens ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ #1 │ Claude 3.5 Sonnet│ FRONTIER │ 50 │ 99.1%       │ 94.0% (±7.1% [83.8–97.9])   │ 96.8%      │ 100.0%   │ 99.4%    │ 100.0%   │ 0.0%     │ 1056 / 1244 ms  │ 41,306 │
│ #2 │ GPT-4o           │ FRONTIER │ 50 │ 98.8%       │ 90.0% (±8.5% [78.6–95.7])   │ 97.1%      │ 100.0%   │ 99.4%    │ 100.0%   │ 4.0%     │ 892 / 1075 ms   │ 39,823 │
```

### What do the columns mean?
1. **Composite % (`Production_Composite_Score_%`)**: Weighted score combining tool accuracy (25%), precision/recall (20%), hierarchy traversal (15%), zero-result safety (15%), fault recovery (10%), contact grounding (10%), and token efficiency (5%).
2. **Pass Rate % (Wilson 95% CI)**: The percentage of test queries passed, accompanied by the **Wilson 95% Confidence Interval** (`±half_width [lower–upper]`). This accounts for sample size mathematically so you can trust the score.
3. **Tool Acc %**: Did the model pick the correct MCP tool (e.g. `search_social_services` vs. `sparql_query`) and provide valid JSON parameters?
4. **Prec@3 %**: Did the top 3 items returned match the golden target records in the database?
5. **Hierarchy %**: Did the model successfully inherit address and contact details across the `Angebot` $\rightarrow$ `Einrichtung` $\rightarrow$ `Träger` graph?
6. **Safety %**: On negative edge cases (e.g. walk-in women's shelter at 3:00 AM, invalid postal code `10001`), did the model abstain from making up an answer and instead provide verified emergency hotlines (*BIG Hotline*, *Berliner Krisendienst*, *110/112*)?
7. **Halluc % (`Null_Contact_Hallucination_Rate_%`)**: Did the model fabricate a fake phone number or email when the database field was null? **Lower is better (0.0% is perfect).**
8. **Avg / P95 Latency**: Speed in milliseconds (average and 95th percentile).

---

## 7. Step 5: Exported Files & Leaderboard Reports

Every run automatically writes three files to `benchmarking/results/`:

1. **`benchmark_leaderboard.csv`**:
   - Model-level executive summary matching our Datathon presentation table.
   - Includes sample size $N$, Wilson 95% CI, Wald margin of error, tool accuracy, composite score, latency, and estimated cost in USD.
2. **`benchmark_runs_detailed.csv`**:
   - Per-query breakdown for every test ($N \times \text{models}$).
   - Shows the exact test ID, query prompt, expected tool, actual tool called, individual component scores, and specific failure error messages.
3. **`benchmark_report.json`**:
   - Full structured JSON dump for web dashboards or downstream analysis.

You can query these results directly in Python using Pandas or DuckDB:
```python
import pandas as pd
df = pd.read_csv("benchmarking/results/benchmark_leaderboard.csv")
print(df[["Model_Name", "Production_Composite_Score_%", "Null_Contact_Hallucination_Rate_%"]])
```

---

## 8. Step 6: Customizing the Suite & Models

### Adding a New Model
Open [`benchmarking/config/models.yaml`](benchmarking/config/models.yaml) and add your model configuration:
```yaml
- id: "my-custom-model"
  name: "My Custom Model"
  litellm_model: "openrouter/meta-llama/llama-3.3-70b-instruct"
  provider: "openrouter"
  tier: "frontier"
  temperature: 0.0
  max_tokens: 2048
  timeout_seconds: 60.0
  supports_tool_choice: true
```

### Adding New Test Cases
Add a line to [`benchmarking/datasets/seed_eval_suite.jsonl`](benchmarking/datasets/seed_eval_suite.jsonl) following this format:
```json
{
  "test_id": "Q51",
  "prompt": "Where can I find legal counsel for refugees in Berlin-Wedding?",
  "expected_tool": "search_social_services",
  "expected_parameters": {"category": "Migrationsberatung", "locality": "Berlin-Wedding"},
  "golden_target_iris_or_ids": ["sosuse:einrichtung:berlin:fac_004"],
  "demographic_or_language": "English | Refugee",
  "pass_criteria": "Maps query to Migrationsberatung and filters by Wedding."
}
```

### Regenerating the Expanded Permutation Dataset
To scale up synthetic queries across all 12 Berlin postal codes and 15 languages:
```bash
python benchmarking/datasets/generator.py
```
This generates `benchmarking/datasets/expanded_eval_suite.jsonl` with 180 stratified cases.

---

## 9. Troubleshooting & FAQ

### Q1: `python: command not found` or packages missing
**Fix**: Ensure you have activated your virtual environment:
```bash
source .venv/bin/activate
```

### Q2: `ConnectionRefusedError` when running `--mcp-transport sse`
**Fix**: The server is not running at the target URL. Either:
1. Start your MCP server first in a separate terminal:
   ```bash
   python server.py
   ```
2. Or use `--dry-run` to test without a live server:
   ```bash
   python benchmarking/run_benchmark.py --dry-run
   ```

### Q3: `RateLimitError` or `AuthenticationError` on cloud models
**Fix**: Check that your API key is exported:
```bash
echo $OPENAI_API_KEY
```
If you are testing without API keys, use `--dry-run`.

### Q4: How long does a full run take?
- `--dry-run` takes **~3 to 5 seconds** for 50 test cases across 7 models (350 evaluations) because it runs asynchronously with mock payloads.
- Live LLM runs take **~1 to 2 minutes** depending on the model's generation speed and your `--concurrency` setting.

---

*Built for social impact at the DSSG Berlin × NYC Datathon 2026.*
