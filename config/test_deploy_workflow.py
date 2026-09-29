"""deploy.yaml: migrations run as a Cloud Run job before traffic moves (SERBITO-323)."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yaml").read_text("utf-8"))
ENV = WORKFLOW["env"]
STEPS = WORKFLOW["jobs"]["deploy"]["steps"]


def _index(predicate) -> int:
    matches = [i for i, step in enumerate(STEPS) if predicate(step)]
    assert len(matches) == 1, matches
    return matches[0]


DETECT = _index(lambda s: s.get("id") == "migrations")
MIGRATE = _index(lambda s: "gcloud run jobs deploy" in s.get("run", ""))
DEPLOY = _index(lambda s: "gcloud run deploy" in s.get("run", ""))
TRIVY = _index(lambda s: "trivy image" in s.get("run", ""))


def test_migrate_job_runs_after_the_gate_and_before_the_traffic_switch():
    # Trivy-gated image -> decide -> migrate -> only then the revision that takes traffic.
    assert TRIVY < DETECT < MIGRATE < DEPLOY
    assert "--no-traffic" not in STEPS[DEPLOY]["run"]  # this step is the traffic switch


def test_failed_migration_stops_the_deploy():
    migrate = STEPS[MIGRATE]
    run = migrate["run"]
    assert migrate["if"] == "steps.migrations.outputs.changed == 'true'"
    assert '"$MIGRATE_JOB"' in run and ENV["MIGRATE_JOB"]
    assert "--args=manage.py,migrate,--noinput" in run
    # --execute-now --wait: gcloud exits non-zero when the execution fails -> job fails.
    assert "--execute-now" in run and "--wait" in run
    assert "--max-retries 0" in run
    for step in STEPS[DETECT : DEPLOY + 1]:
        assert not step.get("continue-on-error"), step.get("name")
    assert "if" not in STEPS[DEPLOY]


def test_job_and_service_share_image_identity_and_settings():
    migrate, deploy = STEPS[MIGRATE]["run"], STEPS[DEPLOY]["run"]
    for needle in (
        "$AR_IMAGE:${{ github.sha }}",
        "$RUNTIME_SA",
        "$CLOUDSQL_INSTANCE",
        "$RUN_SECRETS",
        "$RUNNER_TEMP/deploy.env.yaml",
    ):
        assert needle in migrate and needle in deploy, needle
    assert "DATABASE_URL=javi-database-url:latest" in ENV["RUN_SECRETS"]


def test_checkout_has_history_for_the_migration_diff():
    assert STEPS[0]["uses"].startswith("actions/checkout@")
    assert STEPS[0]["with"]["fetch-depth"] == 0


# --- The detection script, run as-is against a throwaway repo and a fake gcloud ----------

FAKE_GCLOUD = """#!/bin/sh
case "$*" in
  "run jobs describe"*) [ -n "$FAKE_JOB_EXISTS" ] ;;
  "run services describe"*) [ -n "$FAKE_LIVE_IMAGE" ] && echo "$FAKE_LIVE_IMAGE" ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gcloud").write_text(FAKE_GCLOUD)
    (bin_dir / "gcloud").chmod(0o755)

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=work,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(path, message):
        file = work / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(message)
        git("add", "-A")
        git("commit", "-qm", message)
        return git("rev-parse", "HEAD")

    def detect(job_exists=True, live_image=""):
        output = tmp_path / "github_output"
        output.write_text("")
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GITHUB_OUTPUT": str(output),
            "MIGRATE_JOB": "javi-migrate",
            "SERVICE": "javi",
            "REGION": "europe-west1",
            "FAKE_JOB_EXISTS": "1" if job_exists else "",
            "FAKE_LIVE_IMAGE": live_image,
        }
        # GitHub's default run shell: bash -e -o pipefail.
        subprocess.run(
            ["bash", "-eo", "pipefail", "-c", STEPS[DETECT]["run"]],
            cwd=work,
            env=env,
            check=True,
            capture_output=True,
        )
        return output.read_text().strip()

    git("init", "-q")
    return commit, git, detect


def image(sha):
    return f"europe-west1-docker.pkg.dev/serbito/javi/javi:{sha}"


def test_detect_skips_when_no_migration_changed_since_the_live_commit(repo):
    commit, _, detect = repo
    live = commit("deliveries/migrations/0001_initial.py", "initial")
    commit("deliveries/views.py", "code only")
    commit("deliveries/migrations/__init__.py", "package marker")
    assert detect(live_image=image(live)) == "changed=false"


def test_detect_runs_when_a_migration_changed_since_the_live_commit(repo):
    commit, _, detect = repo
    live = commit("deliveries/views.py", "live")
    commit("deliveries/migrations/0012_new.py", "migration")
    assert detect(live_image=image(live)) == "changed=true"


def test_detect_baseline_is_the_live_commit_not_the_previous_tag(repo):
    # A tag whose deploy failed carries migrations the DB never got; diffing against that
    # tag would skip them. The live image's commit is the baseline.
    commit, git, detect = repo
    live = commit("deliveries/views.py", "live")
    commit("deliveries/migrations/0012_new.py", "failed release")
    git("tag", "v0.2.0")
    commit("deliveries/views.py", "next release")
    assert detect(live_image=image(live)) == "changed=true"


def test_detect_falls_back_to_the_previous_tag(repo):
    commit, git, detect = repo
    commit("deliveries/migrations/0001_initial.py", "initial")
    git("tag", "v0.1.0")
    commit("deliveries/views.py", "code only")
    assert detect(live_image="") == "changed=false"
    commit("notifications/migrations/0006_x.py", "migration")
    assert detect(live_image=image("0" * 40)) == "changed=true"


@pytest.mark.parametrize("job_exists", [True, False])
def test_detect_is_fail_safe(repo, job_exists):
    commit, _, detect = repo
    commit("deliveries/views.py", "a")
    commit("deliveries/views.py", "b")
    # No job yet (first deploy after SERBITO-323) or no baseline at all -> migrate.
    assert detect(job_exists=job_exists, live_image="") == "changed=true"


def test_admin_path_comes_from_secret_manager():
    # SERBITO-362: the admin's URL is not in the public repo; without it the admin is off.
    assert "ADMIN_PATH=javi-admin-path:latest" in ENV["RUN_SECRETS"]
