# ADR-0006: argv-only execution, input validation, and privilege policy

- **Status:** Accepted (2026-09-02)
- **Context:** The kernel executes operating-system commands derived from playbook parameters that originate in human text. Classic failure modes: shell injection via package names, option-injection (`apt install -o=…`), sudo password fishing, orphaned process groups on timeout/interrupt.
- **Decision (security-first, guideline 15):**
  1. **No shell.** Every command is an `argv` list executed via `subprocess.Popen` without `shell=True`. There is no code path that concatenates user text into a shell string.
  2. **Token validation.** Package names must match `^[A-Za-z0-9][A-Za-z0-9._+-]*$` (no leading dash, no separators/globs); service units `^[A-Za-z0-9][A-Za-z0-9:@._-]*$`; search queries are split into tokens under the name rule. Anything else is refused — never sanitized, refused.
  3. **End-of-options discipline.** Mutating package commands pass `--` before user-supplied names.
  4. **Privilege:** root required per-step is declared by the playbook; if not root, the runner prefixes `sudo -n` (non-interactive). No password prompts are ever issued or captured; missing privileges produce a clear error. No root daemon, sudoers is never touched.
  5. **Process hygiene:** children start in their own session (`start_new_session=True`); on timeout or interrupt the whole process group gets SIGTERM then SIGKILL. Per-step timeouts and 16 KiB/stream output tails (stored in the journal).
  6. **Protected set:** removal/undo targeting boot-critical packages (`glibc/libc6`, `systemd*`, kernel image/firmware, `dpkg`, `apt*`, `dnf`, `pacman`, `zypper`, `apk-tools`, `coreutils`, `bash`, `dbus*`, `sudo`, `util-linux`, `mount`, `passwd`, `login`, `sysvinit`, `openrc`) is classified T3 and refused outright — undo artifacts included (a journal is a user-editable file, so its contents get re-validated before any undo executes).
- **Consequences:** Some legitimate edge cases (e.g. removing `python3` on Debian) require manual action by design; adapter command vocabulary is constrained but fully testable as exact argv.
