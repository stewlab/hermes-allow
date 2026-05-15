"""Tests for hermes-allow plugin (stdlib only, no pytest required).

Run with:
    python3 tests/test_hermes_allow.py
"""

import sys
import os
import traceback
from unittest.mock import MagicMock

# Mock hermes_cli before importing the plugin
sys.modules['hermes_cli'] = MagicMock()
sys.modules['hermes_cli.config'] = MagicMock()

# Add parent directory so we can import __init__.py directly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from __init__ import (
    _is_match,
    _check_allow,
    _check_block,
    _strip_env_prefix,
    _split_compound,
    _DEFAULT_ALLOWED,
    _DEFAULT_BLOCKED,
)


# ---------------------------------------------------------------------------
# Minimal assertion helpers
# ---------------------------------------------------------------------------


def assert_equal(a, b, msg=''):
    if a != b:
        raise AssertionError(f'{msg}\n  Expected: {b!r}\n  Got:      {a!r}')


def assert_true(val, msg=''):
    if not val:
        raise AssertionError(f'{msg}\n  Expected True, got {val!r}')


def assert_false(val, msg=''):
    if val:
        raise AssertionError(f'{msg}\n  Expected False, got {val!r}')


def assert_none(val, msg=''):
    if val is not None:
        raise AssertionError(f'{msg}\n  Expected None, got {val!r}')


def assert_not_none(val, msg=''):
    if val is None:
        raise AssertionError(f'{msg}\n  Expected non-None value, got None')


def assert_in(sub, container, msg=''):
    if sub not in container:
        raise AssertionError(f'{msg}\n  {sub!r} not found in {container!r}')


# ---------------------------------------------------------------------------
# _split_compound
# ---------------------------------------------------------------------------


def test_split_compound():
    """_split_compound splits on top-level operators only."""
    print('\nTesting _split_compound()...')

    assert_equal(_split_compound('git status'), ['git status'])
    assert_equal(_split_compound('git status && git log'), ['git status', 'git log'])
    assert_equal(_split_compound('ls; pwd'), ['ls', 'pwd'])
    assert_equal(_split_compound('ls -la || echo no'), ['ls -la', 'echo no'])
    assert_equal(_split_compound('cat f | head'), ['cat f', 'head'])

    # Operators inside double quotes are not splitters
    assert_equal(
        _split_compound('git commit -m "fix: a && b"'),
        ['git commit -m "fix: a && b"'],
    )
    assert_equal(
        _split_compound("git commit -m 'fix: a; b'"),
        ["git commit -m 'fix: a; b'"],
    )

    # Trailing/leading operators produce no empty segments
    assert_equal(_split_compound('git status;'), ['git status'])
    assert_equal(_split_compound(';git status'), ['git status'])
    assert_equal(_split_compound('git status &&'), ['git status'])

    # Empty / whitespace-only
    assert_equal(_split_compound(''), [])
    assert_equal(_split_compound('   '), [])

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# _strip_env_prefix
# ---------------------------------------------------------------------------


def test_strip_env_prefix():
    """_strip_env_prefix removes leading VAR=value tokens."""
    print('\nTesting _strip_env_prefix()...')

    # No env vars — command returned unchanged
    assert_equal(_strip_env_prefix('git status'), 'git status')
    assert_equal(_strip_env_prefix('rm -rf /tmp/test'), 'rm -rf /tmp/test')

    # Single env var
    assert_equal(_strip_env_prefix('FOO=bar git status'), 'git status')
    assert_equal(_strip_env_prefix('PATH=/bin ls'), 'ls')
    assert_equal(_strip_env_prefix('DEBUG=1 cargo test'), 'cargo test')

    # Multiple env vars
    assert_equal(_strip_env_prefix('FOO=bar BAZ=qux git status'), 'git status')
    assert_equal(
        _strip_env_prefix('VAR1=val1 VAR2=val2 VAR3=val3 command arg1 arg2'),
        'command arg1 arg2',
    )

    # Colon-separated values (PATH-style)
    assert_equal(_strip_env_prefix('PATH=/usr/bin:/usr/local/bin ls'), 'ls')

    # Leading/trailing whitespace is stripped
    assert_equal(_strip_env_prefix('  FOO=bar  git status  '), 'git status')

    # Only env vars, no command → empty string
    assert_equal(_strip_env_prefix('FOO=bar BAZ=qux'), '')
    assert_equal(_strip_env_prefix('  FOO=bar  '), '')

    # Empty / whitespace-only input
    assert_equal(_strip_env_prefix(''), '')
    assert_equal(_strip_env_prefix('   '), '')

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# _is_match
# ---------------------------------------------------------------------------


def test_is_match():
    """_is_match tests both base-name and full-string matching."""
    print('\nTesting _is_match()...')

    # --- base-name match (pattern = bare word) ---
    assert_true(_is_match('git', 'git'), 'exact base name')
    assert_true(_is_match('ls', 'ls'), 'exact base name')
    assert_true(_is_match('git status', 'git'), 'base name with args')
    assert_true(_is_match('ls -la /tmp', 'ls'), 'base name with args')
    assert_true(_is_match('podman ps -a', 'podman'), 'base name with args')

    # base-name must be an exact hit — no substring sliding
    assert_false(_is_match('gitk', 'git'), "gitk should not match 'git' pattern")
    assert_false(_is_match('git-status', 'git'), 'git-status base != git')

    # --- wildcard on base name ---
    assert_true(_is_match('git-status', 'git-*'), 'git-* matches git-status')
    assert_true(_is_match('git-push', 'git-*'), 'git-* matches git-push')
    assert_false(_is_match('git', 'git-*'), 'git does not match git-*')
    assert_true(_is_match('cargo-fmt', 'cargo-*'), 'cargo-* matches cargo-fmt')

    # --- full-string pattern with trailing wildcard ---
    assert_true(_is_match('podman ps', 'podman ps*'), 'podman ps exact')
    assert_true(_is_match('podman ps -a', 'podman ps*'), 'podman ps with args')
    assert_true(
        _is_match('podman ps --all --no-trunc', 'podman ps*'), 'podman ps many flags'
    )
    assert_false(_is_match('podman run', 'podman ps*'), 'podman run != podman ps*')
    assert_false(_is_match('podman', 'podman ps*'), 'bare podman != podman ps*')

    # --- full-string pattern with space + wildcard (requires at least one arg) ---
    assert_true(
        _is_match('podman run -it fedora', 'podman run *'), 'podman run with args'
    )
    assert_true(
        _is_match('podman run --rm alpine sh', 'podman run *'), 'podman run --rm'
    )
    assert_false(
        _is_match('podman run', 'podman run *'),
        'podman run bare: no args, space required',
    )
    assert_false(_is_match('podman ps', 'podman run *'), 'podman ps != podman run *')

    # --- blocklist-style multi-wildcard patterns ---
    assert_true(_is_match('rm -rf /tmp/test', 'rm *-rf *'), 'rm -rf pattern')
    assert_true(_is_match('rm -fr /tmp/test', 'rm *-fr *'), 'rm -fr pattern')
    assert_true(_is_match('rm -rf *', 'rm -rf *'), 'rm -rf * literal glob cmd')
    assert_true(
        _is_match('podman run --rm -it fedora bash', 'podman run *'), 'podman run long'
    )

    # --- ./path patterns ---
    assert_true(_is_match('./build.sh', './build.sh'), './build.sh exact')
    assert_true(_is_match('./run_web.sh', './run_web.sh'), './run_web.sh exact')
    assert_false(_is_match('./deploy.sh', './build.sh'), 'different script')

    # --- empty string always returns False ---
    assert_false(_is_match('', 'git'), 'empty command')
    assert_false(_is_match('', '*'), 'empty command vs wildcard')

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# _check_allow  (allow mode)
# ---------------------------------------------------------------------------


def test_check_allow():
    """Allow mode: only explicitly listed commands pass."""
    print('\nTesting _check_allow()...')

    # --- common read-only shell commands ---
    for cmd in [
        'ls',
        'ls -la',
        'ls -la /tmp',
        'cat README.md',
        'head -20 file.txt',
        'tail -f log.txt',
        'wc -l file.txt',
        'pwd',
        'echo hello',
        'which git',
        'whoami',
        'uname -a',
        'date',
        'env',
        'printenv PATH',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- VCS ---
    for cmd in [
        'git status',
        'git log --oneline',
        'git diff HEAD',
        'git push origin main',
        'git pull',
        'git fetch --all',
        'git commit -m "fix: correct off-by-one"',
        'git commit -m "feat: support && operator in messages"',
        'gh pr list',
        'git-lfs status',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Rust toolchain ---
    for cmd in [
        'cargo build',
        'cargo test',
        'cargo check',
        'cargo fmt',
        'cargo clippy',
        'rustc --version',
        'rustup show',
        'rustfmt src/main.rs',
        'cargo-watch -x test',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Python toolchain ---
    for cmd in [
        'python3 script.py',
        'python3 -m pytest',
        'python3 -m mypy src/',
        'pytest tests/',
        'ruff check .',
        'ruff format .',
        'mypy src/',
        'black .',
        'isort .',
        'pip list',
        'pip3 show requests',
        'uv pip install -r requirements.txt',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Build tools ---
    for cmd in [
        'make',
        'make clean',
        'make test',
        'cmake ..',
        'just build',
        'task lint',
        './build.sh',
        './run_web.sh',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Search / text tools ---
    for cmd in [
        "grep -r 'TODO' src/",
        "rg 'fn main'",
        "find . -name '*.rs'",
        "sed 's/foo/bar/g' file.txt",
        "awk '{print $1}' file.txt",
        'sort file.txt',
        'diff a.txt b.txt',
        "jq '.name' data.json",
        'cat file.txt | head -10',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Network queries (read-only) ---
    for cmd in [
        'curl https://example.com',
        'wget https://example.com/file',
        'ping -c 3 8.8.8.8',
        'dig github.com',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- System info ---
    for cmd in [
        'du -sh .',
        'df -h',
        'free -m',
        'ps aux',
        'top -b -n1',
        'stat file.txt',
        'file binary',
        'sha256sum archive.tar.gz',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Non-destructive file ops ---
    for cmd in ['mkdir -p src/lib', 'touch newfile.txt', 'cp src.txt dst.txt']:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Container safe subcommands ---
    for cmd in [
        'podman ps',
        'podman ps -a',
        'podman images',
        'podman images -a',
        'podman logs mycontainer',
        'podman logs -f mycontainer',
        'podman build -t myimage .',
        'podman run -it fedora bash',
        'podman run --rm alpine sh',
        'podman exec mycontainer ls',
        'podman inspect mycontainer',
        'podman top mycontainer',
        'podman stats --no-stream',
        'docker ps',
        'docker ps -a',
        'docker images',
        'docker logs mycontainer',
        'docker build -t myimage .',
        'docker run -it alpine sh',
        'docker exec mycontainer ls',
        'docker inspect mycontainer',
        'docker stats --no-stream',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Distrobox ---
    for cmd in [
        'distrobox-enter',
        'distrobox enter fedora-toolbox',
        'distrobox list',
        'distrobox list --all',
        'toolbox',
    ]:
        assert_none(_check_allow(cmd, _DEFAULT_ALLOWED), f'should allow: {cmd}')

    # --- Explicitly absent (intentionally blocked in default allow mode) ---
    for cmd in [
        'rm file.txt',
        'rm -rf /tmp/test',
        'mv a.txt b.txt',
        'chmod +x script.sh',
        'chown user:group file.txt',
        'ln -s src dst',
        'kill 1234',
        'killall python3',
        'ssh user@host',
        'scp file user@host:/tmp',
        'rsync -av src/ dst/',
        'tar czf archive.tar.gz dir/',
        'gzip file.txt',
        'zip archive.zip file.txt',
        'unzip archive.zip',
        'vim file.txt',
        'nano file.txt',
        'hx file.txt',
        'strace ls',
        'gdb ./binary',
    ]:
        result = _check_allow(cmd, _DEFAULT_ALLOWED)
        assert_not_none(result, f'should block: {cmd}')
        (
            assert_in('not in allowed list', result),
            f'error message format wrong for: {cmd}',
        )

    # --- Dangerous container commands blocked in allow mode ---
    for cmd in [
        'podman system prune -a',
        'podman system reset',
        'podman rm mycontainer',
        'podman rmi myimage',
        'docker system prune',
        'docker rm mycontainer',
        'docker rmi myimage',
    ]:
        result = _check_allow(cmd, _DEFAULT_ALLOWED)
        assert_not_none(result, f'should block: {cmd}')

    # --- Error message includes config path hint ---
    result = _check_allow('vim file.txt', _DEFAULT_ALLOWED)
    assert_not_none(result)
    assert_in('config.yaml', result), 'error message should mention config.yaml'
    assert_in('vim', result), 'error message should name the blocked command'

    # --- Compound commands: all segments must be allowed ---
    for cmd in [
        'git status && git log',
        'ls -la; pwd',
        'cat file.txt | head -10',
        "git status || echo 'not a git repo'",
        'grep -r TODO . | sort | uniq',
    ]:
        assert_none(
            _check_allow(cmd, _DEFAULT_ALLOWED), f'should allow compound: {cmd}'
        )

    # --- Compound commands: one blocked segment blocks the whole command ---
    for cmd in [
        'rm -rf test && cat test',
        'cat test; rm test',
        'git status && chmod +x script.sh',
        'ls | rm -rf test',
    ]:
        result = _check_allow(cmd, _DEFAULT_ALLOWED)
        assert_not_none(result, f'should block compound: {cmd}')

    # --- Env prefix stripped before matching ---
    assert_none(_check_allow('FOO=bar git status', _DEFAULT_ALLOWED))
    assert_none(_check_allow('PATH=/bin ls -la', _DEFAULT_ALLOWED))
    assert_none(_check_allow('DEBUG=1 cargo test', _DEFAULT_ALLOWED))

    result = _check_allow('FOO=bar rm -rf test', _DEFAULT_ALLOWED)
    assert_not_none(result, 'env prefix should not bypass block')
    assert_in('rm', result)

    # "podman run *" requires at least one argument; bare "podman run" is not in the list
    result = _check_allow('podman run', _DEFAULT_ALLOWED)
    assert_not_none(result, 'podman run with no args is not in allowlist')

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# _check_block  (block mode)
# ---------------------------------------------------------------------------


def test_check_block():
    """Block mode: blocked patterns stop the command; everything else passes."""
    print('\nTesting _check_block()...')

    # --- Safe commands pass through ---
    for cmd in [
        'git status',
        'git log',
        'ls -la',
        'cat README.md',
        'python3 script.py',
        'cargo build',
        'ruff check .',
        'curl https://example.com',
        'grep -r TODO .',
        'podman ps',
        'podman ps -a',
        'podman images',
        'podman logs mycontainer',
        'podman run -it fedora bash',
        'docker ps',
        'docker images',
        'docker run -it alpine sh',
        'rm file.txt',
        'rm -r testdir',
        'rm -f file.txt',
        'vim file.txt',
        'ssh user@host',
    ]:
        assert_none(_check_block(cmd, _DEFAULT_BLOCKED), f'should allow: {cmd}')

    # --- rm -rf / rm -fr variants ---
    for cmd in [
        'rm -rf /tmp/test',
        'rm -fr /tmp/test',
        'rm -rf .',
        'rm -fr .',
        'rm -rf *',
        'rm -fr *',
    ]:
        result = _check_block(cmd, _DEFAULT_BLOCKED)
        assert_not_none(result, f'should block: {cmd}')
        assert_in('rm', result.lower())
        assert_in('matched blocklist rule', result.lower())

    # --- Container prune commands ---
    for cmd in [
        'podman prune -a',
        'podman system prune -a',
        'podman system prune --all',
        'podman volume prune',
        'docker prune',
        'docker system prune',
        'docker volume prune',
    ]:
        result = _check_block(cmd, _DEFAULT_BLOCKED)
        assert_not_none(result, f'should block: {cmd}')
        assert_in('matched blocklist rule', result.lower())

    # --- Container system commands ---
    for cmd in [
        'podman system reset',
        'podman system info',
        'docker system df',
        'docker system events',
    ]:
        result = _check_block(cmd, _DEFAULT_BLOCKED)
        assert_not_none(result, f'should block: {cmd}')

    # --- Container remove commands ---
    for cmd in [
        'podman rm mycontainer',
        'podman rm -f mycontainer',
        'podman rm container1 container2',
        'podman rmi myimage',
        'podman rmi myimage:latest',
        'docker rm mycontainer',
        'docker rm -f c1 c2',
        'docker rmi myimage',
        'docker rmi myimage:v1',
    ]:
        result = _check_block(cmd, _DEFAULT_BLOCKED)
        assert_not_none(result, f'should block: {cmd}')

    # --- Error message format: includes matched rule ---
    result = _check_block('rm -rf /tmp', _DEFAULT_BLOCKED)
    assert_not_none(result)
    assert_in('matched blocklist rule', result.lower())
    assert_in('config.yaml', result), 'error message should mention config.yaml'

    result = _check_block('podman system prune -a', _DEFAULT_BLOCKED)
    assert_not_none(result)
    assert_in('matched blocklist rule', result.lower())

    # --- Compound: one blocked segment blocks the whole command ---
    for cmd in [
        'git status && rm -rf /tmp/test',
        'rm -rf test; git status',
        'ls | podman system prune -a',
        'cat test || docker rm mycontainer',
    ]:
        result = _check_block(cmd, _DEFAULT_BLOCKED)
        assert_not_none(result, f'should block compound: {cmd}')

    # --- Compound: all safe segments pass ---
    for cmd in [
        'git status && git log',
        'ls -la; pwd',
        'cat file.txt | grep TODO',
        'rm file.txt; git status',
    ]:
        assert_none(
            _check_block(cmd, _DEFAULT_BLOCKED), f'should allow compound: {cmd}'
        )

    # --- Env prefix stripped before checking blocklist ---
    result = _check_block('FOO=bar rm -rf /tmp/test', _DEFAULT_BLOCKED)
    assert_not_none(result, 'env prefix should not bypass block')

    assert_none(_check_block('FOO=bar git status', _DEFAULT_BLOCKED))
    assert_none(_check_block('DEBUG=1 rm file.txt', _DEFAULT_BLOCKED))

    # --- Empty blocklist: nothing is blocked ---
    assert_none(_check_block('rm -rf /', []), 'empty blocklist blocks nothing')
    assert_none(_check_block('podman system reset', []))

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_cases():
    """Boundary and degenerate inputs."""
    print('\nTesting edge cases...')

    # --- Empty / whitespace-only input is always allowed (no command to block) ---
    assert_none(_check_allow('', _DEFAULT_ALLOWED))
    assert_none(_check_allow('   ', _DEFAULT_ALLOWED))
    assert_none(_check_allow('\t\n', _DEFAULT_ALLOWED))
    assert_none(_check_block('', _DEFAULT_BLOCKED))
    assert_none(_check_block('  \t  ', _DEFAULT_BLOCKED))

    # Extra whitespace inside a command is normalised before matching
    assert_none(_check_allow('git   status', _DEFAULT_ALLOWED))
    result = _check_allow('rm   -rf   test', _DEFAULT_ALLOWED)
    assert_not_none(result)

    # --- Empty pattern list ---
    # Allow mode with empty list blocks everything (no pattern can match)
    result = _check_allow('git status', [])
    assert_not_none(result)
    assert_in('not in allowed list', result)

    result = _check_allow('ls', [])
    assert_not_none(result)

    # Block mode with empty list allows everything
    assert_none(_check_block('rm -rf /', []))
    assert_none(_check_block('podman system reset', []))

    # --- Case sensitivity: patterns and commands are case-sensitive ---
    assert_not_none(_check_allow('Git status', _DEFAULT_ALLOWED), 'Git != git')
    assert_not_none(_check_allow('GIT STATUS', _DEFAULT_ALLOWED), 'GIT != git')
    assert_not_none(_check_allow('CARGO build', _DEFAULT_ALLOWED), 'CARGO != cargo')
    assert_none(_check_allow('git status', _DEFAULT_ALLOWED), 'lowercase matches')
    assert_none(_check_allow('cargo build', _DEFAULT_ALLOWED), 'lowercase matches')

    # Trailing/leading operators — covered by test_split_compound
    assert_none(_check_allow('git status;', _DEFAULT_ALLOWED))
    assert_none(_check_allow(';git status', _DEFAULT_ALLOWED))
    assert_none(_check_allow('git status &&', _DEFAULT_ALLOWED))

    assert_false(_is_match('', 'git'))
    assert_false(_is_match('', ''))
    assert_false(_is_match('', '*'))

    assert_true(_is_match('git status', '*'))
    assert_true(_is_match('rm -rf /', '*'))

    print('  ✓ All tests passed')


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def main():
    print('=' * 60)
    print('hermes-allow tests')
    print('=' * 60)

    test_funcs = [
        test_split_compound,
        test_strip_env_prefix,
        test_is_match,
        test_check_allow,
        test_check_block,
        test_edge_cases,
    ]

    passed = 0
    failed = 0

    for fn in test_funcs:
        try:
            fn()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f'\n✗ {fn.__name__} FAILED:')
            traceback.print_exc()

    print('\n' + '=' * 60)
    print(f'Results: {passed}/{len(test_funcs)} test groups passed')
    if failed:
        print(f'         {failed} test groups FAILED')
    print('=' * 60)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
