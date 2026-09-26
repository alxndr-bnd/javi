"""Стражи dockerfile: то, без чего деплой падает на Trivy или теряет сигналы остановки."""

import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")


def test_strips_pip_vendored_sbom():
    # SBOM системного pip декларирует setuptools/msgpack, которых нет в окружении,
    # а Trivy-гейт видит в них HIGH CVE (serbito docs/101, javi v0.51.0)
    assert "bom.cdx.json" in DOCKERFILE and "vendor.txt" in DOCKERFILE
    assert "-path '*/pip/_vendor/*' -delete" in DOCKERFILE


def test_cmd_is_exec_form_and_execs_gunicorn():
    cmd = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD"))
    assert cmd.startswith('CMD ["')
    assert "exec gunicorn" in cmd


def test_uv_image_pinned_by_version_and_digest():
    # Мутабельный uv:latest менял сборку без коммита (SERBITO-289). Отдельная FROM-стадия,
    # а не COPY --from=<образ>: Dependabot (docker) обновляет только строки FROM.
    assert re.search(
        r"^FROM ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+@sha256:[0-9a-f]{64} AS uv$", DOCKERFILE, re.M
    )
    assert "COPY --from=uv /uv " in DOCKERFILE
    assert ":latest" not in DOCKERFILE
