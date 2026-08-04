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
