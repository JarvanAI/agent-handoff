"""Backward-compatible imports after the handoff -> agent_handoff rename."""

from __future__ import annotations

import agent_handoff
import handoff
import session_distill
from agent_handoff.version import __version__


def test_legacy_packages_share_the_public_api() -> None:
    assert handoff.__version__ == __version__ == "0.2.0"
    assert session_distill.__version__ == "0.2.0"
    assert handoff.DistillationEngine is agent_handoff.DistillationEngine
    assert session_distill.DistillationEngine is agent_handoff.DistillationEngine
    assert handoff.BaseSessionAdapter is agent_handoff.BaseSessionAdapter


def test_legacy_submodules_are_the_real_modules() -> None:
    from handoff.engine import DistillationEngine as HandoffEngine
    from handoff.core.noise_filter import NoiseFilter as HandoffFilter
    from session_distill.adapters import get_adapter as distill_get_adapter

    assert HandoffEngine is agent_handoff.engine.DistillationEngine
    assert HandoffFilter is agent_handoff.core.noise_filter.NoiseFilter
    assert distill_get_adapter is agent_handoff.adapters.get_adapter
    assert handoff.search_sessions is agent_handoff.search_sessions
