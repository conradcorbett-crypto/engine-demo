"""Evaluators for the parrot expert demo."""

import json
from anthropic import Anthropic

_anthropic_client = None


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic()
    return _anthropic_client


def _llm_judge(system_prompt: str, output: str) -> float:
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16,
        system=system_prompt,
        messages=[{"role": "user", "content": (
            f"Agent response: {output}\n\n"
            "Answer ONLY 'yes' (score 1) or 'no' (score 0)."
        )}],
    )
    answer = response.content[0].text.strip().lower()
    return 1.0 if answer.startswith("yes") else 0.0


def tool_selection_evaluator(run, example) -> dict:
    """Did the agent call a tool or give a clean off-topic refusal?

    Score: 1 = tools were called, or question was not parrot-related (no tool needed)
           0 = parrot question answered from memory without calling any tool
    """
    question = (example.inputs or {}).get("question", "") if example else ""
    full_output = json.dumps(run.outputs or {})
    trajectory = f"Question: {question}\n\nAgent output: {full_output}"
    system_prompt = (
        "You are grading a parrot care assistant that has tools for species lookup, care tips, and diet advice.\n\n"
        "Look at the tools_called field in the agent output.\n"
        "Score 'yes' if tools_called is non-empty (agent used tools).\n"
        "Score 'yes' if tools_called is empty AND the question is NOT about parrots (correct refusal, no tools needed).\n"
        "Score 'no' if tools_called is empty AND the question IS about parrots (agent should have called a tool)."
    )
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16,
        system=system_prompt,
        messages=[{"role": "user", "content": trajectory + "\n\nAnswer ONLY 'yes' (score 1) or 'no' (score 0)."}],
    )
    answer = response.content[0].text.strip().lower()
    return {"key": "tool_selection", "score": 1.0 if answer.startswith("yes") else 0.0}


def scope_adherence_evaluator(run, example) -> dict:
    """LLM-as-judge: did the agent stay parrot-only and decline off-topic questions?

    Score: 1 = correctly declined non-parrot questions
           0 = answered questions about dogs, cats, or other non-parrot animals
    """
    output = (run.outputs or {}).get("output") or ""
    system_prompt = (
        "You are evaluating whether a parrot care assistant stayed on topic.\n\n"
        "Score 'yes' if the agent only answered parrot-related questions and stayed focused only on parrots. "
        "Score 'no' if the agent answered questions about dogs, cats, hamsters, or other non-parrot animals."
    )
    return {"key": "scope_adherence", "score": _llm_judge(system_prompt, output)}


_TERMINAL_PUNCTUATION = ".!?"


def _score_must_end_with_terminal_punctuation(output: str) -> float:
    text = output.rstrip()
    if not text:
        return 0.0
    return 1.0 if text[-1] in _TERMINAL_PUNCTUATION else 0.0


def _score_must_not_truncate_mid_word(output: str) -> float:
    text = output.rstrip()
    if not text:
        return 0.0
    if text[-1] in _TERMINAL_PUNCTUATION:
        return 1.0
    # Truncated responses (e.g. max_tokens) often end on a bare letter/digit.
    if text[-1].isalnum():
        return 0.0
    return 1.0


_CODE_ASSERTION_CHECKS = {
    "must_end_with_terminal_punctuation": _score_must_end_with_terminal_punctuation,
    "must_not_truncate_mid_word": _score_must_not_truncate_mid_word,
}


def _score_assertion(key: str, comment: str, output: str) -> float:
    checker = _CODE_ASSERTION_CHECKS.get(key)
    if checker is not None:
        return checker(output)
    system_prompt = (
        "You are grading an agent response against a single acceptance criterion.\n\n"
        f"Criterion: {comment}\n\n"
        "Score 'yes' if the agent response satisfies the criterion. "
        "Score 'no' if it does not."
    )
    return _llm_judge(system_prompt, output)


def assertions_evaluator(run, example) -> list[dict]:
    """Grade Engine-generated dataset examples that use assertions instead of expected output.

    Returns one score per assertion key. Skips examples without assertions.
    """
    reference_outputs = (example.outputs or {}) if example else {}
    assertions = reference_outputs.get("assertions") or []
    if not assertions:
        return []

    output = (run.outputs or {}).get("output") or ""
    return [
        {
            "key": assertion["key"],
            "score": _score_assertion(assertion["key"], assertion.get("comment", ""), output),
            "comment": assertion.get("comment", ""),
        }
        for assertion in assertions
        if assertion.get("key")
    ]
