"""hermes-allow — terminal command guard for Hermes Agent.

Two modes:

  allow (default) — not in the list = blocked. Tight by default.
  block           — in the list = blocked. Everything else passes.

Patterns match the full command string AND the base name (first token).
Either hit counts:

  "podman"        → any podman command (matches base name)
  "podman run *"  → only "podman run <args>" (matches full string)
  "podman ps*"    → "podman ps" and "podman ps -a"

Compound commands (&&, ||, |, ;) are split; every segment is checked.

Config: plugins.entries.hermes-allow in ~/.hermes/config.yaml
"""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from hermes_cli.config import cfg_get, load_config

logger = logging.getLogger(__name__)

_ENV_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_COMPOUND_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||[|;])\s*")

_DEFAULT_ALLOWED: List[str] = [
    # Shell
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "which", "whoami",
    "uname", "date", "env", "printenv", "true", "false", "test", "[",
    # VCS
    "git", "git-*", "gh",
    # Rust
    "cargo", "cargo-*", "rustc", "rustup", "rustfmt",
    # Build
    "./build.sh", "./run_web.sh",
    "make", "cmake", "just", "task",
    # Node
    "node", "npm", "npx",
    # Python
    "python3", "python", "pip", "pip3", "uv",
    "pytest", "ruff", "mypy", "black", "isort",
    # Search
    "find", "grep", "rg", "fd",
    # Text
    "sed", "awk", "sort", "uniq", "cut", "tr", "diff",
    "column", "tee", "xargs", "jq", "yq",
    # Network queries
    "curl", "wget", "ping", "host", "dig",
    # System info
    "du", "df", "free", "top", "htop", "ps",
    "file", "stat", "md5sum", "sha256sum",
    # Binary inspection
    "xxd", "hexdump", "od", "strings", "nm", "objdump", "readelf",
    # Viewers
    "bat", "eza", "tokei",
    # File creation (non-destructive)
    "mkdir", "touch", "cp",
    # WASM / CI / Hermes
    "wasm-opt", "wasm-bindgen", "wasm2wat", "wat2wasm", "act", "hermes",
    # Containers — safe subcommands only
    "podman ps*", "podman images*", "podman logs *",
    "podman build *", "podman run *", "podman exec *",
    "podman inspect *", "podman top *", "podman stats*",
    "docker ps*", "docker images*", "docker logs *",
    "docker build *", "docker run *", "docker exec *",
    "docker inspect *", "docker top *", "docker stats*",
    # Distrobox
    "distrobox-enter", "distrobox enter *", "distrobox list*",
    "toolbox",
]

_DEFAULT_BLOCKED: List[str] = [
    "rm *-rf *", "rm *-fr *", "rm -rf *", "rm -fr *",
    "podman *prune*", "docker *prune*",
    "podman system *", "docker system *",
    "podman rm *", "docker rm *",
    "podman rmi *", "docker rmi *",
]


def _load_config() -> Tuple[str, List[str], List[str]]:
    """Return (mode, allowed, blocked) from config."""
    try:
        config = load_config()
    except Exception:
        return "allow", [], []

    entry = cfg_get(config, "plugins", "entries", "hermes-allow", default={})
    if not isinstance(entry, dict):
        entry = {}

    enabled = entry.get("enabled", True)
    if not enabled:
        return "", [], []

    mode = entry.get("mode", "allow")
    if mode not in ("allow", "block"):
        mode = "allow"

    allowed = entry.get("allowed", _DEFAULT_ALLOWED)
    blocked = entry.get("blocked", _DEFAULT_BLOCKED)

    if not isinstance(allowed, list):
        allowed = _DEFAULT_ALLOWED
    if not isinstance(blocked, list):
        blocked = _DEFAULT_BLOCKED

    return mode, allowed, blocked


def _strip_env_prefix(cmd: str) -> str:
    """Remove leading VAR=value tokens."""
    tokens = cmd.strip().split()
    while tokens and _ENV_PREFIX_RE.match(tokens[0]):
        tokens.pop(0)
    return " ".join(tokens)


def _is_match(segment: str, pattern: str) -> bool:
    """Match pattern against full command and base name. Either hit counts."""
    clean = _strip_env_prefix(segment).strip()
    if not clean:
        return False
    base = clean.split()[0]
    return fnmatch.fnmatch(clean, pattern) or fnmatch.fnmatch(base, pattern)


def _check_allow(command: str, patterns: List[str]) -> Optional[str]:
    """Allow mode: every segment must match at least one pattern."""
    segments = [s.strip() for s in _COMPOUND_SPLIT_RE.split(command) if s.strip()]
    for segment in segments:
        clean = _strip_env_prefix(segment).strip()
        if not clean:
            continue
        if not any(_is_match(segment, p) for p in patterns):
            base = clean.split()[0]
            return (
                f"hermes-allow: blocked '{base}' — "
                f"not in allowed list. "
                f"Add to plugins.entries.hermes-allow.allowed "
                f"in ~/.hermes/config.yaml"
            )
    return None


def _check_block(command: str, patterns: List[str]) -> Optional[str]:
    """Block mode: if any segment matches, block it."""
    segments = [s.strip() for s in _COMPOUND_SPLIT_RE.split(command) if s.strip()]
    for segment in segments:
        clean = _strip_env_prefix(segment).strip()
        if not clean:
            continue
        for pattern in patterns:
            if _is_match(segment, pattern):
                return (
                    f"hermes-allow: blocked '{clean}' — "
                    f"matched blocklist rule '{pattern}'. "
                    f"Adjust plugins.entries.hermes-allow.blocked "
                    f"in ~/.hermes/config.yaml"
                )
    return None


def register(ctx) -> None:  # type: ignore[no-untyped-def]
    """Plugin entry point."""

    def _pre_tool_call(
        tool_name: str, args: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, str]]:
        if tool_name != "terminal":
            return None

        command = args.get("command", "")
        if not command:
            return None

        mode, allowed, blocked = _load_config()
        if not mode:
            return None

        if mode == "allow":
            error = _check_allow(command, allowed)
        else:
            error = _check_block(command, blocked)

        if error:
            return {"action": "block", "message": error}

        return None

    ctx.register_hook("pre_tool_call", _pre_tool_call)
    logger.info("hermes-allow plugin loaded")
