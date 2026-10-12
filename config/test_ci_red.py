"""CI red alert (SERBITO-613): a red run on main or on a tag opens ONE SERBITO Jira issue.

The workflow lists the workflows it watches by name: the list must cover every workflow that
runs outside pull requests. The alert script runs here against fake `gh` and `curl`.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
RED = yaml.safe_load((WORKFLOWS / "ci-red.yml").read_text("utf-8"))
JOB = RED["jobs"]["jira"]
STEP = JOB["steps"][0]


def _triggers(workflow):
    on = workflow.get("on", workflow.get(True))  # PyYAML reads the bare key `on` as True
    return {on} if isinstance(on, str) else set(on)


def test_watches_every_workflow_that_runs_outside_pull_requests():
    names = set()
    for path in WORKFLOWS.glob("*.y*ml"):
        wf = yaml.safe_load(path.read_text("utf-8"))
        if path.name != "ci-red.yml" and _triggers(wf) != {"pull_request"}:
            names.add(wf["name"])
    watched = RED[True]["workflow_run"]
    assert set(watched["workflows"]) == names
    assert watched["types"] == ["completed"]


def test_only_failures_on_main_or_a_tag_and_never_a_pull_request():
    cond = JOB["if"]
    assert "github.event.workflow_run.conclusion == 'failure'" in cond
    assert "github.event.workflow_run.event != 'pull_request'" in cond
    assert "head_repository.full_name == github.repository" in cond
    assert "head_branch == 'main'" in cond and "startsWith(" in cond


def test_minimal_permissions_and_no_actions():
    assert RED["permissions"] == {}
    assert JOB["permissions"] == {"actions": "read"}
    assert all("uses" not in step for step in JOB["steps"])
    assert JOB["runs-on"] == "ubuntu-24.04" and JOB["timeout-minutes"] <= 10


@pytest.fixture
def alert(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = api ]; then echo "verify / pytest"; exit 0; fi\n'
        'printf "verify\\tpytest\\t2026-10-12T10:00:00.0000000Z \\033[31mE   AssertionError: boom'
        '\\033[0m\\n"\n'
    )
    # curl: the search answers from search.json; a create answers with a key. Every request
    # body (stdin) is saved by URL tail.
    (bin_ / "curl").write_text(
        "#!/bin/sh\n"
        'for a; do url="$a"; done\n'
        'case "$url" in\n'
        f'  */search/jql) cat > "{tmp_path}/search-body"; cat "{tmp_path}/search.json";;\n'
        f'  */comment) cat > "{tmp_path}/comment-body";;\n'
        f'  */issue) cat > "{tmp_path}/create-body"; echo \'{{"key": "SERBITO-999"}}\';;\n'
        "esac\n"
    )
    for stub in bin_.iterdir():
        stub.chmod(0o755)

    def run(found=(), email="bot@example.com"):
        issues = [{"key": k, "fields": {"summary": s}} for k, s in found]
        (tmp_path / "search.json").write_text(json.dumps({"issues": issues}))
        env = {
            **os.environ,
            **{k: str(v) for k, v in STEP["env"].items() if not str(v).startswith("${{")},
            "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
            "JIRA_EMAIL": email,
            "JIRA_API_TOKEN": "token" if email else "",
            "GH_TOKEN": "x",
            "REPO": "alxndr-bnd/javi",
            "RUN_ID": "42",
            "RUN_ATTEMPT": "1",
            "RUN_URL": "https://github.com/alxndr-bnd/javi/actions/runs/42",
            "WORKFLOW": "CI",
            "HEAD_BRANCH": "main",
            "HEAD_SHA": "0123456789abcdef0123456789abcdef01234567",
            "EVENT": "push",
        }
        return subprocess.run(
            ["bash", "-c", STEP["run"]],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    return run, tmp_path


def test_no_secrets_skips_green_with_a_notice(alert):
    run, tmp = alert
    r = run(email="")
    assert r.returncode == 0, r.stderr
    assert "::notice::JIRA_EMAIL / JIRA_API_TOKEN are not set" in r.stdout
    assert not (tmp / "search-body").exists() and not (tmp / "create-body").exists()


def test_first_red_run_opens_a_highest_bug(alert):
    run, tmp = alert
    r = run(found=[("SERBITO-1", "CI red: javi / Deploy to Cloud Run")])
    assert r.returncode == 0, r.stderr
    assert "opened https://serbito.atlassian.net/browse/SERBITO-999" in r.stdout
    fields = json.loads((tmp / "create-body").read_text())["fields"]
    assert fields["summary"] == "CI red: javi / CI"
    assert fields["labels"] == ["ci-red", "bug"]
    assert fields["priority"] == {"name": "Highest"} and fields["issuetype"] == {"name": "Bug"}
    assert fields["project"] == {"key": "SERBITO"}
    desc = fields["description"]
    assert "https://github.com/alxndr-bnd/javi/actions/runs/42" in desc
    assert "verify / pytest" in desc
    assert "E   AssertionError: boom" in desc and "\x1b" not in desc
    assert 'labels = "ci-red"' in json.loads((tmp / "search-body").read_text())["jql"]


def test_next_red_run_comments_on_the_open_issue(alert):
    run, tmp = alert
    r = run(found=[("SERBITO-7", "CI red: javi / CI")])
    assert r.returncode == 0, r.stderr
    assert "added to https://serbito.atlassian.net/browse/SERBITO-7" in r.stdout
    assert not (tmp / "create-body").exists()
    body = json.loads((tmp / "comment-body").read_text())["body"]
    assert body.startswith("Red again.") and "E   AssertionError: boom" in body
