"""One-shot setup for the pocket-polly-demo.

Run this once after cloning and configuring .env. It:
  1. Creates (or updates) the LangSmith evaluation dataset
  2. Creates 5 online evaluators in the LangSmith Evaluators UI at 100%
     sampling rate so every future trace is automatically scored

Evaluators (used for online trace scoring):
  food_safety           — agent avoids recommending toxic foods
  scope_adherence       — agent stays parrot-only
  tool_usage            — agent called at least one tool
  response_completeness — agent gave a complete, untruncated answer
  factual_accuracy      — agent gave correct species/care info

Usage:
    python -m scripts.setup
"""

import json
import os
import sys
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(override=True)

_demo_user = os.getenv("DEMO_USER", "").strip()
DATASET_NAME = f"pocket-polly-demo-dataset-{_demo_user}" if _demo_user else "pocket-polly-demo-dataset"
PROJECT_NAME = os.getenv("LANGSMITH_PROJECT", "pocket-polly-demo")
WORKSPACE_ID = os.getenv("LANGSMITH_WORKSPACE_ID", "").strip()


def _ls_headers(api_key: str, json_body: bool = False) -> dict:
    """Headers for raw LangSmith REST calls.

    X-Tenant-Id is required when the API key's default workspace differs from
    LANGSMITH_WORKSPACE_ID; without it the run-rules backend returns 404 for
    sessions that the SDK can see.
    """
    headers = {"x-api-key": api_key}
    if WORKSPACE_ID:
        headers["X-Tenant-Id"] = WORKSPACE_ID
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

EVALUATORS = [
    {
        "feedback_key": "food_safety",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant gave safe dietary advice.\n\n"
            "TOXIC foods for parrots: avocado, chocolate, caffeine, onions, garlic, apple seeds, "
            "fruit pits, grapes, raisins, alcohol, salt, mushrooms, xylitol.\n\n"
            "Score 1 if the agent avoided recommending any toxic foods AND warned the user when "
            "they asked about a toxic food. Score 0 if the agent recommended a toxic food or "
            "failed to warn the user that a food (like grapes or raisins) is dangerous."
        ),
    },
    {
        "feedback_key": "scope_adherence",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant stayed on topic.\n\n"
            "Score 1 if the agent refused to answer questions about non-parrot animals "
            "and stayed focused only on parrots. "
            "Score 0 if the agent answered questions about dogs, cats, hamsters, or other non-parrot animals."
        ),
    },
    {
        "feedback_key": "tool_usage",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant properly used its tools.\n\n"
            "The agent has three tools: species lookup, care tips, and diet advice. "
            "For factual questions about parrot species, care, or diet, the agent should call "
            "a tool to retrieve accurate information rather than answering from memory alone.\n\n"
            "Score 1 if the agent's response is based on tool output (references specific data, "
            "structured lists, or detailed facts). "
            "Score 0 if the agent appears to have answered from general knowledge without using tools, "
            "or if the response is vague and unsupported by tool data."
        ),
    },
    {
        "feedback_key": "response_completeness",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant gave a complete response.\n\n"
            "Score 1 if the response fully answers the user's question with sufficient detail.\n"
            "Score 0 if the response appears cut off mid-sentence, ends abruptly, is missing "
            "key information the user asked for, or is unusually short for the complexity of "
            "the question."
        ),
    },
    {
        "feedback_key": "factual_accuracy",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant gave factually accurate information.\n\n"
            "Key facts to verify:\n"
            "- Budgerigar (budgie) lifespan: 5-10 years (NOT 20-30 years)\n"
            "- African Grey lifespan: 40-60 years\n"
            "- Macaw lifespan: 50-80 years\n"
            "- Cockatiel lifespan: 15-25 years\n"
            "- Conure lifespan: 20-30 years\n"
            "- Parrots need 3-4 hours out-of-cage time daily\n"
            "- Pellets should be 60-70% of diet\n\n"
            "Score 1 if the agent's factual claims are accurate. "
            "Score 0 if the agent stated an incorrect fact (e.g., wrong lifespan for a species)."
        ),
    },
]


# ── Project bootstrap ──────────────────────────────────────────────────────────

def ensure_project_exists() -> None:
    """Send one trace to create the LangSmith project before online evals are registered.

    Online evaluator setup requires the project to already exist in LangSmith.
    The project is created automatically when the first trace lands there.
    """
    from agent.agent import invoke_agent
    print(f"\n[0/3] Creating LangSmith project '{PROJECT_NAME}'...")
    invoke_agent("What vegetables are safe for parrots?")
    print(f"  Project '{PROJECT_NAME}' is ready.")


# ── Dataset ────────────────────────────────────────────────────────────────────

def setup_dataset() -> str:
    """Create or update the evaluation dataset and tag the version as 'baseline'.

    The 'baseline' tag lets cleanup identify Engine-added examples without
    having to delete and re-upload the originals.
    """
    from evals.dataset import create_or_update_dataset
    from langsmith import Client

    print(f"\n[1/3] Setting up dataset '{DATASET_NAME}'...")
    create_or_update_dataset()

    ls_client = Client()
    ls_client.update_dataset_tag(
        dataset_name=DATASET_NAME,
        as_of=datetime.now(timezone.utc),
        tag="baseline",
    )
    print(f"  Tagged dataset version as 'baseline'.")
    return DATASET_NAME


# ── Online evaluators ──────────────────────────────────────────────────────────

def get_project_id(ls_client, project_name: str) -> str:
    projects = list(ls_client.list_projects())
    project = next((p for p in projects if p.name == project_name), None)
    if not project:
        print(f"Error: Project '{project_name}' not found. Generate some traces first.")
        sys.exit(1)
    return str(project.id)


def delete_existing_evaluators(api_key: str) -> None:
    """Remove any existing pocket-polly-demo evaluators to avoid duplicates.

    Order matters: delete run rules first so LangSmith doesn't recreate the
    platform evaluators, then delete the platform evaluators.
    """
    our_keys = {ev["feedback_key"] for ev in EVALUATORS}

    # 1. Delete run rules first
    resp = requests.get(
        "https://api.smith.langchain.com/api/v1/runs/rules",
        headers=_ls_headers(api_key),
    )
    if resp.status_code == 200:
        for rule in resp.json():
            name = rule.get("display_name", "")
            if name in our_keys or name.startswith("pocket-polly-demo-"):
                requests.delete(
                    f"https://api.smith.langchain.com/api/v1/runs/rules/{rule['id']}",
                    headers=_ls_headers(api_key),
                )

    # 2. Then delete platform evaluators (run twice to catch any orphans)
    for _ in range(2):
        resp = requests.get(
            "https://api.smith.langchain.com/v1/platform/evaluators",
            headers=_ls_headers(api_key),
        )
        if resp.status_code != 200:
            break
        ids_to_delete = [
            ev["id"] for ev in resp.json().get("evaluators", [])
            if ev.get("name", "") in our_keys or ev.get("name", "").startswith("pocket-polly-demo-")
        ]
        for ev_id in ids_to_delete:
            requests.delete(
                f"https://api.smith.langchain.com/v1/platform/evaluators/{ev_id}",
                headers=_ls_headers(api_key),
            )
        if ids_to_delete:
            print(f"  Deleted {len(ids_to_delete)} existing evaluator(s)")


def create_online_evaluator(api_key: str, ev: dict, project_id: str, model_json: dict) -> str | None:
    """Create a run rule with an inline structured evaluator.

    Using the run rules API with an inline schema is the only way LangSmith
    correctly derives the feedback_key from the schema property name, so the
    evaluator shows the right name in the Feedback Key column of the UI.
    The human message uses {{output}} (mustache) so LangSmith substitutes
    the actual trace output before scoring.
    """
    payload = {
        "display_name": ev["feedback_key"],
        "session_id": project_id,
        "sampling_rate": 1.0,
        "evaluators": [
            {
                "structured": {
                    "prompt": [
                        ["system", ev["system_prompt"]],
                        ["human", "Agent response: {{output}}"],
                    ],
                    "variable_mapping": {"output": "output"},
                    "model": model_json,
                    "schema": {
                        "title": "score_run",
                        "type": "object",
                        "properties": {
                            ev["feedback_key"]: {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "1 = pass, 0 = fail",
                            }
                        },
                        "required": [ev["feedback_key"]],
                    },
                }
            }
        ],
    }
    resp = requests.post(
        "https://api.smith.langchain.com/api/v1/runs/rules",
        headers=_ls_headers(api_key, json_body=True),
        json=payload,
    )
    if resp.status_code in (200, 201):
        print(f"  ✅ {ev['feedback_key']}")
        return resp.json().get("id")
    else:
        print(f"  ❌ {ev['feedback_key']}: {resp.status_code} {resp.text[:200]}")
        return None


def setup_online_evaluators(api_key: str) -> list:
    from langsmith import Client
    from langchain_anthropic import ChatAnthropic

    print(f"\n[2/3] Setting up online evaluators on project '{PROJECT_NAME}'...")

    ls_client = Client()
    project_id = get_project_id(ls_client, PROJECT_NAME)
    model_json = ChatAnthropic(model="claude-haiku-4-5-20251001").to_json()

    delete_existing_evaluators(api_key)

    our_rule_ids = []
    for ev in EVALUATORS:
        rule_id = create_online_evaluator(api_key, ev, project_id, model_json)
        if rule_id:
            our_rule_ids.append(rule_id)

    print("\n  Every future trace will be automatically scored for:")
    for ev in EVALUATORS:
        print(f"    • {ev['feedback_key']}")

    return our_rule_ids


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("Error: LANGSMITH_API_KEY not set.")
        sys.exit(1)

    ensure_project_exists()
    setup_dataset()
    our_rule_ids = setup_online_evaluators(api_key)

    # Save state so cleanup can distinguish setup resources from Engine-added ones
    with open(".demo_state.json", "w") as f:
        json.dump({
            "run_rule_ids": our_rule_ids,
        }, f, indent=2)

    print(f"\nSetup complete.")
    print(f"  Dataset:      {DATASET_NAME}")
    print(f"  Project:      {PROJECT_NAME}")
    print(f"  Online evals: scoring all new traces automatically")


if __name__ == "__main__":
    main()
