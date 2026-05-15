# hermes-allow

Terminal command guard plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
Intercepts every `terminal` tool call and either allows or blocks it based on your config —
useful for keeping an agent from running destructive commands by accident.

Two modes:

- **allow** (default) — commands not in the list are blocked. Tight by default.
- **block** — commands in the list are blocked. Everything else passes.

> Not a security boundary. Catches agent mistakes, not adversarial escapes. Bypassable
> via scripting languages, pipes, subshells, or writing scripts with the file tool. For
> real isolation, sandbox the agent or remove the `terminal` tool entirely.

## Install

```bash
git clone https://github.com/stewlab/hermes-allow ~/.hermes/plugins/hermes-allow
```

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - hermes-allow
```

Restart Hermes. Allow mode is active with the default allowlist — no further config needed.

## Pattern matching

Every pattern is tested against both the full command string and the base name (first token).
Either match counts as a hit. Patterns use glob syntax (`*` = wildcard).

| Pattern          | Matches                          | Does not match               |
|------------------|----------------------------------|------------------------------|
| `'git'`          | Any git command                  | —                            |
| `'podman run *'` | `podman run -it fedora bash`     | `podman ps`, `podman prune`  |
| `'podman ps*'`   | `podman ps`, `podman ps -a`      | `podman run`                 |

Rule of thumb: no spaces = matches base name (broad). Spaces = matches full string (specific).

Compound commands (`&&`, `||`, `|`, `;`) are split and each segment is checked independently.

## Allow mode (default)

Ships with a safe allowlist covering common read-only and dev-workflow commands:

```
# Broadly allowed (any invocation)
ls, cat, head, tail, wc, pwd, echo, which, whoami, uname, date,
env, printenv, true, false, test, [
git, git-*, gh
cargo, cargo-*, rustc, rustup, rustfmt
./build.sh, ./run_web.sh, make, cmake, just, task
node, npm, npx
python3, python, pip, pip3, uv, pytest, ruff, mypy, black, isort
find, grep, rg, fd, sed, awk, sort, uniq, cut, tr, diff
column, tee, xargs, jq, yq
curl, wget, ping, host, dig
du, df, free, top, htop, ps, file, stat, md5sum, sha256sum
xxd, hexdump, od, strings, nm, objdump, readelf
bat, eza, tokei
mkdir, touch, cp
wasm-opt, wasm-bindgen, wasm2wat, wat2wasm, act, hermes

# Specific subcommands only (full string match)
podman ps*, podman images*, podman logs *, podman build *,
podman run *, podman exec *, podman inspect *, podman top *, podman stats*
docker ps*, docker images*, docker logs *, docker build *,
docker run *, docker exec *, docker inspect *, docker top *, docker stats*
distrobox-enter, distrobox enter *, distrobox list*
toolbox
```

Commands intentionally absent from defaults (add to your config if needed):

```
rm, mv, chmod, chown, ln     # file mutations — use the file tool instead
kill, killall                # process management
ssh, scp, rsync              # remote access
tar, gzip, zip, unzip        # archives
strace, gdb, valgrind        # debuggers
vim, nano, hx                # interactive editors
```

## Block mode

Permissive baseline — everything passes except the blocklist.

```yaml
plugins:
  entries:
    hermes-allow:
      mode: block
      blocked:
        - 'rm *-rf *'
        - 'podman *prune*'
        - 'docker *prune*'
        - 'podman system *'
        - 'docker system *'
```

Default blocklist (when `blocked` is not set in config):

```
rm *-rf *, rm *-fr *, rm -rf *, rm -fr *
podman *prune*, docker *prune*
podman system *, docker system *
podman rm *, docker rm *
podman rmi *, docker rmi *
```

## Examples

The `→` lines below show what hermes-allow decides — they are not shell output.

```
# allow mode (default)

$ git status
→ allowed

$ rm -rf /tmp/test
→ blocked: 'rm' is not in the allowed list

$ podman system prune -a
→ blocked: 'podman' is not in the allowed list


# block mode

$ git status
→ allowed (not in blocklist)

$ rm -rf /tmp/test
→ blocked: 'rm -rf /tmp/test' matched rule 'rm *-rf *'

$ podman system prune -a
→ blocked: 'podman system prune -a' matched rule 'podman system *'
```

## Full config reference

```yaml
plugins:
  enabled:
    - hermes-allow
  entries:
    hermes-allow:
      enabled: true              # false = plugin is a passthrough (all commands allowed)
      mode: allow                # 'allow' or 'block'

      # When true, the built-in default list is merged with your custom list.
      # When false (default), your custom list fully replaces the defaults.
      persist_defaults: false

      # allow mode: list of permitted patterns. Omit to use the built-in defaults.
      allowed:
        - 'git'
        - 'cargo'
        - 'podman run *'

      # block mode: list of blocked patterns. Omit to use the built-in defaults.
      # Set to [] to run with no blocklist (pure passthrough in block mode).
      blocked:
        - 'rm *-rf *'
        - 'podman *prune*'
```

## Development

### Running the tests

No external dependencies needed — the test suite uses only the standard library.

```bash
python3 tests/test_hermes_allow.py
```

Expected output:

```
============================================================
hermes-allow tests
============================================================

Testing _split_compound()...
  ✓ All tests passed

Testing _strip_env_prefix()...
  ✓ All tests passed

Testing _is_match()...
  ✓ All tests passed

Testing _check_allow()...
  ✓ All tests passed

Testing _check_block()...
  ✓ All tests passed

Testing edge cases...
  ✓ All tests passed

============================================================
Results: 6/6 test groups passed
============================================================
```

### Test coverage

The tests cover the core matching logic in isolation (no Hermes runtime required):

- `_split_compound`: splitting on shell operators while respecting single/double quotes
- `_strip_env_prefix`: env var stripping before matching
- `_is_match`: glob pattern matching against base name and full command
- `_check_allow`: allow mode — safe commands pass, destructive commands block, compound commands, env prefix handling
- `_check_block`: block mode — safe commands pass, blocked patterns fire, compound commands
- Edge cases: empty input, empty pattern lists, case sensitivity

### Known limitations

- Quoted env var values with spaces (`GREETING='hello world' cmd`) are not stripped before matching.
- `rm -rf/path` (no space between flag and path) is not caught by the default blocklist — this requires shell-level parsing.
- Subshells (`$()`, backticks) and pipes to `bash`/`sh` are not inspected — the plugin only sees the outer command string.

## License

MIT
