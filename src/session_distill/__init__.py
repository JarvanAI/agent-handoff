"""Backward-compatible alias for :mod:`agent_handoff`.

``session_distill`` remains importable after the package rename, including
submodules such as ``session_distill.engine``.
"""

from __future__ import annotations

from agent_handoff.compat import install_alias

install_alias("session_distill")

import agent_handoff as _agent_handoff
from agent_handoff import *  # noqa: F401,F403
from agent_handoff import __all__ as __all__
from agent_handoff import __version__ as __version__


def __getattr__(name: str):
    return getattr(_agent_handoff, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
