"""Clean up LangSmith resources after the pocket-polly demo.

Resets the demo to a clean state so it can be run again without re-running setup:
  1. Resets baseline dataset to the original 3 examples
  2. Deletes Engine-created datasets (pocket-polly-engine-{user}-*)
  3. Deletes all experiments — CI/CD generates fresh before/after on every PR
  4. Removes Engine-added online evaluators (keeps the 5 registered by setup.py)
  5. Force-resets the fork's main branch to upstream (removes Engine's merged PR)

Usage:
    python -m scripts.cleanup
"""

import json
import os
import subprocess
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

_demo_user = os.getenv("DEMO_USER", "").strip()
DATASET_NAME = f"pocket-polly-demo-dataset-{_demo_user}" if _demo_user else "pocket-polly-demo-dataset"
PROJECT_NAME = os.getenv("LANGSMITH_PROJECT", "pocket-polly-demo")


# ── 1. Reset dataset ───────────────────────────────────────────────────────────

def reset_dataset() -> None:
    """Reset dataset to the original 3 examples by deleting all and re-uploading.

    Engine may add examples and re-tag baseline, so we don't rely on the tag.
    Instead, delete everything and re-upload the canonical 3 from dataset.py.
    """
    from langsmith import Client
    from evals.dataset import EXAMPLES

    print(f"\n[1/5] Resetting dataset '{DATASET_NAME}' to original 3 examples...")
    ls_client = Client()

    datasets = list(ls_client.list_datasets(dataset_name=DATASET_NAME))
    if not datasets:
        print(f"  Dataset '{DATASET_NAME}' not found. Skipping.")
        return

    dataset = datasets[0]
    existing = list(ls_client.list_examples(dataset_id=dataset.id))
    if existing:
        ls_client.delete_examples([e.id for e in existing])
        print(f"  Deleted {len(existing)} example(s).")

    ls_client.create_examples(
        dataset_id=dataset.id,
        inputs=[e["input"] for e in EXAMPLES],
        outputs=[e["output"] for e in EXAMPLES],
        metadata=[e.get("metadata", {}) for e in EXAMPLES],
    )
    print(f"  Re-uploaded {len(EXAMPLES)} original examples.")


def delete_engine_datasets() -> None:
    """Delete Engine-created datasets matching pocket-polly-engine-{DEMO_USER}-*."""
    from langsmith import Client

    prefix = f"pocket-polly-engine-{_demo_user}-" if _demo_user else "pocket-polly-engine-"
    print(f"\n[2/5] Removing Engine datasets matching '{prefix}*'...")
    ls_client = Client()

    deleted = 0
    for dataset in ls_client.list_datasets():
        if dataset.name.startswith(prefix):
            ls_client.delete_dataset(dataset_id=dataset.id)
            print(f"  Deleted dataset '{dataset.name}'")
            deleted += 1

    if deleted == 0:
        print("  No Engine datasets found.")


# ── 3. Delete experiments ─────────────────────────────────────────────────────

def delete_ci_experiments() -> None:
    """Delete all experiments linked to the dataset.

    CI/CD generates fresh before/after experiments on every PR, so there is
    no experiment worth keeping between demos.
    """
    from langsmith import Client

    print(f"\n[3/5] Removing all experiments from dataset '{DATASET_NAME}'...")

    ls_client = Client()
    datasets = list(ls_client.list_datasets(dataset_name=DATASET_NAME))
    if not datasets:
        print(f"  Dataset '{DATASET_NAME}' not found — skipping.")
        return

    dataset_id = datasets[0].id
    experiments = list(ls_client.list_projects(reference_dataset_id=dataset_id))
    if not experiments:
        print("  No experiments found.")
        return

    deleted = 0
    for exp in experiments:
        for attempt in range(3):
            try:
                ls_client.delete_project(project_name=exp.name)
                print(f"  Deleted '{exp.name}'")
                deleted += 1
                time.sleep(1.0)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    print(f"  Rate limited, waiting 5s...")
                    time.sleep(5.0)
                else:
                    print(f"  Failed to delete '{exp.name}': {e}")
                    break

    print(f"  Deleted {deleted} experiment(s).")


# ── 4. Delete Engine-added online evaluators ───────────────────────────────────

def delete_engine_evaluators(api_key: str) -> None:
    """Delete only the online evaluators Engine added — leave our setup.py ones intact.

    setup.py saves the run rule IDs it created to .demo_state.json.
    Any run rule scoped to our project that is NOT in that list was added by
    Engine and is safe to remove. Rules belonging to other projects are ignored.
    """
    from langsmith import Client

    print(f"\n[4/5] Removing Engine-added online evaluators...")

    try:
        with open(".demo_state.json") as f:
            state = json.load(f)
        our_rule_ids = set(state.get("run_rule_ids", []))
    except FileNotFoundError:
        print("  Warning: .demo_state.json not found — run 'python -m scripts.setup' first.")
        print("  Skipping online evaluator cleanup.")
        return

    # Get our project ID so we only touch rules scoped to our project
    ls_client = Client()
    projects = list(ls_client.list_projects())
    project = next((p for p in projects if p.name == PROJECT_NAME), None)
    if not project:
        print(f"  Warning: project '{PROJECT_NAME}' not found. Skipping.")
        return
    project_id = str(project.id)

    resp = requests.get(
        "https://api.smith.langchain.com/api/v1/runs/rules",
        headers={"x-api-key": api_key},
    )
    if resp.status_code != 200:
        print(f"  Could not list run rules ({resp.status_code}). Skipping.")
        return

    deleted = 0
    for rule in resp.json():
        # Only consider rules tied to our project
        if rule.get("session_id") != project_id:
            continue
        if rule["id"] not in our_rule_ids:
            r = requests.delete(
                f"https://api.smith.langchain.com/api/v1/runs/rules/{rule['id']}",
                headers={"x-api-key": api_key},
            )
            if r.status_code in (200, 204):
                print(f"  Deleted Engine run rule '{rule.get('display_name', rule['id'])}'")
                deleted += 1

    if deleted == 0:
        print("  No Engine-added evaluators found.")
    else:
        print(f"  Deleted {deleted} Engine-added evaluator(s).")


# ── 5. Reset fork to upstream main ────────────────────────────────────────────

def reset_fork_to_upstream() -> None:
    """Force-reset the fork's main branch to match upstream langchain-samples/engine-demo.

    This removes Engine's merged PR from the fork's history, restoring the
    buggy agent state so the demo can be run again.
    """
    upstream = "langchain-samples/engine-demo"

    print(f"\n[5/5] Resetting fork main branch to upstream '{upstream}'...")

    # Get the fork's remote URL from git
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("  Warning: could not determine fork remote. Skipping.")
        return

    fork_url = result.stdout.strip()
    # Parse owner/repo from SSH or HTTPS URL
    if "github.com:" in fork_url:
        fork_repo = fork_url.split("github.com:")[1].removesuffix(".git")
    elif "github.com/" in fork_url:
        fork_repo = fork_url.split("github.com/")[1].removesuffix(".git")
    else:
        print(f"  Warning: unrecognised remote URL '{fork_url}'. Skipping.")
        return

    # Get upstream main SHA
    result = subprocess.run(
        ["gh", "api", f"repos/{upstream}/commits/main", "--jq", ".sha"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  Warning: could not fetch upstream SHA ({result.stderr.strip()}). Skipping.")
        return
    upstream_sha = result.stdout.strip()

    # Force-reset fork main to upstream SHA
    result = subprocess.run(
        ["gh", "api", f"repos/{fork_repo}/git/refs/heads/main",
         "-X", "PATCH",
         "-f", f"sha={upstream_sha}",
         "-F", "force=true"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  Reset '{fork_repo}' main to upstream ({upstream_sha[:8]}).")
    else:
        print(f"  Warning: reset failed ({result.stderr.strip()}).")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("Error: LANGSMITH_API_KEY not set.")
        sys.exit(1)

    print(f"Cleaning up demo for user '{_demo_user or 'default'}'...")
    print(f"  Dataset:  {DATASET_NAME}")
    print(f"  Project:  {PROJECT_NAME}")

    reset_dataset()
    delete_engine_datasets()
    delete_ci_experiments()
    delete_engine_evaluators(api_key)
    reset_fork_to_upstream()

    print(f"\nCleanup complete. Ready for the next demo.")


if __name__ == "__main__":
    main()
