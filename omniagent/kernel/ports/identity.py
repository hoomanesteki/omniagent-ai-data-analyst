"""Identity and scoping: principal, tenant, dataset ownership."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    """Identity of a caller, with roles and attributes for RLS."""

    tenant_id: str = "local"
    user_id: str = "local"
    roles: tuple[str, ...] = ()
    attrs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    """Every memory and result is scoped by tenant, dataset, and schema."""

    tenant: str
    dataset: str
    schema_version: str  # manifest hash. Stops rename poisoning retrieval.
