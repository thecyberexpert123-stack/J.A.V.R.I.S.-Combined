# ADR-0002: v1 interaction surface — CLI-first with TUI chat

- **Status:** Accepted (2026-09-02, authority delegated by owner to engineer-of-record)
- **Context:** Owner requirement #10 wants deep integration with simple setup; #11 requires *a path* to GUI control (not necessarily a GUI interface). Candidates: CLI+TUI, desktop overlay first, background daemon first.
- **Decision:** v1 ships a **CLI (`jarvis …`) plus an interactive TUI chat** (M2). Rationale: (1) Linux users' native surface, matching the product's audience; (2) approval gates for safety tiers (T2/T3) are natural and auditable in a terminal; (3) smallest dependency and attack surface (owner guideline 15); (4) a GUI overlay would couple the project to Wayland/compositor fragility (RESEARCH R3) before the safety kernel is proven. GUI *control* (driving desktop apps) remains fully in scope (M5); a GUI *interface* (overlay/launcher) is a post-v1 candidate. Daemon IPC is deferred until a second consumer exists (guideline 14).
- **Consequences:** No desktop overlay in v1; TUI chat depends on a TUI library from M2 (justified per guideline 16 at that time); daemon service lands only when justified by real consumers.
