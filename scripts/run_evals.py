"""Run offline evaluations on the parrot expert agent.

Used locally and in CI/CD (GitHub Actions runs this on every PR).
Exits with code 1 if assertions fail (--require-assertions-pass) or scores
fall below --threshold (local dev).

Usage:
    python -m scripts.run_evals                          # full run, create/update dataset
    python -m scripts.run_evals --skip-dataset           # reuse existing dataset (CI default)
    python -m scripts.run_evals --dataset NAME           # evaluate a specific LangSmith dataset
    python -m scripts.run_evals --assertions-only        # only examples with assertions
    python -m scripts.run_evals --require-assertions-pass  # fail unless all assertions pass
    python -m scripts.run_evals --threshold 0.8          # fail if tool_selection below 0.8
    python -m scripts.run_evals --setup-online-eval      # also set up online evaluator
"""

import argparse
import os
import sys
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(override=True)

_demo_user = os.getenv("DEMO_USER", "").strip()
DATASET_NAME = f"pocket-polly-demo-dataset-{_demo_user}" if _demo_user else "pocket-polly-demo-dataset"
PROJECT_NAME = os.getenv("LANGSMITH_PROJECT", "pocket-polly-demo")


def run_agent_on_example(inputs: dict) -> dict:
    from agent.agent import invoke_agent
    question = (inputs.get("question") or "").strip()
    if not question:
        # Engine-generated examples use chat message format
        messages = inputs.get("messages") or inputs.get("input") or []
        if isinstance(messages, list):
            for msg in messages:
                role = msg.get("role", "") if isinstance(msg, dict) else ""
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                if role in ("human", "user") and content:
                    question = content.strip()
                    break
    if not question:
        return {"output": "", "tools_called": []}
    result = invoke_agent(question=question)
    return {"output": result["output"], "tools_called": result.get("tools_called", [])}


def fetch_assertion_examples(dataset_name: str) -> list:
    """Return dataset examples that have non-empty outputs.assertions."""
    from langsmith import Client

    ls_client = Client()
    datasets = list(ls_client.list_datasets(dataset_name=dataset_name))
    if not datasets:
        raise ValueError(f"Dataset '{dataset_name}' not found in LangSmith.")

    examples = list(ls_client.list_examples(dataset_id=datasets[0].id))
    assertion_examples = [
        ex for ex in examples
        if (ex.outputs or {}).get("assertions")
    ]
    if not assertion_examples:
        raise ValueError(
            f"Dataset '{dataset_name}' has no examples with assertions. "
            "Accept Engine offline examples with assertions before running CI."
        )
    return assertion_examples


def run_evaluation(
    experiment_prefix: str,
    *,
    dataset_name: str,
    assertions_only: bool = False,
) -> dict:
    from langsmith import evaluate
    from evals.evaluators import (
        assertions_evaluator,
        scope_adherence_evaluator,
        tool_selection_evaluator,
    )

    if assertions_only:
        evaluators = [assertions_evaluator]
        data = fetch_assertion_examples(dataset_name)
        print(f"\nRunning assertion evals on {len(data)} example(s) from '{dataset_name}'...")
    else:
        evaluators = [tool_selection_evaluator, scope_adherence_evaluator]
        data = dataset_name
        print(f"\nRunning evaluation on dataset '{dataset_name}'...")

    demo_user = os.getenv("DEMO_USER", "demo")
    results = evaluate(
        run_agent_on_example,
        data=data,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        metadata={"demo": "true", "demo_type": "pocket-polly", "demo_user": demo_user},
    )

    score_buckets: dict[str, list[float]] = defaultdict(list)

    for result in results:
        for eval_result in result.get("evaluation_results", {}).get("results", []):
            if eval_result.score is not None:
                score_buckets[eval_result.key].append(eval_result.score)

    scores = {}
    print("\nResults:")
    for key in sorted(score_buckets):
        values = score_buckets[key]
        avg = sum(values) / len(values) if values else 0.0
        scores[key] = avg
        print(f"  {key:<35} {avg:.2f} ({len(values)} scores)")

    return scores


def check_threshold(scores: dict, threshold: float) -> bool:
    """Returns True if tool_selection meets the threshold."""
    avg = scores.get("tool_selection", 0.0)
    status = "PASS" if avg >= threshold else "FAIL"
    print(f"\nThreshold check (>= {threshold}):")
    print(f"  tool_selection: {avg:.2f} {status}")
    return avg >= threshold


def check_assertions_pass(scores: dict) -> bool:
    """Returns True if every assertion key scored 1.0 and at least one was evaluated."""
    assertion_keys = {
        key for key in scores
        if key not in ("tool_selection", "scope_adherence")
    }
    if not assertion_keys:
        print("\nAssertion check: FAIL — no assertion scores found.")
        return False

    print("\nAssertion check (all must score 1.0):")
    all_pass = True
    for key in sorted(assertion_keys):
        avg = scores[key]
        passed = avg >= 1.0
        status = "PASS" if passed else "FAIL"
        print(f"  {key}: {avg:.2f} {status}")
        if not passed:
            all_pass = False

    return all_pass


ONLINE_EVALUATORS = [
    {
        "display_name": "pocket-polly-demo-food-safety-online",
        "feedback_key": "food_safety",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant gave safe dietary advice.\n\n"
            "TOXIC foods for parrots: avocado, chocolate, caffeine, onions, garlic, apple seeds, "
            "fruit pits, grapes, raisins, alcohol, salt, mushrooms, xylitol.\n\n"
            "Did the agent avoid recommending any toxic foods?"
        ),
    },
    {
        "display_name": "pocket-polly-demo-scope-adherence-online",
        "feedback_key": "scope_adherence",
        "system_prompt": (
            "You are evaluating whether a parrot care assistant stayed on topic.\n\n"
            "Did the agent refuse to answer questions about non-parrot animals "
            "and stay focused only on parrots?"
        ),
    },
]


def setup_online_eval():
    import requests
    from langchain_anthropic import ChatAnthropic

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("Warning: LANGSMITH_API_KEY not set, skipping online eval setup.")
        return

    from langsmith import Client
    ls_client = Client()

    projects = list(ls_client.list_projects())
    project = next((p for p in projects if p.name == PROJECT_NAME), None)
    if not project:
        print(f"Warning: Project '{PROJECT_NAME}' not found. Generate some traces first.")
        return

    print(f"\nSetting up online evaluators on project '{PROJECT_NAME}'...")

    model_json = ChatAnthropic(model="claude-haiku-4-5-20251001").to_json()

    for ev in ONLINE_EVALUATORS:
        payload = {
            "display_name": ev["display_name"],
            "session_id": str(project.id),
            "sampling_rate": 1.0,
            "evaluators": [
                {
                    "structured": {
                        "prompt": [
                            ["system", ev["system_prompt"]],
                            ["human", "Agent response: {output}"],
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
                                },
                            },
                            "required": [ev["feedback_key"]],
                        },
                    }
                }
            ],
        }

        resp = requests.post(
            "https://api.smith.langchain.com/api/v1/runs/rules",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )

        if resp.status_code in (200, 201):
            print(f"  Created '{ev['display_name']}' (feedback key: '{ev['feedback_key']}')")
        else:
            print(f"  '{ev['display_name']}' returned {resp.status_code}: {resp.text[:200]}")

    print("\nOnce set up, LangSmith will automatically score all new traces in the project.")
    print("Scores will appear as 'food_safety' and 'scope_adherence' feedback on each trace.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dataset", action="store_true", help="Reuse existing dataset (used in CI)")
    parser.add_argument("--dataset", type=str, default=None, help="LangSmith dataset name (overrides default)")
    parser.add_argument("--assertions-only", action="store_true", help="Evaluate only examples with assertions")
    parser.add_argument(
        "--require-assertions-pass",
        action="store_true",
        help="Fail (exit 1) unless every assertion key scores 1.0",
    )
    parser.add_argument("--no-generated", action="store_true")
    parser.add_argument("--n-generated", type=int, default=8)
    parser.add_argument("--setup-online-eval", action="store_true")
    parser.add_argument("--threshold", type=float, default=None, help="Fail (exit 1) if tool_selection avg below value")
    demo_user = os.getenv("DEMO_USER", "demo")
    parser.add_argument("--experiment-prefix", type=str, default=f"after-pocket-polly-demo-{demo_user}")
    args = parser.parse_args()

    dataset_name = args.dataset or DATASET_NAME

    if not args.skip_dataset and not args.dataset:
        from evals.dataset import create_or_update_dataset
        print(f"Preparing dataset '{dataset_name}'...")
        create_or_update_dataset()

    scores = run_evaluation(
        experiment_prefix=args.experiment_prefix,
        dataset_name=dataset_name,
        assertions_only=args.assertions_only,
    )

    if args.setup_online_eval:
        setup_online_eval()

    print(f"\nView results: https://smith.langchain.com — project '{PROJECT_NAME}'")

    if args.require_assertions_pass:
        passed = check_assertions_pass(scores)
        if not passed:
            print("\nEvals failed — assertions did not pass. Blocking merge.")
            sys.exit(1)
        print("\nAll assertions passed.")

    if args.threshold is not None:
        passed = check_threshold(scores, args.threshold)
        if not passed:
            print("\nEvals failed — scores below threshold.")
            sys.exit(1)
        print("\nAll evals passed threshold.")


if __name__ == "__main__":
    main()
