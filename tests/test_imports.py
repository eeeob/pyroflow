"""Import-surface tests: every module imports cleanly and the global
``@patch_cls`` monkey-patch is applied to Pyrogram.

If any module pulled in an unguarded newer-Python feature (e.g. a bare
``StrEnum`` import) or an undeclared dependency, importing it here fails.
"""

import importlib

import pytest

MODULES = [
    "pyroflow",
    "pyroflow.client",
    "pyroflow.dispatcher",
    "pyroflow.enums",
    "pyroflow.errors",
    "pyroflow.models",
    "pyroflow.types",
    "pyroflow.typings",
    "pyroflow.listener_coordinator",
    "pyroflow.listener_coordinator.listener_coordinator",
    "pyroflow.listener_coordinator.memory_listener_coordinator",
    "pyroflow.listener_coordinator.redis_listener_coordinator",
    "pyroflow.update_coordinated",
    "pyroflow.update_coordinated.update_coordinated",
    "pyroflow.update_coordinated.message_coordinated",
    "pyroflow.update_coordinated.callback_query_coordinated",
    "pyroflow.update_coordinator",
    "pyroflow.update_coordinator.update_coordinator",
    "pyroflow.update_coordinator.memory_update_coordinator",
    "pyroflow.update_coordinator.redis_update_coordinator",
    "pyroflow.update_history",
    "pyroflow.update_history.update_history",
    "pyroflow.update_history.message_history",
    "pyroflow.update_history.callback_query_history",
    "pyroflow.update_history_store",
    "pyroflow.update_history_store.update_history_store",
    "pyroflow.update_history_store.memory_update_history_store",
    "pyroflow.update_listener",
    "pyroflow.update_listener.update_listener",
    "pyroflow.update_listener.message_listener",
    "pyroflow.update_listener.callback_query_listener",
    "pyroflow.utils",
    "pyroflow.utils.classes",
    "pyroflow.utils.enums",
    "pyroflow.utils.errors",
    "pyroflow.utils.misc_tools",
    "pyroflow.utils.models",
    "pyroflow.utils.typings",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    assert importlib.import_module(module) is not None


def test_redis_import_does_not_require_redis_installed():
    """The Redis backends must import even without ``redis`` present:
    every ``redis`` import is guarded by ``TYPE_CHECKING`` / local import."""
    importlib.import_module("pyroflow.listener_coordinator.redis_listener_coordinator")
    importlib.import_module("pyroflow.update_coordinator.redis_update_coordinator")


def test_global_monkey_patch_applied():
    import pyrogram.dispatcher
    import pyrogram.types

    import pyroflow

    # types.py patches replaced the Pyrogram classes themselves
    assert pyroflow.Message is pyrogram.types.Message
    assert pyroflow.CallbackQuery is pyrogram.types.CallbackQuery
    assert hasattr(pyrogram.types.Message, "ask")

    # client.py / dispatcher.py patches
    assert hasattr(pyroflow.Client, "ask")
    assert hasattr(pyrogram.dispatcher.Dispatcher, "register_listener")
    # preserve_old kept the originals around
    assert hasattr(pyrogram.dispatcher.Dispatcher, "old__init__")


def test_public_exports_present():
    import pyroflow

    for name in (
        "Client",
        "Dispatcher",
        "Message",
        "CallbackQuery",
        "MessageListener",
        "CallbackQueryListener",
        "MessageCoordinated",
        "CallbackQueryCoordinated",
        "MessageHistory",
        "CallbackQueryHistory",
    ):
        assert hasattr(pyroflow, name), f"pyroflow.{name} is not exported"
