"""Backward-compatible alias for :mod:`agent_handoff`.

Historical imports (``import handoff``, ``handoff.engine``, ``handoff.core``)
keep working after the package rename.
"""

from __future__ import annotations

from agent_handoff.compat import install_alias

install_alias("handoff")

import agent_handoff as _agent_handoff
from agent_handoff import *  # noqa: F401,F403
from agent_handoff import __all__ as __all__
from agent_handoff import __version__ as __version__


def __getattr__(name: str):
    return getattr(_agent_handoff, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
