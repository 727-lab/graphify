"""Kotlin receiver-typed member calls and JVM interface dispatch.

A Kotlin call through an injected dependency (`repo.save()` where `repo` is a
constructor `val`) had no edge: the engine never recorded the receiver for a
lowercase navigation head, so the shared cross-file pass dropped the call as an
unresolvable member call. Java already binds such calls through a per-method
receiver type table; these tests pin the Kotlin twin.

Receivers covered: constructor `val`/`var`, class property (declared type and
`= Ctor()` initializer), function parameter, typed local, `this.field.m()`,
safe call `repo?.m()`. Guards: an ambiguous type name binds only through the
caller's imports or directory; a method declared on a supertype in another file
is found; a type declared nowhere here is parked, not guessed.
"""
from __future__ import annotations

from pathlib import Path

from graphify.extract import extract


def _edges(tmp_path: Path, files: dict[str, str], relation: str = "calls") -> set[tuple[str, str]]:
    """``relation`` edges as ``("File:label", "File:label")`` pairs."""
    paths = []
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    r = extract(paths, cache_root=tmp_path, parallel=False)
    where = {
        n["id"]: f'{Path(n.get("source_file", "")).stem}:{n["label"]}'
        for n in r["nodes"]
    }
    return {
        (where[e["source"]], where[e["target"]])
        for e in r["edges"]
        if e["relation"] == relation and e["source"] in where and e["target"] in where
    }


REPO_KT = """\
package data
interface OrderRepo {
    fun save(id: String)
    fun load(id: String): String
}
"""
REPO_IMPL_KT = """\
package data
class OrderRepoImpl : OrderRepo {
    override fun save(id: String) {}
    override fun load(id: String): String = id
}
"""
# Same method names on an unrelated type: a bare-name match would be wrong.
AUDIT_KT = """\
package audit
class AuditLog {
    fun save(id: String) {}
    fun load(id: String): String = id
}
"""


def test_constructor_val_receiver_binds_to_the_declared_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "audit/AuditLog.kt": AUDIT_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\n"
                           "class Checkout(private val repo: OrderRepo) {\n"
                           "    fun run() { repo.save(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "OrderRepo:.save()") in edges
    assert ("Checkout:.run()", "AuditLog:.save()") not in edges


def test_class_property_receiver_with_declared_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\n"
                           "class Checkout {\n    private lateinit var repo: OrderRepo\n"
                           "    fun run() { repo.load(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "OrderRepo:.load()") in edges


def test_class_property_receiver_typed_by_constructor_initializer(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "data/OrderRepoImpl.kt": REPO_IMPL_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepoImpl\n"
                           "class Checkout {\n    private val repo = OrderRepoImpl()\n"
                           "    fun run() { repo.save(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "OrderRepoImpl:.save()") in edges


def test_function_parameter_and_typed_local_receivers(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "data/OrderRepoImpl.kt": REPO_IMPL_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\nimport data.OrderRepoImpl\n"
                           "class Checkout {\n"
                           "    fun viaParam(repo: OrderRepo) { repo.save(\"1\") }\n"
                           "    fun viaLocal() {\n        val local: OrderRepoImpl = OrderRepoImpl()\n"
                           "        local.load(\"1\")\n    }\n}\n",
    })
    assert ("Checkout:.viaParam()", "OrderRepo:.save()") in edges
    assert ("Checkout:.viaLocal()", "OrderRepoImpl:.load()") in edges


def test_this_field_and_safe_call_shapes(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\n"
                           "class Checkout(private val repo: OrderRepo?) {\n"
                           "    fun a() { this.repo?.save(\"1\") }\n"
                           "    fun b() { repo?.load(\"1\") }\n}\n",
    })
    assert ("Checkout:.a()", "OrderRepo:.save()") in edges
    assert ("Checkout:.b()", "OrderRepo:.load()") in edges


def test_method_declared_on_a_supertype_in_another_file_is_found(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "data/CachedRepo.kt": "package data\nabstract class CachedRepo : OrderRepo { fun warm() {} }\n",
        "app/Checkout.kt": "package app\nimport data.CachedRepo\n"
                           "class Checkout(private val repo: CachedRepo) {\n"
                           "    fun run() { repo.save(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "OrderRepo:.save()") in edges


def test_ambiguous_type_name_binds_only_through_the_callers_import(tmp_path: Path) -> None:
    dup_a = "package a\nclass Store { fun put() {} }\n"
    dup_b = "package b\nclass Store { fun put() {} }\n"
    edges = _edges(tmp_path, {
        "a/Store.kt": dup_a,
        "b/Store.kt": dup_b,
        "app/Imported.kt": "package app\nimport a.Store\n"
                           "class Imported(private val store: Store) { fun go() { store.put() } }\n",
        "app/Unimported.kt": "package app\n"
                             "class Unimported(private val store: Store) { fun go() { store.put() } }\n",
    })
    imported = {t for s, t in edges if s == "Imported:.go()"}
    unimported = {t for s, t in edges if s == "Unimported:.go()"}
    assert any(t.endswith(":.put()") for t in imported)
    assert not any(t.endswith(":.put()") for t in unimported)


def test_a_receiver_declared_nowhere_here_is_parked_not_guessed(tmp_path: Path) -> None:
    files = {
        "audit/AuditLog.kt": AUDIT_KT,
        "app/Checkout.kt": "package app\nimport ext.RemoteRepo\n"
                           "class Checkout(private val repo: RemoteRepo) {\n"
                           "    fun run() { repo.save(\"1\") }\n}\n",
    }
    edges = _edges(tmp_path, files)
    assert ("Checkout:.run()", "AuditLog:.save()") not in edges


def test_interface_method_dispatches_to_its_kotlin_implementation(tmp_path: Path) -> None:
    dispatch = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "data/OrderRepoImpl.kt": REPO_IMPL_KT,
    }, relation="dispatches_to")
    assert ("OrderRepo:.save()", "OrderRepoImpl:.save()") in dispatch
    assert ("OrderRepo:.load()", "OrderRepoImpl:.load()") in dispatch


def test_object_qualified_call_keeps_its_extracted_binding(tmp_path: Path) -> None:
    # Regression guard for #1698: the capitalized `Settings.get()` shape is not
    # routed through the receiver-typed resolver.
    paths = []
    for name, text in {
        "util/Settings.kt": "package util\nobject Settings { fun get(k: String): String = k }\n",
        "app/Caller.kt": "package app\nimport util.Settings\n"
                         "class Caller { fun go() { Settings.get(\"a\") } }\n",
    }.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    r = extract(paths, cache_root=tmp_path, parallel=False)
    by_id = {n["id"]: n for n in r["nodes"]}
    hits = [
        e for e in r["edges"]
        if e["relation"] == "calls"
        and by_id[e["source"]]["label"] == ".go()"
        and by_id[e["target"]]["label"] == ".get()"
    ]
    assert hits and hits[0]["confidence"] == "EXTRACTED"
