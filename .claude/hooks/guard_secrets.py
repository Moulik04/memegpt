#!/usr/bin/env python3
"""PreToolUse hook for Bash: refuse commands that would print a credential.

Two things get blocked:

  * commands that mention a secrets file (backend/.env, .env.secrets, shell
    profiles that export tokens, tfstate, ...), other than harmless
    metadata verbs like `ls` or `chmod`
  * commands that dump environment variables or cloud config that embeds
    them (printenv, bare env, docker compose config, docker inspect,
    gcloud run describe, Render/Vercel env listings, ...)

scripts/env_check.sh is the sanctioned way to ask "is this set?".

This is a pattern matcher over the command text, so it stops the accidental
paths (a stray grep, a debug dump), not a deliberately obfuscated command.
The Read/Grep deny rules in settings.json cover the file tools.

Exit status 2 blocks the call and sends stderr back to the model. Any
unexpected error also blocks: a guard that fails open is not a guard.
"""
import json
import os
import re
import shlex
import sys

HELPER = r"(?:\./)?scripts/env_check\.sh(?:[ \t]+[A-Za-z0-9_./~-]+){1,2}"

FILE_MSG = (
    "Blocked: this command would read or touch a secrets file. Don't open it. "
    "To check whether a variable is set, run: scripts/env_check.sh VAR [FILE] "
    "(prints only 'set (N chars)' or 'unset')."
)
ENV_MSG = (
    "Blocked: this command would dump environment variables or config that "
    "embeds them. To check one variable, run: scripts/env_check.sh VAR [FILE] "
    "(prints only 'set (N chars)' or 'unset'). For the live Cloud Run service, "
    "run scripts/cloudrun_status.sh."
)
GREP_MSG = (
    "Blocked: a recursive search from here would read secrets files and print "
    "matching lines. Add --exclude='.env*', narrow it with --include='*.py', "
    "or point it at a specific source directory."
)

# A command that mentions one of these paths is blocked (unless every
# mention sits in a harmless-verb segment, see HARMLESS).
PROTECTED = [
    r"\.env\.secrets(?!\.example\b)",
    r"(?:^|[\s/'\"=<>(])backend/\.env(?![\w.-])",
    r"\.env\.local\b",
    r"\.env\.[\w-]+\.local\b",
    r"\.env\.(?:production|prod|staging)\b",
    r"\.vercel/\.env",
    r"\.dev\.vars\b",
    r"\.(?:zshenv|zshrc|zprofile|bash_profile|bashrc|profile)\b",
    r"\.tfvars\b",
    r"\.tfstate\b",
    r"\.netrc\b",
    r"\.aws/credentials",
    r"\.config/gcloud",
    r"\.config/gh/hosts",
    r"\.docker/config\.json",
    r"\.npmrc\b",
    r"\.ssh/(?:id_|[\w.-]*_key)",
    r"\.pem\b",
    r"service[-_]?account[\w.-]*\.json",
    # A glob that would expand to .env.secrets (but not `--exclude='.env*'`).
    r"(?<!--exclude=)(?<!--exclude=')(?<!--exclude=\")(?<!--exclude )\.env[\w.-]*[*?\[]",
]

# Verbs that only look at metadata. A segment starting with one of these may
# name a secrets file, so `chmod 600 .env.secrets` and `ls -l backend/.env`
# keep working.
HARMLESS = {"ls", "stat", "chmod", "chown", "touch", "mkdir", "test", "[", "[[", "wc", "file", "realpath", "readlink", "du"}
HARMLESS_GIT = {"check-ignore", "ls-files", "status"}

ENV_DUMPS = [
    r"\bdocker(?:-compose|\s+compose)\b.*\bconfig\b",
    r"\bdocker\s+(?:\w+\s+)?inspect\b",
    r"\bdocker(?:-compose|\s+compose)?\s+(?:exec|run)\b.*(?<![\w-])(?:env|printenv)(?:\s|$)",
    r"/proc/[^\s/]*/environ",
    r"\bps\s+(?:[^|;&]*\s)?(?:eww?|auxe|axe|-Eww?)(?:\s|$)",
    r"\blaunchctl\s+(?:getenv|export|print)\b",
    r"\bgcloud\s+secrets\s+versions\s+access\b",
    r"\bgcloud\s+run\s+(?:services|revisions|jobs|executions)\s+describe\b",
    r"\bgcloud\s+run\s+(?:services|revisions|jobs)\s+list\b.*--format[= ]['\"]?(?:json|yaml)",
    r"\bkubectl\s+(?:get|describe)\s+(?:secrets?|cm|configmaps?)\b",
    r"\bkubectl\s+get\s+\S+.*-o\s*(?:json|yaml)",
    r"\bkubectl\s+exec\b.*(?<![\w-])(?:env|printenv)(?:\s|$)",
    r"\bterraform\s+(?:show|state\s+(?:pull|show)|output\s+(?:-json|-raw))\b",
    r"api\.render\.com\S*/(?:env-vars|secret-files)",
    r"\bvercel\s+(?:env\s+(?:ls|list|pull|run)|pull)\b",
    r"api\.vercel\.com\S*/env\b",
    r"\bgh\s+auth\s+token\b",
    r"\bgh\s+auth\s+status\b.*(?:\s-t\b|--show-token)",
    # Echoing a secret-named variable.
    r"\b(?:echo|printf|print)\b[^|;&]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|DATABASE_URL|CREDENTIAL|OIDC)",
    # Dumping a process environment or settings object from a script.
    r"(?<!\bin\s)os\.environ(?!\s*\[|\.get\b|\.pop\b|\.setdefault\b|\.update\b)",
    r"(?:print|log\w*|dumps|repr)\s*\([^)]*os\.(?:environ|getenv)[^)]*(?:KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL)",
    r"process\.env(?!\s*\.\w|\s*\[)",
    r"console\.log\([^)]*process\.env\.\w*(?:KEY|TOKEN|SECRET|PASSWORD)",
    r"print\(\s*(?:get_)?settings(?:\(\))?\s*\)",
    r"\b(?:get_)?settings(?:\(\))?\.(?:model_dump|dict|json)\(",
]

SECRET_VAR = r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|DATABASE_URL|CREDENTIAL)"


def strip_message_heredocs(cmd: str) -> str:
    """Drop the body of `cat <<EOF ... EOF` heredocs (commit messages, PR
    bodies, notes written to a file). `cat` only prints or writes the body,
    so nothing in it executes. A path it writes to is still checked: that
    stays on the `cat` line, outside the body."""
    pat = re.compile(r"(cat\s*(?:>>?\s*\S+\s*)?<<-?\s*(['\"]?)(\w+)\2[^\n]*\n)(.*?)(\n[ \t]*\3\b)", re.S)
    return pat.sub(r"\1\5", cmd)


def split_segments(cmd: str):
    return [s.strip() for s in re.split(r"&&|\|\||[;&|\n]", cmd) if s.strip()]


def words(segment: str):
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        toks = segment.split()
    # Drop leading VAR=value assignments and wrappers.
    while toks and (re.match(r"^[A-Za-z_]\w*=", toks[0]) or toks[0] in {"sudo", "command", "time", "nohup", "builtin"}):
        toks = toks[1:]
    return toks


def is_harmless(segment: str, toks) -> bool:
    if not toks or re.search(r"\$\(|`|<\(|>\(", segment):
        return False
    if toks[0] in HARMLESS:
        return True
    return toks[0] == "git" and len(toks) > 1 and toks[1] in HARMLESS_GIT


def dumps_env(toks) -> bool:
    if not toks:
        return False
    first, rest = toks[0], toks[1:]
    if first == "printenv":
        return True
    if first == "env":
        return all(t.startswith("-") for t in rest)  # `env` / `env -0`, not `env VAR=x cmd`
    if first == "export":
        return not rest or rest == ["-p"]
    if first == "set":
        return not rest
    if first in {"declare", "typeset"}:
        return any(re.match(r"^-[a-zA-Z]*[xp]", t) for t in rest) or not rest
    return False


def in_backend_dir(cmd: str, cwd: str) -> bool:
    if re.search(r"\b(?:cd|pushd)\s+['\"]?[^\s;&|'\"]*backend(?:/|\b)", cmd):
        return True
    real = os.path.realpath(cwd or ".")
    return real.endswith("/backend") or "/backend/" in real + "/"


def risky_recursive_search(segment: str, toks) -> bool:
    if not toks:
        return False
    tool, args = toks[0], toks[1:]
    if tool in {"grep", "egrep", "fgrep"}:
        recursive = any(re.match(r"^-[a-zA-Z]*[rR]", a) or a in {"--recursive", "--dereference-recursive"} for a in args)
    elif tool in {"rg", "ag"}:
        recursive = any(a in {"-uu", "-u", "--no-ignore", "--hidden", "--unrestricted", "-."} for a in args)
    else:
        return False
    if not recursive:
        return False
    if re.search(r"--include", segment) or re.search(r"--exclude(?:-from)?[= ]\S*env", segment):
        return False
    plain = [a for a in args if not a.startswith("-")]
    targets = plain[1:] if plain else []  # first plain arg is the pattern
    if not targets:
        return True
    broad = {".", "./", "..", "../", "~", "/", "*", "./*", "backend", "backend/", "./backend", "./backend/"}
    for t in targets:
        t = os.path.expanduser(t)
        if t in broad or t.rstrip("/").endswith("/backend") or t.rstrip("/") in {os.path.expanduser("~"), "/Users"}:
            return True
        if os.path.isdir(t) and any(os.path.isfile(os.path.join(t, n)) for n in (".env", ".env.local", ".env.secrets")):
            return True
    return False


def check(command: str, cwd: str = ""):
    """Return an error message if the command must be blocked, else None."""
    cmd = strip_message_heredocs(command)
    # The sanctioned helper may name a secrets file; nothing else rides along.
    cmd = re.sub(HELPER, "scripts/env_check.sh", cmd)
    segments = split_segments(cmd)
    parsed = [(s, words(s)) for s in segments]
    # `ls .env.secrets | xargs cat` would turn a harmless listing into a read.
    allow_harmless = not re.search(r"\bxargs\b", cmd)

    backend_cd = in_backend_dir(cmd, cwd)
    for seg, toks in parsed:
        # Message-bearing commands: only look at them if they run something.
        if toks[:2] in (["git", "commit"], ["git", "tag"]) or toks[:3] in (["gh", "pr", "create"], ["gh", "pr", "edit"], ["gh", "pr", "comment"]):
            if not re.search(r"\$\(|`", seg):
                continue
        if dumps_env(toks):
            return ENV_MSG
        for pat in ENV_DUMPS:
            if re.search(pat, seg):
                return ENV_MSG
        if re.search(r"\bcurl\b", seg) and re.search(r"(?:\s-[a-zA-Z]*v[a-zA-Z]*\b|--verbose|--trace)", seg) \
                and re.search(r"Authorization|Bearer|--user|\s-u\s|\$\{?\w*" + SECRET_VAR, seg):
            return ENV_MSG
        if re.search(r"(?:\bset\s+-[a-zA-Z]*x|\b(?:ba|z)?sh\s+-[a-zA-Z]*x|-o\s+xtrace)", seg) and re.search(SECRET_VAR, seg):
            return ENV_MSG
        if risky_recursive_search(seg, toks):
            return GREP_MSG
        if re.search(r"\bfind\b", seg) and re.search(r"-(?:exec|execdir|ok)\b", seg) and re.search(r"\.env", seg):
            return FILE_MSG
        if allow_harmless and is_harmless(seg, toks):
            continue
        for pat in PROTECTED:
            if re.search(pat, seg):
                return FILE_MSG
        if backend_cd and re.search(r"(?:^|[\s'\"=<>(])(?:\./)?\.env(?:$|[\s'\";)<>])", seg):
            return FILE_MSG
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name", "Bash") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command") or ""
        message = check(command, payload.get("cwd") or "")
    except Exception as exc:  # fail closed
        print(f"Blocked: guard_secrets could not evaluate this command ({type(exc).__name__}).", file=sys.stderr)
        return 2
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
