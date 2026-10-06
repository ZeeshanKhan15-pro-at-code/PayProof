"""Explicit local human-command contracts; no AI/comparison verification state.

The atomic command is SQLiteStore.record_independent_check. Callback and identity
are taken exclusively from the stored trusted baseline and current comparison.
"""

from payproof.workflow_contracts import IndependentCheckAction, IndependentCheckEvent

__all__ = ["IndependentCheckAction", "IndependentCheckEvent"]
