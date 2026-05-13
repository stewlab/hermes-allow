# hermes-allow

Terminal command guard for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Two modes:

- **allow** (default) — not in the list = blocked. Tight by default.
- **block** — in the list = blocked. Everything else passes.

## Pattern matching

Every pattern is tried against the full command string AND the base name (first token). Either hit counts.

| Pattern | Matches | Doesn't |
|---------|---------|---------|
| `"git"` | All git commands | — |
| `"podman run *"` | `podman run -it fedora bash` | `podman ps`, `podman prune` |
| `"podman ps*"` | `podman ps`, `podman ps -a` | `podman run` |

No spaces = matches base name (broad). Spaces = matches full string (specific).

Compound commands (`&&`, `||`, `|`, `;`) are split and every segment is checked independently.

## Install

```bash
git clone <repo-url> ~/.hermes/plugins/hermes-allow
```

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - hermes-allow
```

Restart Hermes.

## Default: allow mode

No config needed. Ships with a safe allowlist:

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

**Not in defaults** (add if needed):

```
rm, mv, chmod, chown, ln          # file mutations — use file tool
kill, killall                      # process management
ssh, scp, rsync                    # remote access
tar, gzip, zip, unzip             # archives
strace, gdb, valgrind             # debug
vim, nano, hx                     # interactive editors
```

## Block mode

Permissive — let everything through except specific dangerous commands.

```yaml
plugins:
  entries:
    hermes-allow:
      mode: block
      blocked:
        - "rm *-rf *"
        - "podman *prune*"
        - "docker *prune*"
        - "podman system *"
        - "docker system *"
```

Default blocklist (used when `blocked` is not set):

```
rm *-rf *, rm *-fr *, rm -rf *, rm -fr *
podman *prune*, docker *prune*
podman system *, docker system *
podman rm *, docker rm *
podman rmi *, docker rmi *
```

## Full config reference

```yaml
plugins:
  enabled:
    - hermes-allow
  entries:
    hermes-allow:
      enabled: true              # false = passthrough
      mode: allow                # "allow" or "block"

      # Used in allow mode. Defaults shown above; set to override.
      allowed:
        - "git"
        - "cargo"
        - "podman run *"

      # Used in block mode. Defaults shown above; set to override.
      # Also set blocked: [] to run with no blocklist.
      blocked:
        - "rm *-rf *"
        - "podman *prune*"
```

## Examples

```
# allow mode (default)

$ git status
→ allowed

$ podman system prune -a
→ hermes-allow: blocked 'podman' — not in allowed list.

$ rm -rf /tmp/test
→ hermes-allow: blocked 'rm' — not in allowed list.


# block mode

$ git status
→ allowed (not in blocklist)

$ podman system prune -a
→ hermes-allow: blocked 'podman system prune -a' — matched blocklist rule 'podman system *'.

$ rm -rf /tmp/test
→ hermes-allow: blocked 'rm -rf /tmp/test' — matched blocklist rule 'rm *-rf *'.
```

## Not a security boundary

Catches agent mistakes, not adversarial escapes. Bypassable via scripting languages, pipes, subshells, or writing scripts with the file tool. For real isolation, sandbox the agent or remove the `terminal` tool entirely.

## License

MIT
