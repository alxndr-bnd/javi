"""deploy.yaml: migrations run as a Cloud Run job before traffic moves (SERBITO-323); a weekly
refresh rebuilds and redeploys the newest release tag, with a smoke check and rollback
(SERBITO-401)."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
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
        '"$IMAGE"',
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


def _clean_env(**extra):
    # No inherited GIT_*: inside a git hook they point at the REAL repository.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", **extra)
    return env


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
            env=_clean_env(),
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

    git("init", "-q", "-b", "main")
    assert Path(git("rev-parse", "--absolute-git-dir")).resolve() == (work / ".git").resolve()
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


def test_trivy_comes_from_a_checksum_pinned_release():
    # SERBITO-385: no downloaded script piped to a shell; the tarball is checked against a
    # pinned sha256 before it is installed.
    for step in STEPS:
        assert not re.search(r"\|\s*(sudo\s+)?(ba)?sh\b", step.get("run", "")), step["name"]
    trivy = STEPS[TRIVY]
    assert len(trivy["env"]["TRIVY_SHA256"]) == 64
    run = trivy["run"]
    assert run.index("sha256sum -c") < run.index("sudo install")


# --- SERBITO-389: a tag without its CHANGELOG.md section stops before the build ---------------

GUARD = _index(lambda s: "CHANGELOG.md" in s.get("run", ""))


@pytest.mark.parametrize(
    "tag, ok",
    [("v0.3.0", True), ("v0.4.0", False), ("v0x3x0", False), ("v0.3", False)],
)
def test_deploy_refuses_a_tag_without_its_changelog_section(tmp_path, tag, ok):
    # Right after checkout and the tag pick (SERBITO-401): it checks the tag that deploys.
    assert GUARD == 2 and GUARD < _index(lambda s: s.get("name") == "Build & push image")
    (tmp_path / "CHANGELOG.md").write_text(
        "## [Unreleased]\n\n## [0.3.0] - 2026-10-03\n\n### Fixed\n- X\n  - SR: X\n"
    )
    r = subprocess.run(
        ["bash", "-e", "-c", STEPS[GUARD]["run"]],
        cwd=tmp_path,
        env={"RELEASE_TAG": tag, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    if not ok:
        assert "::error" in r.stdout and tag in r.stdout


# --- SERBITO-401: weekly refresh of the newest release tag ---------------------------------

ON = WORKFLOW[True]  # PyYAML reads the bare key `on` as True
PICK = _index(lambda s: s.get("id") == "release")
PREV = _index(lambda s: s.get("id") == "prev")
SMOKE = _index(lambda s: "Smoke check" in s.get("name", ""))


def test_weekly_on_wednesday_and_by_hand():
    assert ON["push"]["tags"] == ["v*.*.*"]
    # Wednesday 03:00 UTC: Cloud SQL maintenance is Tuesday 02:00 UTC.
    assert ON["schedule"] == [{"cron": "0 3 * * 3"}]
    assert "workflow_dispatch" in ON


def test_a_refresh_never_overlaps_a_release_deploy():
    assert WORKFLOW["concurrency"] == {"group": "deploy-production", "cancel-in-progress": False}


def test_verify_gates_a_tag_and_a_refresh_skips_it():
    # The refreshed tag passed verify at release; main HEAD (what verify would test) never ships.
    jobs = WORKFLOW["jobs"]
    assert jobs["verify"]["if"] == "github.event_name == 'push'"
    cond = jobs["deploy"]["if"]
    assert jobs["deploy"]["needs"] == "verify" and "!cancelled()" in cond
    assert "needs.verify.result == 'success'" in cond
    assert "needs.verify.result == 'skipped' && github.event_name != 'push'" in cond


def test_later_steps_use_the_picked_tag_not_the_trigger_ref():
    assert PICK == 1, "the tag pick runs right after checkout"
    text = (ROOT / ".github" / "workflows" / "deploy.yaml").read_text("utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    # On a schedule run both point at main, not at the deployed tag.
    assert "github.sha" not in code and "GITHUB_SHA" not in code
    assert code.count("GITHUB_REF_NAME") == 1  # only the tag pick, for a tag push


def _run(i, cwd, tmp_path, **env):
    out, genv = tmp_path / "out", tmp_path / "env"
    out.write_text("")
    genv.write_text("")
    script = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", r"${\1}", STEPS[i]["run"])
    r = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=_clean_env(
            GITHUB_OUTPUT=str(out), GITHUB_ENV=str(genv), GITHUB_STEP_SUMMARY=os.devnull, **env
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return r, dict(line.split("=", 1) for f in (out, genv) for line in f.read_text().splitlines())


def test_a_tag_push_deploys_its_own_commit(repo, tmp_path):
    commit, git, _ = repo
    sha = commit("deliveries/views.py", "release")
    git("tag", "v0.2.0")
    r, out = _run(
        PICK,
        tmp_path / "repo",
        tmp_path,
        GITHUB_EVENT_NAME="push",
        GITHUB_REF_NAME="v0.2.0",
        AR_IMAGE=ENV["AR_IMAGE"],
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out["mode"], out["RELEASE_TAG"]) == ("release", "v0.2.0")
    assert out["IMAGE"] == image(sha)


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_a_refresh_rebuilds_the_newest_release_tag(repo, tmp_path, event):
    commit, git, _ = repo
    commit("deliveries/views.py", "old")
    git("tag", "v0.9.0")
    newest = commit("deliveries/views.py", "newest release")
    git("tag", "v0.10.0")  # version order, not text order
    commit("deliveries/views.py", "candidate")
    git("tag", "v0.11.0-rc1")  # not a vX.Y.Z release tag
    commit("deliveries/views.py", "work on main")
    r, out = _run(
        PICK, tmp_path / "repo", tmp_path, GITHUB_EVENT_NAME=event, AR_IMAGE=ENV["AR_IMAGE"]
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert git("rev-parse", "HEAD") == newest, "the tag must be checked out"
    day = datetime.now(UTC).strftime("%Y%m%d")
    assert (out["mode"], out["RELEASE_TAG"]) == ("refresh", "v0.10.0")
    assert out["IMAGE"] == image(f"{newest}-r{day}")


def test_a_refresh_without_a_release_tag_fails(repo, tmp_path):
    commit, _, _ = repo
    commit("deliveries/views.py", "never released")
    r, _ = _run(
        PICK, tmp_path / "repo", tmp_path, GITHUB_EVENT_NAME="schedule", AR_IMAGE=ENV["AR_IMAGE"]
    )
    assert r.returncode != 0 and "::error::No vX.Y.Z tag" in r.stdout


def test_detect_reads_the_commit_from_a_refreshed_image_tag(repo):
    commit, _, detect = repo
    live = commit("deliveries/migrations/0001_initial.py", "live release")
    commit("deliveries/views.py", "code only")
    assert detect(live_image=image(f"{live}-r20261007")) == "changed=false"


FAKE_GCLOUD_TRAFFIC = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$*" in
  "run services describe"*"--format=json"*) [ -n "$FAKE_JSON" ] && echo "$FAKE_JSON" ;;
  "run services describe"*"status.url"*) echo "https://javi-x.a.run.app" ;;
  "run services update-traffic"*) exit 0 ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def fakes(tmp_path):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for name, body in {
        "gcloud": FAKE_GCLOUD_TRAFFIC,
        "curl": '#!/bin/sh\nprintf "%s" "$FAKE_CODE"\n',
        "sleep": "#!/bin/sh\nexit 0\n",
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    jq = shutil.which("jq")
    path = os.pathsep.join(
        [str(bin_dir), "/usr/bin", "/bin", *([os.path.dirname(jq)] if jq else [])]
    )
    log = tmp_path / "gcloud.log"
    log.write_text("")
    return {"PATH": path, "FAKE_LOG": str(log), "SERVICE": "javi", "REGION": "europe-west1"}, log


def test_serving_revision_is_read_before_the_deploy(tmp_path, fakes):
    assert MIGRATE < PREV < DEPLOY < SMOKE
    env, _ = fakes
    traffic = {
        "status": {
            "traffic": [{"latestRevision": True, "percent": 100, "revisionName": "javi-00067"}]
        }
    }
    r, out = _run(PREV, tmp_path, tmp_path, FAKE_JSON=json.dumps(traffic), **env)
    assert r.returncode == 0 and out["revision"] == "javi-00067", r.stdout + r.stderr
    r, out = _run(PREV, tmp_path, tmp_path, FAKE_JSON="", **env)
    assert r.returncode == 0 and out["revision"] == "", r.stdout + r.stderr


def test_the_deploy_takes_traffic_back_after_a_rollback():
    # A rollback pins traffic to the old revision by name; the next deploy unpins it.
    assert '--region "$REGION" --to-latest' in STEPS[DEPLOY]["run"]


def test_smoke_runs_after_every_deploy():
    smoke = STEPS[SMOKE]
    assert "if" not in smoke and not smoke.get("continue-on-error")
    assert smoke["env"]["PREV_REVISION"] == "${{ steps.prev.outputs.revision }}"


@pytest.mark.parametrize(
    "code, prev, ok, rollback",
    [
        ("200", "javi-00067", True, False),
        ("500", "javi-00067", False, True),
        ("000", "", False, False),
    ],
)
def test_smoke_rolls_back_to_the_previous_revision(tmp_path, fakes, code, prev, ok, rollback):
    env, log = fakes
    r, _ = _run(SMOKE, tmp_path, tmp_path, FAKE_CODE=code, PREV_REVISION=prev, **env)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    assert ("--to-revisions javi-00067=100" in log.read_text()) == rollback, log.read_text()
    if not ok:
        assert "::error::" in r.stdout


# --- SERBITO-348: security headers check after the deploy -----------------------------------

HEADERS_SCRIPT = ROOT / "scripts" / "check_security_headers.sh"
HEADERS = _index(lambda s: s.get("name") == "Security headers check")
GOOD_HEADERS = (
    "HTTP/2 200\r\n"
    "Strict-Transport-Security: max-age=31536000; includeSubDomains\r\n"
    "X-Content-Type-Options: nosniff\r\n"
    "X-Frame-Options: DENY\r\n"
    "Referrer-Policy: same-origin\r\n"
    "Content-Security-Policy: frame-ancestors 'none'\r\n"
    "\r\n"
)


@pytest.fixture
def fake_headers(tmp_path):
    """A curl stub that prints $FAKE_HEADERS as the response headers (no network)."""
    bin_dir = tmp_path / "hdrbin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text('#!/bin/sh\nprintf "%b" "$FAKE_HEADERS"\n')
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "gcloud").write_text('#!/bin/sh\necho "https://javi-x.a.run.app"\n')
    (bin_dir / "gcloud").chmod(0o755)
    return os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])


def _check(path_env, headers):
    return subprocess.run(
        ["bash", str(HEADERS_SCRIPT), "https://javi-x.a.run.app/"],
        env=_clean_env(PATH=path_env, FAKE_HEADERS=headers.replace("\r\n", "\\r\\n")),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_header_check_passes_on_a_complete_set(fake_headers):
    r = _check(fake_headers, GOOD_HEADERS)
    assert r.returncode == 0, r.stdout + r.stderr


def test_header_check_accepts_frame_ancestors_and_report_only_csp(fake_headers):
    headers = GOOD_HEADERS.replace("X-Frame-Options: DENY\r\n", "").replace(
        "Content-Security-Policy: frame-ancestors 'none'",
        "content-security-policy: object-src 'none'; frame-ancestors 'none'",
    )
    assert _check(fake_headers, headers).returncode == 0
    report_only = GOOD_HEADERS.replace(
        "Content-Security-Policy: frame-ancestors 'none'",
        "Content-Security-Policy-Report-Only: default-src 'self'",
    )
    assert _check(fake_headers, report_only).returncode == 0  # X-Frame-Options covers framing


@pytest.mark.parametrize(
    "drop, reported",
    [
        ("Strict-Transport-Security: max-age=31536000; includeSubDomains\r\n", "Strict-Transport"),
        ("X-Content-Type-Options: nosniff\r\n", "X-Content-Type-Options"),
        ("Referrer-Policy: same-origin\r\n", "Referrer-Policy"),
    ],
)
def test_header_check_names_each_missing_header(fake_headers, drop, reported):
    r = _check(fake_headers, GOOD_HEADERS.replace(drop, ""))
    assert r.returncode == 1 and reported in r.stdout, r.stdout


def test_header_check_needs_a_framing_ban_and_a_csp(fake_headers):
    # The live landing before SERBITO-348: HSTS, nosniff, Referrer-Policy only.
    headers = GOOD_HEADERS.replace("X-Frame-Options: DENY\r\n", "").replace(
        "Content-Security-Policy: frame-ancestors 'none'\r\n", ""
    )
    r = _check(fake_headers, headers)
    assert r.returncode == 1
    assert "X-Frame-Options or CSP frame-ancestors" in r.stdout
    assert "Content-Security-Policy or" in r.stdout
    # Report-only frame-ancestors is ignored by browsers, so it does not count.
    ro = headers.replace(
        "\r\n\r\n", "\r\nContent-Security-Policy-Report-Only: frame-ancestors 'none'\r\n\r\n"
    )
    r = _check(fake_headers, ro)
    assert r.returncode == 1 and "X-Frame-Options or CSP frame-ancestors" in r.stdout


def test_header_check_prints_names_not_values(fake_headers):
    r = _check(
        fake_headers,
        GOOD_HEADERS.replace("X-Frame-Options: DENY\r\n", "").replace(
            "Content-Security-Policy: frame-ancestors 'none'",
            "Content-Security-Policy: secret-value-x",
        ),
    )
    assert r.returncode == 1 and "secret-value-x" not in r.stdout + r.stderr


def test_header_check_fails_when_the_request_fails(tmp_path):
    bin_dir = tmp_path / "failbin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text("#!/bin/sh\nexit 28\n")
    (bin_dir / "curl").chmod(0o755)
    r = _check(os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]), "")
    assert r.returncode == 1


def test_header_step_runs_last_on_every_deploy_without_rollback():
    step = STEPS[HEADERS]
    assert HEADERS == len(STEPS) - 1 and SMOKE < HEADERS
    assert "if" not in step and not step.get("continue-on-error")
    assert "update-traffic" not in step["run"]
    assert '"$SVC_URL/"' in step["run"]


def test_header_step_fails_the_run_on_missing_headers(tmp_path, fake_headers):
    env = dict(PATH=fake_headers, SERVICE="javi", REGION="europe-west1", RELEASE_TAG="v0.70.0")
    bad = GOOD_HEADERS.replace("Referrer-Policy: same-origin\r\n", "")
    r, _ = _run(HEADERS, ROOT, tmp_path, FAKE_HEADERS=bad.replace("\r\n", "\\r\\n"), **env)
    assert r.returncode == 1 and "::error::" in r.stdout, r.stdout + r.stderr
    good = GOOD_HEADERS.replace("\r\n", "\\r\\n")
    r, _ = _run(HEADERS, ROOT, tmp_path, FAKE_HEADERS=good, **env)
    assert r.returncode == 0, r.stdout + r.stderr


def test_header_step_skips_a_refreshed_tag_without_the_script(tmp_path, fake_headers):
    # A weekly refresh checks out the newest tag; tags before SERBITO-348 have no script.
    env = dict(PATH=fake_headers, SERVICE="javi", REGION="europe-west1", RELEASE_TAG="v0.64.0")
    r, _ = _run(HEADERS, tmp_path, tmp_path, FAKE_HEADERS="", **env)
    assert r.returncode == 0 and "::notice::" in r.stdout, r.stdout + r.stderr
