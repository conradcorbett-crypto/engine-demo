"""Resolve the Engine-created dataset name for CI from PR metadata or env.

Resolution order:
  1. ENGINE_DATASET_NAME env var
  2. PR label: engine-dataset:<name>
  3. PR body HTML comment: <!-- engine-dataset: name -->
  4. Branch name slug: engine/<slug> -> pocket-polly-engine-{DEMO_USER}-<slug>

Usage:
    python -m scripts.resolve_engine_dataset
    python -m scripts.resolve_engine_dataset --event-path /path/to/event.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


ENGINE_DATASET_LABEL_PREFIX = "engine-dataset:"
BODY_COMMENT_PATTERN = re.compile(
    r"<!--\s*engine-dataset:\s*(.+?)\s*-->",
    re.IGNORECASE,
)


def _from_env() -> str | None:
    name = os.getenv("ENGINE_DATASET_NAME", "").strip()
    return name or None


def _from_labels(labels: list[dict]) -> str | None:
    for label in labels:
        label_name = label.get("name", "") if isinstance(label, dict) else str(label)
        if label_name.startswith(ENGINE_DATASET_LABEL_PREFIX):
            return label_name[len(ENGINE_DATASET_LABEL_PREFIX):].strip() or None
    return None


def _from_body(body: str) -> str | None:
    match = BODY_COMMENT_PATTERN.search(body or "")
    if match:
        return match.group(1).strip() or None
    return None


def _from_branch(branch: str, demo_user: str) -> str | None:
    branch = (branch or "").strip()
    if not branch.startswith("engine/"):
        return None
    slug = branch.removeprefix("engine/").strip("/")
    if not slug:
        return None
    if demo_user:
        return f"pocket-polly-engine-{demo_user}-{slug}"
    return f"pocket-polly-engine-{slug}"


def resolve_engine_dataset(
    *,
    event_path: str | None = None,
    demo_user: str | None = None,
) -> str:
    """Return the Engine dataset name or raise ValueError with guidance."""
    if name := _from_env():
        return name

    event_path = event_path or os.getenv("GITHUB_EVENT_PATH", "")
    demo_user = (demo_user if demo_user is not None else os.getenv("DEMO_USER", "")).strip()

    if event_path and os.path.isfile(event_path):
        with open(event_path) as f:
            event = json.load(f)

        pull_request = event.get("pull_request") or {}
        if name := _from_labels(pull_request.get("labels") or []):
            return name
        if name := _from_body(pull_request.get("body") or ""):
            return name
        head_ref = (pull_request.get("head") or {}).get("ref", "")
        if name := _from_branch(head_ref, demo_user):
            return name

    raise ValueError(
        "Could not resolve Engine dataset name. Set ENGINE_DATASET_NAME, add a PR label "
        f"'{ENGINE_DATASET_LABEL_PREFIX}<name>', embed '<!-- engine-dataset: <name> -->' "
        "in the PR body, or use branch name 'engine/<slug>'."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve Engine dataset name from PR metadata")
    parser.add_argument("--event-path", type=str, default=None, help="GitHub event JSON path")
    parser.add_argument("--demo-user", type=str, default=None, help="Override DEMO_USER for branch slug")
    args = parser.parse_args()

    try:
        name = resolve_engine_dataset(event_path=args.event_path, demo_user=args.demo_user)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(name)


if __name__ == "__main__":
    main()
