"""Стражи dockerfile: то, без чего деплой падает на Trivy или теряет сигналы остановки."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
WORKFLOWS = ROOT / ".github" / "workflows"
UV_STAGE = re.compile(
    r"^FROM ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64} AS uv$", re.M
)


def test_strips_pip_vendored_sbom():
    # SBOM системного pip декларирует setuptools/msgpack, которых нет в окружении,
    # а Trivy-гейт видит в них HIGH CVE (serbito docs/101, javi v0.51.0)
    assert "bom.cdx.json" in DOCKERFILE and "vendor.txt" in DOCKERFILE
    assert "-path '*/pip/_vendor/*' -delete" in DOCKERFILE


CMD = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD"))


def test_cmd_is_exec_form_and_execs_gunicorn():
    assert CMD.startswith('CMD ["')
    assert "exec gunicorn" in CMD


def test_container_start_does_not_migrate():
    # Миграции гоняет деплой (Cloud Run job до переключения трафика), не каждый холодный
    # старт (SERBITO-323). Никакого entrypoint-скрипта, который мог бы вернуть их на старт.
    assert "migrate" not in CMD
    assert not re.search(r"^ENTRYPOINT", DOCKERFILE, re.M)
    assert "--preload" in CMD  # Django импортируется один раз, а не в каждом воркере


def test_bytecode_is_compiled_at_build_time():
    # Без .pyc каждый старт процесса компилировал stdlib, зависимости и код из исходников:
    # python:*-slim удаляет .pyc stdlib, uv по умолчанию их не создаёт (SERBITO-323).
    assert re.search(r"^RUN python -m compileall .*sysconfig.*stdlib", DOCKERFILE, re.M)
    assert re.search(r"^RUN uv sync --frozen --no-dev --compile-bytecode$", DOCKERFILE, re.M)
    lines = DOCKERFILE.splitlines()
    copy_app = lines.index("COPY . .")
    assert re.match(r"RUN python -m compileall .* /app$", lines[copy_app + 1])


def test_uv_image_pinned_by_version_and_digest():
    # Мутабельный uv:latest менял сборку без коммита (SERBITO-289). Отдельная FROM-стадия,
    # а не COPY --from=<образ>: Dependabot (docker) обновляет только строки FROM.
    assert UV_STAGE.search(DOCKERFILE)
    assert "COPY --from=uv /uv " in DOCKERFILE
    assert ":latest" not in DOCKERFILE


def test_python_base_pinned_by_digest_and_matches_ci_python():
    # Мутабельный python:3.14-slim менял прод без коммита (SERBITO-294): тег + digest
    # multi-arch индекса. Минор совпадает с .python-version — им CI (setup-uv) гоняет тесты.
    match = re.search(r"^FROM python:(\d+\.\d+)-slim@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M)
    assert match
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == match.group(1)


def test_ci_uv_version_comes_from_dockerfile(tmp_path):
    # Один источник версии uv — стадия uv в Dockerfile (её бампает Dependabot). CI читает её
    # шагом uv-version; прогоняем этот шаг как есть и сверяем результат (SERBITO-294).
    ci = (WORKFLOWS / "ci.yaml").read_text(encoding="utf-8")
    step = re.search(r"id: uv-version\n +run: \|\n((?: {10}.*\n)+)", ci)
    assert step, "ci.yaml: step 'uv-version' not found"
    script = "\n".join(line.strip() for line in step.group(1).splitlines())
    output = tmp_path / "github_output"
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=ROOT,
        env={"GITHUB_OUTPUT": str(output), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert output.read_text().strip() == f"version={UV_STAGE.search(DOCKERFILE).group(1)}"

    # Every setup-uv in every workflow takes that output — no hardcoded version to drift.
    for workflow in WORKFLOWS.glob("*.y*ml"):
        text = workflow.read_text(encoding="utf-8")
        for block in re.findall(r"uses: astral-sh/setup-uv@.*\n((?: {8,}.*\n)*)", text):
            assert "version: ${{ steps.uv-version.outputs.version }}" in block, workflow.name
            assert "version-file" not in block, workflow.name
