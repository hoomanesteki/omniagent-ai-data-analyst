"""Semantic agent: build a SemanticQuery from the question and hand it to the executor.

Metric identification and dimension grouping are already deterministic
(the catalog match made in master_node). The one thing free text needs a
model for is spotting a time expression and any explicit filter values —
so this node makes exactly one LLM call, for exactly that, and resolves
the extracted time phrase deterministically via TimeResolver.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.messages import latest_user_message
from omniagent.agents.node_types import GraphNode
from omniagent.agents.query_codec import query_to_dict
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.models import SemanticExtraction
from omniagent.kernel.ports.llm import LLMProvider
from omniagent.kernel.ports.semantic import Filter, FilterOp, SemanticProvider, SemanticQuery
from omniagent.kernel.ports.time import CalendarSpec, TimeResolver
from omniagent.kernel.state import OmniState
from omniagent.kernel.time_resolver import TimePhraseError


def make_semantic_agent_node(
    *,
    dataset_id: str,
    catalog: Catalog,
    semantic_provider: SemanticProvider,
    llm: LLMProvider,
    model_id: str,
    time_resolver: TimeResolver,
    calendar: CalendarSpec,
    now_fn: Callable[[], datetime],
) -> GraphNode:
    """Bind a dataset's catalog, semantic provider, and model to a node function."""

    async def semantic_agent_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        metric_name = state.matched_metric
        if not metric_name:
            # master_node only routes here after a deterministic catalog
            # match; reaching this node without one is a wiring bug, not a
            # user-facing condition.
            return Command(
                goto=END,
                update={"error": "semantic_agent reached with no matched_metric"},
            )

        extraction = llm.structured(
            model_id,
            {
                "task": "extract_time_and_filters",
                "question": question,
                "metric": metric_name,
                "known_dimensions": list(catalog.dimension_names()),
            },
            schema=SemanticExtraction,
        )

        assumptions: list[str] = []
        time_range = None
        if extraction.time_phrase:
            try:
                time_range = time_resolver.resolve(
                    extraction.time_phrase, now=now_fn(), cal=calendar
                )
            except TimePhraseError:
                assumptions.append(
                    f"Could not interpret time phrase {extraction.time_phrase!r}; showing all time."
                )

        known_dimensions = set(catalog.dimensions)
        filters: list[Filter] = []
        for extracted in extraction.filters:
            if extracted.dimension in known_dimensions:
                filters.append(
                    Filter(field=extracted.dimension, op=FilterOp.EQ, value=extracted.value)
                )
            else:
                assumptions.append(
                    f"Ignored filter on unrecognized dimension {extracted.dimension!r}."
                )

        group_by = catalog.match_dimensions(question)
        query = SemanticQuery(
            metrics=(metric_name,),
            group_by=group_by,
            filters=tuple(filters),
            time_range=time_range,
            # A breakdown needs its rows ordered by the metric, descending,
            # for the narrator's "X leads at Y" claim to actually describe
            # the real top group rather than whichever 100 rows the engine
            # happened to return first.
            order_by=(f"-{metric_name}",) if group_by else (),
            limit=100,
            assumptions=tuple(assumptions),
        )

        issues = semantic_provider.validate(dataset_id, query)
        if issues:
            return Command(
                goto=END,
                update={"error": "; ".join(str(issue) for issue in issues)},
            )

        model_calls_by_node = dict(state.model_calls_by_node)
        model_calls_by_node["semantic_agent"] = model_calls_by_node.get("semantic_agent", 0) + 1

        return Command(
            goto="executor",
            update={
                "semantic_query": query_to_dict(query),
                "assumptions": assumptions,
                "llm_calls": state.llm_calls + 1,
                "model_calls_by_node": model_calls_by_node,
            },
        )

    return semantic_agent_node
