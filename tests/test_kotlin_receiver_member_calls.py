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


STATE_KT = """\
package state
import data.OrderRepo
class Payments(val repo: OrderRepo) {
    fun current(): OrderRepo = repo
}
class CheckoutState(val payments: Payments)
"""


def test_field_chain_reaches_the_method_through_declared_field_types(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "state/State.kt": STATE_KT,
        "app/Checkout.kt": "package app\nimport state.CheckoutState\n"
                           "class Checkout(private val state: CheckoutState) {\n"
                           "    fun run() { state.payments.repo.save(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "OrderRepo:.save()") in edges


def test_call_chain_uses_the_declared_return_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "state/State.kt": STATE_KT,
        "app/Checkout.kt": "package app\nimport state.CheckoutState\n"
                           "class Checkout(private val state: CheckoutState) {\n"
                           "    fun run() { state.payments.current()!!.load(\"1\") }\n}\n",
    })
    assert ("Checkout:.run()", "State:.current()") in edges
    assert ("Checkout:.run()", "OrderRepo:.load()") in edges


def test_lazy_and_provider_get_unwrap_to_the_injected_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\n"
                           "class Checkout(\n    private val lazyRepo: Lazy<OrderRepo>,\n"
                           "    private val repoProvider: Provider<OrderRepo>?,\n) {\n"
                           "    fun a() { lazyRepo.get().save(\"1\") }\n"
                           "    fun b() { repoProvider?.get()?.load(\"1\") }\n}\n",
    })
    assert ("Checkout:.a()", "OrderRepo:.save()") in edges
    assert ("Checkout:.b()", "OrderRepo:.load()") in edges


def test_state_flow_value_unwraps_to_the_state_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "state/State.kt": STATE_KT,
        "app/Interactor.kt": "package app\nimport state.CheckoutState\n"
                             "interface Interactor { val state: StateFlow<CheckoutState> }\n",
        "app/Service.kt": "package app\n"
                          "class Service(private val interactor: Interactor) {\n"
                          "    fun run() { interactor.state.value.payments.repo.save(\"1\") }\n}\n",
    })
    assert ("Service:.run()", "OrderRepo:.save()") in edges


def test_let_and_also_lambda_parameters_take_the_receiver_type(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "state/State.kt": STATE_KT,
        "app/Checkout.kt": "package app\nimport data.OrderRepo\nimport state.Payments\n"
                           "class Checkout(private val repo: OrderRepo?, private val payments: Payments?) {\n"
                           "    fun a() { repo?.let { it.save(\"1\") } }\n"
                           "    fun b() { repo?.also { r -> r.load(\"1\") } }\n"
                           "    fun c() { payments?.let { it.repo.save(\"1\") } }\n"
                           "    fun d(items: List<OrderRepo>) { items.forEach { it.save(\"1\") } }\n}\n",
    })
    assert ("Checkout:.a()", "OrderRepo:.save()") in edges
    assert ("Checkout:.b()", "OrderRepo:.load()") in edges
    assert ("Checkout:.c()", "OrderRepo:.save()") in edges
    assert ("Checkout:.d()", "OrderRepo:.save()") not in edges


def test_flow_property_reads_are_edges_to_the_property(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n    fun init()\n}\n",
        "app/Interactor.kt": "package app\nimport core.Core\n"
                             "interface Interactor : Core<String>\n",
        "app/Service.kt": "package app\n"
                          "class Service(private val interactor: Interactor) {\n"
                          "    fun subscribe() {\n        interactor.state\n"
                          "            .onEach { }\n            .launchIn(scope)\n    }\n"
                          "    fun once() { interactor.init() }\n}\n",
    })
    assert ("Service:.subscribe()", "Core:.state") in edges
    assert ("Service:.once()", "Core:.state") not in edges


def test_extension_flow_property_links_readers_and_its_getter(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n}\n",
        "app/Ext.kt": "package app\nimport core.Core\n"
                      "internal val Core<String>.baseState: Flow<String>\n"
                      "    get() = state.filterIsInstance<String>()\n",
        "app/Interactor.kt": "package app\nimport core.Core\n"
                             "interface Interactor : Core<String>\n",
        "app/Service.kt": "package app\n"
                          "class Service(private val interactor: Interactor) {\n"
                          "    fun subscribe() { interactor.baseState.onEach { }.launchIn(scope) }\n}\n",
    })
    assert ("Service:.subscribe()", "Ext:baseState") in edges
    assert ("Ext:baseState", "Core:.state") in edges


def test_property_initializer_and_init_block_use_constructor_parameter_types(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n}\n",
        "data/OrderRepo.kt": REPO_KT,
        "app/ViewModel.kt": "package app\nimport core.Core\nimport data.OrderRepo\n"
                            "class ViewModel(interactor: Core<String>, repo: OrderRepo) {\n"
                            "    val ui = interactor.state.map { it }\n"
                            "    init { repo.save(\"1\") }\n}\n",
    })
    assert ("ViewModel:ViewModel", "Core:.state") in edges
    assert ("ViewModel:ViewModel", "OrderRepo:.save()") in edges


def test_same_named_extension_flow_properties_bind_through_the_readers_import(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n}\n",
        "base/BaseExt.kt": "package base\nimport core.Core\n"
                           "internal val Core<String>.baseState: Flow<String>\n"
                           "    get() = state.filterIsInstance<String>()\n",
        "b2b/B2bExt.kt": "package b2b\nimport core.Core\n"
                         "internal val Core<Int>.baseState: Flow<Int>\n"
                         "    get() = state.filterIsInstance<Int>()\n",
        "app/Service.kt": "package app\nimport core.Core\nimport b2b.baseState\n"
                          "class Service(private val interactor: Core<Int>) {\n"
                          "    fun subscribe() { interactor.baseState.onEach { }.launchIn(scope) }\n}\n",
    })
    assert ("Service:.subscribe()", "B2bExt:baseState") in edges
    assert ("Service:.subscribe()", "BaseExt:baseState") not in edges


def test_flow_passed_as_an_argument_or_assigned_is_a_read(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n    val other: Flow<Int>\n}\n",
        "app/Service.kt": "package app\nimport core.Core\n"
                          "class Service(private val interactor: Core<String>) {\n"
                          "    fun merged() = combine(interactor.state, interactor.other) { a, b -> a }\n"
                          "    fun kept() { val s = interactor.state }\n"
                          "    fun none() { val n = interactor.hashCode() }\n}\n",
    })
    assert ("Service:.merged()", "Core:.state") in edges
    assert ("Service:.merged()", "Core:.other") in edges
    assert ("Service:.kept()", "Core:.state") in edges
    assert ("Service:.none()", "Core:.state") not in edges


def test_flow_property_read_through_an_implementation_with_an_unknown_base(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "core/Core.kt": "package core\n"
                        "interface Core<S> {\n    val state: StateFlow<S>\n}\n",
        "app/InteractorImpl.kt": "package app\nimport core.Core\nimport ext.Outside\n"
                                 "class InteractorImpl(private val repo: Repo) : Core<String>, Outside {\n"
                                 "    override val state = repo.state\n}\n",
        "app/Service.kt": "package app\n"
                          "class Service(private val interactor: InteractorImpl) {\n"
                          "    fun subscribe() { interactor.state.onEach { }.launchIn(scope) }\n}\n",
    })
    assert ("Service:.subscribe()", "Core:.state") in edges


def test_top_level_function_parameter_receiver(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Helpers.kt": "package app\nimport data.OrderRepo\n"
                          "fun persist(repo: OrderRepo) { repo.save(\"1\") }\n",
    })
    assert ("Helpers:persist()", "OrderRepo:.save()") in edges


def test_members_after_a_parse_error_stay_on_their_class(tmp_path: Path) -> None:
    props = "".join(f"    private val p{i} = Holder()\n" for i in range(10))
    filler = "".join(f"\n    fun f{i}() {{ repo.load(\"{i}\") }}\n" for i in range(40))
    broken = (
        "package app\nimport data.OrderRepo\n"
        "class Broken(private val repo: OrderRepo) {\n"
        + props
        + "\n    fun second() { repo.save(\"1\") }\n"
        "    private val merged = combine(a, b) { override, default ->\n"
        "        if (default == null) null else override ?: default\n    }\n"
        + filler + "}\n"
    )
    paths = []
    for name, text in {"data/OrderRepo.kt": REPO_KT, "app/Broken.kt": broken}.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    r = extract(paths, cache_root=tmp_path, parallel=False)
    by_id = {n["id"]: n for n in r["nodes"]}
    second = [n for n in r["nodes"] if n["label"].removeprefix(".") == "second()"]
    assert second
    owners = {
        by_id[e["source"]]["label"] for e in r["edges"]
        if e["relation"] == "method" and e["target"] == second[0]["id"]
    }
    assert owners == {"Broken"}
    called = {
        by_id[e["target"]]["label"] for e in r["edges"]
        if e["relation"] == "calls" and e["source"] == second[0]["id"]
    }
    assert ".save()" in called


def test_grammar_gaps_are_repaired_without_moving_lines(tmp_path: Path) -> None:
    source = (
        "package app\nimport data.OrderRepo\n"
        "abstract class Base<\n    R : OrderRepo,\n    S : Any,\n    >(protected val repo: R) {\n"
        "    private val onFail = suspend { repo.load(\"x\") }\n"
        "    private val merged = combine(a, b) { override, default -> override ?: default }\n"
        "    fun third() {\n        repo.save(\"1\")\n    }\n}\n"
    )
    paths = []
    for name, text in {"data/OrderRepo.kt": REPO_KT, "app/Base.kt": source}.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    r = extract(paths, cache_root=tmp_path, parallel=False)
    by_id = {n["id"]: n for n in r["nodes"]}
    third = [n for n in r["nodes"] if n["label"] == ".third()"]
    assert third and third[0]["source_location"] == "L9"
    owners = {by_id[e["source"]]["label"] for e in r["edges"]
              if e["relation"] == "method" and e["target"] == third[0]["id"]}
    assert owners == {"Base"}
    called = {by_id[e["target"]]["label"] for e in r["edges"]
              if e["relation"] == "calls" and e["source"] == third[0]["id"]}
    assert ".save()" in called


def test_mock_factories_type_the_field_in_tests(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/CheckoutTest.kt": "package app\nimport data.OrderRepo\n"
                               "class CheckoutTest {\n"
                               "    private val repo = mockk<OrderRepo>(relaxed = true)\n"
                               "    fun stubs() { coEvery { repo.load(any()) } returns \"x\" }\n"
                               "    fun verifies() { repo.save(\"1\") }\n}\n",
    })
    assert ("CheckoutTest:.stubs()", "OrderRepo:.load()") in edges
    assert ("CheckoutTest:.verifies()", "OrderRepo:.save()") in edges


def test_typed_receiver_does_not_bind_to_a_same_named_method_of_this_file(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Facade.kt": "package app\nimport data.OrderRepo\n"
                         "class Facade(private val dataSource: OrderRepo) {\n"
                         "    fun load(id: String): String = dataSource.load(id)\n"
                         "    fun other() = load(\"1\")\n}\n",
    })
    assert ("Facade:.load()", "OrderRepo:.load()") in edges
    assert ("Facade:.load()", "Facade:.load()") not in edges
    assert ("Facade:.other()", "Facade:.load()") in edges


def test_when_guard_does_not_break_the_class(tmp_path: Path) -> None:
    source = (
        "package app\nimport data.OrderRepo\n"
        "class Guarded(private val repo: OrderRepo) {\n"
        "    fun pick(x: Any, flag: Boolean) = when (x) {\n"
        "        is String if flag -> repo.load(x)\n"
        "        else -> \"\"\n"
        "    }\n"
        "    fun after() {\n        repo.save(\"1\")\n    }\n}\n"
    )
    edges = _edges(tmp_path, {"data/OrderRepo.kt": REPO_KT, "app/Guarded.kt": source})
    assert ("Guarded:.pick()", "OrderRepo:.load()") in edges
    assert ("Guarded:.after()", "OrderRepo:.save()") in edges


def test_newer_syntax_and_odd_bytes_do_not_break_the_class(tmp_path: Path) -> None:
    source = (
        "package app\nimport data.OrderRepo\n"
        "class Odd(private val repo: OrderRepo) {\n"
        "    fun pick(x: Any, a: Boolean, b: Boolean) = when (x) {\n"
        "        is String if a &&\n"
        "            b -> repo.load(x)\n"
        "        else -> \"\"\n"
        "    }\n"
        "    fun tag(ids: List<String>) = ids.map { id ->\n"
        "        $\"{i:${id};\" + \"x\"\n"
        "    }\n"
        "    fun gate(ids: List<String>, on: Boolean) = ids.takeIf {\n"
        "        (on) && it.isNotEmpty()\n"
        "    }\n"
        "    fun zero(t: Int) = when (t) {\n"
        "        1 -> '\x00'\n"
        "        else -> null\n"
        "    }\n"
        "    fun after() {\n        repo.save(\"1\")\n    }\n}\n"
    )
    edges = _edges(tmp_path, {"data/OrderRepo.kt": REPO_KT, "app/Odd.kt": source})
    assert ("Odd:.pick()", "OrderRepo:.load()") in edges
    assert ("Odd:.after()", "OrderRepo:.save()") in edges


def test_type_parameter_receiver_takes_its_upper_bound(tmp_path: Path) -> None:
    edges = _edges(tmp_path, {
        "data/OrderRepo.kt": REPO_KT,
        "app/Service.kt": "package app\nimport data.OrderRepo\n"
                          "abstract class Service<R : OrderRepo, S>(protected val repo: R) {\n"
                          "    fun run() { repo.save(\"1\") }\n}\n",
    })
    assert ("Service:.run()", "OrderRepo:.save()") in edges


def test_extension_function_is_a_weaker_fallback_and_stdlib_names_are_not(tmp_path: Path) -> None:
    paths = []
    for name, text in {
        "data/OrderRepo.kt": REPO_KT,
        "data/RepoExt.kt": "package data\nfun OrderRepo.saveAll(ids: List<String>) {}\n"
                           "fun OrderRepo.copy(): OrderRepo = this\n",
        "app/Checkout.kt": "package app\nimport data.OrderRepo\nimport data.saveAll\n"
                           "class Checkout(private val repo: OrderRepo) {\n"
                           "    fun run() { repo.saveAll(listOf()) }\n"
                           "    fun dup() { repo.copy() }\n}\n",
    }.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    r = extract(paths, cache_root=tmp_path, parallel=False)
    by_id = {n["id"]: n for n in r["nodes"]}
    calls = [
        (by_id[e["source"]]["label"], by_id[e["target"]]["label"], e.get("confidence_score"))
        for e in r["edges"] if e["relation"] == "calls"
    ]
    ext = [c for c in calls if c[0] == ".run()" and c[1].endswith("saveAll()")]
    assert ext and ext[0][2] == 0.75
    assert not [c for c in calls if c[0] == ".dup()" and c[1].endswith("copy()")]
