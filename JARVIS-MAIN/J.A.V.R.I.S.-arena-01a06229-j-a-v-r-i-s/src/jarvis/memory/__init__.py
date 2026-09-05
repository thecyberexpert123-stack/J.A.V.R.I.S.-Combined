"""Owner-taught file memory (ADR-0020): plain files, provenance, injection-scanned writes.

One small markdown file per entry under the state dir — human-readable,
purge-able, bounded. Only the owner writes (write-time hygiene + prompt-
injection scan); the LLM planner reads a bounded, delimited block. The
store never executes anything and never talks to a network.
"""

from __future__ import annotations
