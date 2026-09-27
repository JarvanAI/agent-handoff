"""Output generators for ADR Playbooks and A2A Handoff Envelopes."""

from agent_handoff.outputs.handoff_envelope import HandoffEnvelopeGenerator
from agent_handoff.outputs.playbook_generator import PlaybookGenerator

__all__ = [
    "HandoffEnvelopeGenerator",
    "PlaybookGenerator",
]
