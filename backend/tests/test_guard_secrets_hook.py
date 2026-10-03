"""The Claude Code Bash hook that keeps credentials out of tool output.

It is a pattern matcher, so these tests pin both directions: the commands
that must be refused, and the everyday commands that must still run. Run
the hook through its real entry point (JSON on stdin, exit status 2) for
a handful, and call check() directly for the rest.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "guard_secrets.py"
ENV_CHECK = REPO / "scripts" / "env_check.sh"

spec = importlib.util.spec_from_file_location("guard_secrets", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

BLOCKED = [
    # Reading a secrets file, by any verb.
    "sed -n '1,20p' .env.secrets",
    "grep GROQ backend/.env",
    "cat backend/.env",
    "cat ./backend/.env",
    "head -5 /Users/moulik/Developer/memegpt/backend/.env",
    "set -a && . backend/.env && set +a",
    "source .env.secrets",
    "cp backend/.env /tmp/x",
    "awk -F= '{print $2}' .env.secrets",
    "python3 -c \"print(open('.env.secrets').read())\"",
    "cat frontend/.env.local",
    "cat frontend/.env.production.local",
    "cat ~/.zshenv",
    "grep TOKEN ~/.zshrc",
    "cat terraform/terraform.tfstate",
    "cat .env.s*",
    "cat .env*",
    "find . -name '.env*' -exec cat {} \\;",
    "ls .env.secrets | xargs cat",
    "echo $(cat .env.secrets)",
    "cat .env.secrets && ls",
    "cat >> .env.secrets <<'EOF'\nA=1\nEOF",
    "cat <<'EOF'\nhi\nEOF\nprintenv",
    "scripts/env_check.sh GROQ_API_KEY .env.secrets; cat .env.secrets",
    # Dumping the environment.
    "docker compose config",
    "docker-compose config",
    "docker compose -f docker-compose.yml config --format json",
    "docker inspect memegpt-backend",
    "docker exec memegpt-backend env",
    "docker compose exec backend printenv",
    "printenv",
    "printenv GROQ_API_KEY",
    "env",
    "env | grep GROQ",
    "env | sed -E 's/=.*/=<v>/'",
    "export -p",
    "export",
    "set",
    "declare -x",
    "cat /proc/self/environ",
    "ps eww -p 1234",
    "gcloud run services describe memegpt-backend --region=us-central1",
    "gcloud run revisions describe memegpt-backend-00039-r9q",
    "gcloud run services list --format=json",
    "gcloud secrets versions access latest --secret=GROQ_API_KEY",
    "kubectl get secret memegpt-secrets -o yaml",
    "kubectl exec deploy/memegpt -- env",
    "terraform show",
    "terraform state pull",
    "curl -s -H \"Authorization: Bearer $RENDER_API_KEY\" https://api.render.com/v1/services/srv-1/env-vars",
    "vercel env ls",
    "vercel env pull .env.local",
    "vercel pull",
    "curl -s \"https://api.vercel.com/v9/projects/prj_1/env?decrypt=true\"",
    "gh auth token",
    "echo $GROQ_API_KEY",
    "echo \"key is ${VERCEL_TOKEN}\"",
    "printf '%s' \"$DATABASE_URL\"",
    "curl -v -H \"Authorization: Bearer $GROQ_API_KEY\" https://api.groq.com/openai/v1/models",
    "bash -x deploy.sh $GROQ_API_KEY",
    "python3 -c 'import os; print(os.environ)'",
    "python3 -c 'import os; print(dict(os.environ))'",
    "python3 -c 'import os; print(os.environ[\"GROQ_API_KEY\"])'",
    "node -e 'console.log(process.env)'",
    "node -e 'console.log(process.env.GROQ_API_KEY)'",
    "python3 -c 'from config import get_settings; print(get_settings())'",
    "python3 -c 'from config import get_settings; print(get_settings().model_dump())'",
    # Recursive searches that would sweep up the secrets files.
    "grep -rn GROQ_API_KEY .",
    "grep -rn GROQ_API_KEY backend",
    "grep -rIn token ~",
    "rg --hidden --no-ignore GROQ",
]

ALLOWED = [
    "git status --short",
    "git log --oneline | head -5",
    "git diff --stat",
    "ls -la",
    "ls -l .env.secrets",
    "chmod 600 .env.secrets",
    "touch .env.secrets",
    "[ -f .env.secrets ] && echo present",
    "wc -c < .env.secrets",
    "git check-ignore -v .env.secrets",
    "cat .env.example",
    "cat .env.secrets.example",
    "cat backend/.env.example",
    "sed -n 1,20p .env",
    "grep -c '^LLM_PROVIDER=' .env",
    "scripts/env_check.sh GROQ_API_KEY",
    "scripts/env_check.sh GROQ_API_KEY .env.secrets",
    "./scripts/env_check.sh DATABASE_URL backend/.env",
    "cd backend && ../scripts/env_check.sh GROQ_API_KEY .env",
    "gcloud secrets versions list GROQ_API_KEY",
    "gcloud secrets list",
    "gcloud run revisions list --service=memegpt-backend --region=us-central1",
    "scripts/cloudrun_status.sh",
    "gh secret list",
    "gh run list --limit 3",
    "vercel env add BACKEND_URL preview",
    "vercel ls",
    "env FOO=1 pytest -q",
    "env -i PATH=/usr/bin ls",
    "export FOO=bar",
    "set -euo pipefail",
    "set -a && . ./.env && set +a",
    "echo $GROQ_MODEL",
    "echo done; ls",
    "./scripts/verify_safe.sh backend/.venv/bin/python -m pytest -q backend",
    "terraform plan",
    "terraform fmt -check",
    "docker compose up -d --build",
    "docker compose ps",
    "docker compose logs backend --tail 50",
    "docker ps",
    "kubectl get pods",
    "grep -rn parse_intent backend/routers backend/nlp",
    "grep -rn GROQ_API_KEY --include='*.py' backend",
    "grep -rn GROQ_API_KEY --exclude='.env*' .",
    "rg GROQ_API_KEY",
    "python3 -c \"import os; print('GROQ_API_KEY' in os.environ)\"",
    "node -e 'console.log(process.env.NODE_ENV)'",
    "curl -s https://memegpt-backend-2jxpla5n2a-uc.a.run.app/health",
    "curl -sv https://example.com/health",
    "git commit -m \"A setting gets a talking-to\"",
    "git commit -m \"$(cat <<'EOF'\nA job stops winging it\n\nsee .env.secrets, printenv, docker compose config\nEOF\n)\"",
    "cat >> notes.md <<'EOF'\nnever run printenv or docker compose config; keep .env.secrets private\nEOF",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocked(command):
    assert guard.check(command, str(REPO)) is not None, command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command):
    assert guard.check(command, str(REPO)) is None, command


def test_bare_dotenv_is_secret_only_inside_backend():
    assert guard.check("cat .env", str(REPO)) is None
    assert guard.check("cat .env", str(REPO / "backend")) is not None
    assert guard.check("cd backend && cat .env", str(REPO)) is not None
    assert guard.check("grep GROQ ./.env", str(REPO / "backend")) is not None
    assert guard.check("cat .env.example", str(REPO / "backend")) is None


def test_helper_cannot_smuggle_a_second_command():
    ok = "scripts/env_check.sh GROQ_API_KEY .env.secrets"
    assert guard.check(ok, str(REPO)) is None
    for tail in ("; cat .env.secrets", " && printenv", " | cat backend/.env", " $(cat .env.secrets)"):
        assert guard.check(ok + tail, str(REPO)) is not None, tail


def run_hook(command, cwd=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or str(REPO)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)


@pytest.mark.parametrize("command", ["sed -n '1,20p' .env.secrets", "grep GROQ backend/.env", "docker compose config"])
def test_entry_point_blocks_with_exit_2_and_points_at_helper(command):
    result = run_hook(command)
    assert result.returncode == 2
    assert "scripts/env_check.sh" in result.stderr
    assert result.stdout == ""


def test_entry_point_allows_ordinary_command():
    assert run_hook("git status --short").returncode == 0


def test_entry_point_fails_closed_on_garbage_input():
    result = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert result.returncode == 2


def test_entry_point_ignores_other_tools():
    payload = {"tool_name": "Read", "tool_input": {"file_path": "x"}}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)
    assert result.returncode == 0


# --- scripts/env_check.sh -------------------------------------------------

def env_check(*args, env=None):
    return subprocess.run([str(ENV_CHECK), *args], capture_output=True, text=True, env=env)


def test_env_check_reports_length_only(tmp_path):
    f = tmp_path / "t.env"
    f.write_text(
        "A=abcde\nexport B=\"quoted val\"  # c\nC=\nD=plain # trailing\nE='single'\nF=crlf\r\nA=final12\n"
    )
    expected = {"A": "set (7 chars)", "B": "set (10 chars)", "C": "unset", "D": "set (5 chars)", "E": "set (6 chars)", "F": "set (4 chars)", "NOPE": "unset"}
    for var, out in expected.items():
        result = env_check(var, str(f))
        assert result.stdout.strip() == out, var
        assert result.returncode == (0 if out.startswith("set") else 1)


def test_env_check_never_prints_the_value(tmp_path):
    secret = "gsk_ThisIsNotARealKeyJustATestFixture123"
    f = tmp_path / "t.env"
    f.write_text(f"GROQ_API_KEY={secret}\n")
    result = env_check("GROQ_API_KEY", str(f))
    assert secret not in result.stdout + result.stderr
    assert "gsk_" not in result.stdout + result.stderr
    assert result.stdout.strip() == f"set ({len(secret)} chars)"


def test_env_check_reads_the_environment_when_no_file_given():
    import os

    env = {**os.environ, "ENV_CHECK_PROBE": "twelve chars"}
    assert env_check("ENV_CHECK_PROBE", env=env).stdout.strip() == "set (12 chars)"
    env.pop("ENV_CHECK_PROBE")
    assert env_check("ENV_CHECK_PROBE", env=env).stdout.strip() == "unset"


def test_env_check_missing_file_and_bad_usage(tmp_path):
    assert env_check("A", str(tmp_path / "nope.env")).stdout.strip() == "unset"
    assert env_check("A;rm").returncode == 2
    assert env_check().returncode == 2
