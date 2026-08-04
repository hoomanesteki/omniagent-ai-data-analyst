"""Turn a caller's task-shaped `req` dict into a prompt string.

Callers (agent nodes) stay decoupled from any one provider's prompting
conventions by passing a small, structured dict rather than a raw prompt —
this is where that dict becomes actual text, shared across providers so the
same `req` shape produces comparable prompts regardless of which model
answers it.
"""

from __future__ import annotations

from typing import Any

_TASK_INSTRUCTIONS = {
    "extract_time_and_filters": (
        "Extract the time period and any explicit filters from the user's "
        "question. Only extract what is explicitly stated — never invent a "
        "time period or filter the question doesn't mention. If the "
        "question names a time period (e.g. 'last quarter', 'this month', "
        "'year to date'), extract it verbatim as time_phrase; otherwise "
        "leave time_phrase null. For each explicit filter, name one of the "
        "known dimensions and the value the question specifies."
    ),
    "generate_sql": (
        "Write a single read-only SELECT statement that answers the "
        "question, using only the tables and columns listed in `schema`. "
        "Never use DROP, CREATE, ALTER, DELETE, INSERT, UPDATE, TRUNCATE, "
        "EXEC, or SELECT INTO, and never emit more than one statement. If "
        "`prior_error` is present, it explains why your last attempt "
        "(`prior_attempt_sql`) was rejected — fix that specific problem "
        "rather than starting over from scratch."
    ),
    "route_question": (
        "The question did not match any known metric by name. Decide what "
        "to do with it. Set intent to 'sql' if it is plausibly a real "
        "question about this dataset's underlying data that a SQL query "
        "could answer, even if it doesn't name a known metric. Set intent "
        "to 'chat' if it is a greeting, small talk, or a request unrelated "
        "to this dataset (weather, general knowledge, and so on) that no "
        "query could ever answer. Set needs_clarification to true only if "
        "the question is genuinely too vague to act on either way, and "
        "list one or two clarification_options as short follow-up "
        "questions. Never guess a metric name that was not explicitly "
        "given in known_metrics."
    ),
}


def build_prompt(req: dict[str, Any]) -> str:
    task = req.get("task")
    lines: list[str] = []

    instruction = _TASK_INSTRUCTIONS.get(task) if task else None
    if instruction:
        lines.append(instruction)

    for key, value in req.items():
        if key == "task":
            continue
        lines.append(f"{key}: {value}")

    return "\n".join(lines) if lines else str(req)
