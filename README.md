# engine-demo

A parrot expert chatbot with intentional bugs, built to demonstrate LangSmith Engine's ability to identify issues in agent traces and propose fixes via PR. The agent answers questions about parrot care using three tools: `lookup_species`, `get_care_tips`, and `get_diet_advice`.

## What this demos

1. **Engine identifies bugs** — the agent has bugs in the prompt and code that cause bad responses
2. **Engine proposes a PR fix** — targets the root cause code and opens a PR on your fork
3. **Engine proposes offline examples and online evals to add** — expand dataset coverage and monitoring with one click
4. **Offline evals in CI/CD** — the PR can't merge until eval scores pass a threshold
5. **Before/after scores in LangSmith** — both "before" and "after" experiments created automatically by CI when Engine opens a PR

## The bugs

Bugs are spread across three files so Engine has to reason about code, not just prompts:

| Bug | File | Effect | Caught by |
|-----|------|--------|-----------|
| Bad system prompt | `agent/prompts.py` | Answers any animal; answers from memory instead of calling tools | `tool_usage`, `scope_adherence` |
| Grapes missing from toxic list | `agent/tools.py` | Agent tells users raisins are safe for parrots | `food_safety` |
| Wrong budgie lifespan | `agent/tools.py` | Returns "20-30 years" instead of the correct "5-10 years" | `factual_accuracy` |
| `max_tokens=300` | `agent/agent.py` | Truncates responses on complex questions | `response_completeness` |

## Setup

**1. Fork and clone this repo**

**2. Create a virtual environment**
```bash
uv sync
source .venv/bin/activate
```

Or with pip:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**3. Configure environment**
```bash
cp .env.example .env
```

Edit `.env`:
```
ANTHROPIC_API_KEY=your-key
LANGSMITH_API_KEY=your-demo-workspace-api-key
LANGSMITH_PROJECT=pocket-polly-demo-yourname
LANGSMITH_WORKSPACE_ID=your-demo-workspace-id
LANGCHAIN_TRACING_V2=true
DEMO_USER=your-name
```

> Use a unique `LANGSMITH_PROJECT` name per person (e.g. `pocket-polly-demo-morgan`). Multiple demo-ers sharing the same project name will mix traces and online evaluators. The project is created automatically on first use.

`DEMO_USER` additionally scopes your dataset and experiment names:
- Dataset: `pocket-polly-demo-dataset-morgan`
- Experiments: `pocket-polly-demo-morgan-<timestamp>`

**4. Run one-shot setup**
```bash
python -m scripts.setup
```

This does three things in one command:
1. **Creates the LangSmith project** by sending one trace (required before online evaluators can be registered)
2. **Creates the dataset** `pocket-polly-demo-dataset-<your-name>` with 3 curated test cases, then tags that version as `baseline` in LangSmith
3. **Creates 5 online evaluators** in the LangSmith Evaluators UI at 100% sampling rate — every future trace is automatically scored for `food_safety`, `scope_adherence`, `tool_usage`, `response_completeness`, and `factual_accuracy`. Their run rule IDs are saved to `.demo_state.json` so cleanup can tell them apart from evaluators Engine adds.

Only needs to be run once. Between demos, run `python -m scripts.cleanup` instead.

**5. Generate traces**
```bash
python -m scripts.generate_traces
```

Runs 13 single-turn queries and 3 multi-turn threaded conversations through the buggy agent to populate LangSmith with trace and thread variety beyond the dataset examples.

**6. Add GitHub secrets** (for CI/CD)

In your fork: Settings → Secrets → Actions → add `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_WORKSPACE_ID`, and `DEMO_USER`.

> **Important:** When pasting secrets, make sure there are no trailing newlines or spaces.

**7. Enable GitHub Actions**

In your fork: Actions → (if prompted) enable workflows. GitHub disables Actions on forks by default — this step is required for offline evals to run on PRs.

**8. Connect Engine**

In LangSmith Engine, connect your LangSmith project (`LANGSMITH_PROJECT`) and your GitHub fork so Engine can read traces and open PRs against your repo.

## Demo flow

### Before the demo

```bash
# One-shot setup: creates dataset, sets up online evaluators
python -m scripts.setup

# Generate more traces including threads
python -m scripts.generate_traces

# Start the chat UI
streamlit run app.py
```

### During the demo

1. Show PocketPolly UI — ask questions (species lookup, care tips, diet advice, etc.)
2. Show traces in LangSmith with online eval scores (`food_safety`, `scope_adherence`, etc.)
3. Engine analyzes traces and identifies root causes across prompt and code
4. Add Engine-suggested offline examples — show ability to edit in annotation queue
5. Engine opens a PR on your fork
6. GitHub Actions runs evals on main (before experiment) and the PR branch (after experiment) — after scores pass ✅
7. Merge the PR
8. Add Engine-suggested online eval
9. Show the experiments in LangSmith — before/after score comparison

### After the demo

```bash
python -m scripts.cleanup
```

## Scripts

| Script | What it does |
|--------|-------------|
| `python -m scripts.setup` | One-shot setup: creates dataset and creates 5 online evaluators |
| `python -m scripts.generate_traces` | Runs 13 single-turn queries + 3 multi-turn threads through the buggy agent |
| `python -m scripts.run_evals` | Runs offline evals against the dataset and prints scores |
| `python -m scripts.run_evals --skip-dataset` | Re-runs evals against existing dataset (used in CI) |
| `python -m scripts.run_evals --threshold 0.7` | Exits with code 1 if scores < 0.7 (used in CI) |
| `python -m scripts.cleanup` | Resets demo to clean state — see Cleanup section |
| `streamlit run app.py` | Start the PocketPolly chat UI |

## Evaluators

Two LLM-as-judge evaluators run in CI (offline). Claude Haiku scores each 0 or 1:

- **`tool_selection`** — did the agent ground its response in tool output rather than answering from memory? Goes 0→1 when the bad system prompt is fixed.
- **`scope_adherence`** — did the agent stay parrot-only and decline non-parrot questions?

## Online Evaluators

Online evaluators run automatically on every trace as it arrives in LangSmith. This gives Engine a continuous signal on live traffic, not just offline evals on a fixed dataset.

Five online evaluators are registered by `python -m scripts.setup`: `food_safety`, `scope_adherence`, `tool_usage`, `response_completeness`, and `factual_accuracy`.

## CI/CD

`.github/workflows/evals.yml` runs automatically on every PR to `main`.

Add these secrets to your repo (Settings → Secrets → Actions):
- `ANTHROPIC_API_KEY`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGSMITH_WORKSPACE_ID`
- `DEMO_USER`

`DEMO_USER` and `LANGSMITH_PROJECT` must match what you used locally — that's how CI finds the right dataset.

```
PR opened → GitHub Actions → run_evals --skip-dataset --threshold 0.7
                                          ↓
                               scores < 0.7 → ❌ blocks merge
                               scores ≥ 0.7 → ✅ mergeable
```

CI runs evals on both the base branch (creating the "before" experiment) and the PR branch (creating the "after" experiment) in LangSmith automatically. Because `--skip-dataset` fetches the existing dataset from LangSmith by name, any examples Engine adds to the dataset are included in the eval run automatically.

## Repo structure

```
agent/
├── prompts.py        # buggy system prompt (Bug 1 — Engine fixes this)
├── tools.py          # species lookup, care tips, diet advice (Bugs 2 & 3)
└── agent.py          # LangGraph ReAct agent (Bug 4 — max_tokens too low)

evals/
├── dataset.py        # creates per-user LangSmith dataset (3 curated examples)
└── evaluators.py     # 2 LLM-as-judge offline evaluators (used in CI)

scripts/
├── setup.py          # one-shot setup: dataset + online evaluators
├── generate_traces.py    # populate LangSmith with extra traces and threads
├── run_evals.py          # offline evals + CI threshold check
└── cleanup.py            # resets demo to clean state after presentation

.github/workflows/
└── evals.yml         # CI/CD: runs evals on every PR to main

app.py                # PocketPolly chat UI (Streamlit)
```

## Cleanup

Run after the demo to reset everything for the next presenter:

```bash
python -m scripts.cleanup
```

This does four things:
1. **Resets dataset to original 3 examples** — deletes all examples and re-uploads the canonical 3, removing anything Engine added
2. **Deletes all experiments** — CI/CD generates fresh before/after experiments on every PR, so nothing needs to be preserved between demos
3. **Removes Engine-added online evaluators** — uses saved run rule IDs from `.demo_state.json` to delete only evaluators Engine added, leaving the 5 from `setup.py` in place
4. **Resets the fork's main branch to upstream** — force-resets to remove Engine's merged PR, restoring the buggy agent state

After cleanup, the demo is ready to run again — no need to re-run `setup.py`.
