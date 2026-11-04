"""Member-level interface dispatch for Kotlin and Java.

A Kotlin call through a constructor-injected dependency lands on the interface's
method node, because that is what the call site names: `ordersInfoHolder.getScope()`
where `ordersInfoHolder` is an `OrdersInfoHolder` resolves to
`OrdersInfoHolder.getScope()`. The implementing `OrdersInfoHolderImpl.getScope()`
is a separate node, and nothing joins the two, so a directed walk stops at the
interface and every chain through an injected dependency is cut at that point.
On an Android codebase wired with Toothpick, Dagger or Hilt, where every
dependency is an interface, that is most chains.

The mechanism — single-owner, per-method `dispatches_to` edges at INFERRED,
fanning out to every implementer — lives in `graphify.interface_dispatch`; this
module fixes the JVM gate. Kotlin and Java share one package and type namespace
(the JVM resolution pass already treats them as one family), so both ends may
be declared in either language, but not in a `.cs`, `.swift` or other file that
merely reuses the interface's name.
"""
from __future__ import annotations

from graphify.interface_dispatch import (  # noqa: F401  (re-exported for callers)
    DISPATCH_RELATION,
    method_label as _method_label,
    resolve_interface_dispatch,
)

_JVM_SUFFIXES = (".kt", ".kts", ".java")


def resolve_jvm_interface_dispatch(
    per_file: list[dict],
    all_nodes: list[dict],
    all_edges: list[dict],
) -> None:
    """Link each Kotlin/Java interface method to every implementation that owns it unambiguously."""
    resolve_interface_dispatch(per_file, all_nodes, all_edges, suffixes=_JVM_SUFFIXES)
