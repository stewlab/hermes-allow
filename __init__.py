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
Operators inside single or double quotes are not treated as splitters.

Note: subshell syntax ($(), backticks) is NOT parsed. See README.

Config: plugins.entries.hermes-allow in ~/.hermes/config.yaml
"""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from hermes_cli.config import cfg_get, load_config

logger = logging.getLogger(__name__)

_ENV_PREFIX_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')


def _split_compound(cmd: str) -> List[str]:
    """Split a shell command on top-level operators (&&, ||, |, ;).

    Operators inside single or double quotes are ignored, so
    'git commit -m "fix: a && b"' is treated as one segment.
    """
    segments: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            current.append(ch)
        elif cmd[i : i + 2] in ('&&', '||'):
            segments.append(''.join(current).strip())
            current = []
            i += 2
            continue
        elif ch in ('|', ';'):
            segments.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    segments.append(''.join(current).strip())
    return [s for s in segments if s]


# Sentinel returned by _load_config when plugin is explicitly disabled.
_DISABLED = 'disabled'

_DEFAULT_ALLOWED: List[str] = [
    # Shell
    'ls',
    'cat',
    'head',
    'tail',
    'wc',
    'pwd',
    'echo',
    'which',
    'whoami',
    'uname',
    'date',
    'env',
    'printenv',
    'true',
    'false',
    'test',
    '[',
    # VCS
    'git',
    'git-*',
    'gh',
    # Rust
    'cargo',
    'cargo-*',
    'rustc',
    'rustup',
    'rustfmt',
    # Build
    './build.sh',
    './run_web.sh',
    'make',
    'cmake',
    'just',
    'task',
    # Node
    'node',
    'npm',
    'npx',
    # Python
    'python3',
    'python',
    'pip',
    'pip3',
    'uv',
    'pytest',
    'ruff',
    'mypy',
    'black',
    'isort',
    # Search
    'find',
    'grep',
    'rg',
    'fd',
    # Text
    'sed',
    'awk',
    'sort',
    'uniq',
    'cut',
    'tr',
    'diff',
    'column',
    'tee',
    'xargs',
    'jq',
    'yq',
    # Network queries
    'curl',
    'wget',
    'ping',
    'host',
    'dig',
    # System info
    'du',
    'df',
    'free',
    'top',
    'htop',
    'ps',
    'file',
    'stat',
    'md5sum',
    'sha256sum',
    # Binary inspection
    'xxd',
    'hexdump',
    'od',
    'strings',
    'nm',
    'objdump',
    'readelf',
    # Viewers
    'bat',
    'eza',
    'tokei',
    # File creation (non-destructive)
    'mkdir',
    'touch',
    'cp',
    # WASM / CI / Hermes
    'wasm-opt',
    'wasm-bindgen',
    'wasm2wat',
    'wat2wasm',
    'act',
    'hermes',
    # Containers — safe subcommands only
    'podman ps*',
    'podman images*',
    'podman logs *',
    'podman build *',
    'podman run *',
    'podman exec *',
    'podman inspect *',
    'podman top *',
    'podman stats*',
    'docker ps*',
    'docker images*',
    'docker logs *',
    'docker build *',
    'docker run *',
    'docker exec *',
    'docker inspect *',
    'docker top *',
    'docker stats*',
    # Distrobox
    'distrobox-enter',
    'distrobox enter *',
    'distrobox list*',
    'toolbox',
]

_DEFAULT_BLOCKED: List[str] = [
    'rm *-rf *',
    'rm *-fr *',
    'rm -rf *',
    'rm -fr *',
    'podman *prune*',
    'docker *prune*',
    'podman system *',
    'docker system *',
    'podman rm *',
    'docker rm *',
    'podman rmi *',
    'docker rmi *',
]

# Module-level cache: None = not yet loaded, tuple = loaded value.
_config_cache: Optional[Tuple[str, List[str], List[str]]] = None


def _load_config() -> Tuple[str, List[str], List[str]]:
    """Return (mode, allowed, blocked) from config, with caching."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    result = _load_config_uncached()
    _config_cache = result
    return result


def _load_config_uncached() -> Tuple[str, List[str], List[str]]:
    try:
        config = load_config()
    except Exception as exc:
        logger.warning(
            'hermes-allow: failed to load config (%s) — '
            'falling back to allow mode with default allowlist',
            exc,
        )
        return 'allow', list(_DEFAULT_ALLOWED), list(_DEFAULT_BLOCKED)

    try:
        entry = cfg_get(config, 'plugins', 'entries', 'hermes-allow', default={})
        if not isinstance(entry, dict):
            entry = {}

        enabled = entry.get('enabled', True)
        if not enabled:
            logger.debug('hermes-allow: disabled via config')
            return _DISABLED, [], []

        mode = entry.get('mode', 'allow')
        if mode not in ('allow', 'block'):
            logger.warning(
                "hermes-allow: unknown mode %r — falling back to 'allow'", mode
            )
            mode = 'allow'

        allowed = entry.get('allowed', _DEFAULT_ALLOWED)
        blocked = entry.get('blocked', _DEFAULT_BLOCKED)

        if not isinstance(allowed, list):
            logger.warning("hermes-allow: 'allowed' is not a list — using defaults")
            allowed = list(_DEFAULT_ALLOWED)
        if not isinstance(blocked, list):
            logger.warning("hermes-allow: 'blocked' is not a list — using defaults")
            blocked = list(_DEFAULT_BLOCKED)

        logger.debug(
            'hermes-allow: loaded config mode=%r allowed=%d patterns blocked=%d patterns',
            mode,
            len(allowed),
            len(blocked),
        )
        return mode, allowed, blocked

    except Exception as exc:
        logger.warning(
            'hermes-allow: error reading plugin config (%s) — '
            'falling back to allow mode with default allowlist',
            exc,
        )
        return 'allow', list(_DEFAULT_ALLOWED), list(_DEFAULT_BLOCKED)


def _strip_env_prefix(cmd: str) -> str:
    """Remove leading VAR=value tokens from a command string."""
    tokens = cmd.strip().split()
    while tokens and _ENV_PREFIX_RE.match(tokens[0]):
        tokens.pop(0)
    return ' '.join(tokens)


def _is_match(clean: str, pattern: str) -> bool:
    """Match pattern against full cleaned command and its base name."""
    if not clean:
        return False
    base = clean.split()[0]
    return fnmatch.fnmatch(clean, pattern) or fnmatch.fnmatch(base, pattern)


def _check_allow(command: str, patterns: List[str]) -> Optional[str]:
    """Allow mode: every segment must match at least one allowed pattern."""
    for segment in _split_compound(command):
        clean = _strip_env_prefix(segment)
        if not clean:
            continue
        if not any(_is_match(clean, p) for p in patterns):
            base = clean.split()[0]
            logger.debug(
                'hermes-allow: blocking segment %r (no match in allowlist)', clean
            )
            return (
                f"hermes-allow: blocked '{base}' — "
                f'not in allowed list. '
                f'Add to plugins.entries.hermes-allow.allowed '
                f'in ~/.hermes/config.yaml'
            )
    logger.debug('hermes-allow: command allowed: %r', command)
    return None


def _check_block(command: str, patterns: List[str]) -> Optional[str]:
    """Block mode: if any segment matches a blocked pattern, block it."""
    for segment in _split_compound(command):
        clean = _strip_env_prefix(segment)
        if not clean:
            continue
        for pattern in patterns:
            if _is_match(clean, pattern):
                logger.debug(
                    'hermes-allow: blocking segment %r (matched rule %r)',
                    clean,
                    pattern,
                )
                return (
                    f"hermes-allow: blocked '{clean}' — "
                    f"matched blocklist rule '{pattern}'. "
                    f'Adjust plugins.entries.hermes-allow.blocked '
                    f'in ~/.hermes/config.yaml'
                )
    logger.debug('hermes-allow: command allowed: %r', command)
    return None


def register(ctx) -> None:  # type: ignore[no-untyped-def]
    """Plugin entry point."""

    def _pre_tool_call(
        tool_name: str, args: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, str]]:
        if tool_name != 'terminal':
            return None

        command = args.get('command', '')
        if not command:
            return None

        try:
            mode, allowed, blocked = _load_config()
        except Exception as exc:
            # Config load failed entirely after all fallbacks — fail closed.
            logger.error(
                'hermes-allow: unexpected error loading config (%s) — blocking command as a safety measure',
                exc,
            )
            return {
                'action': 'block',
                'message': (
                    'hermes-allow: blocked — plugin encountered an internal error '
                    'and is failing closed. Check logs for details.'
                ),
            }

        if mode == _DISABLED:
            return None

        try:
            if mode == 'allow':
                error = _check_allow(command, allowed)
            else:
                error = _check_block(command, blocked)
        except Exception as exc:
            # Pattern matching failed — fail closed.
            logger.error(
                'hermes-allow: unexpected error checking command %r (%s) — blocking as a safety measure',
                command,
                exc,
            )
            return {
                'action': 'block',
                'message': (
                    'hermes-allow: blocked — plugin encountered an internal error '
                    'and is failing closed. Check logs for details.'
                ),
            }

        if error:
            return {'action': 'block', 'message': error}

        return None

    ctx.register_hook('pre_tool_call', _pre_tool_call)
    logger.info('hermes-allow plugin loaded (mode will be resolved on first call)')
