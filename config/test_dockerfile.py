"""Стражи dockerfile: то, без чего деплой падает на Trivy или теряет сигналы остановки."""

from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parent.parent / "dockerfile").read_text(encoding="utf-8")


def test_strips_pip_vendored_sbom():
    # SBOM системного pip декларирует setuptools/msgpack, которых нет в окружении,
    # а Trivy-гейт видит в них HIGH CVE (serbito docs/101, javi v0.51.0)
    assert "bom.cdx.json" in DOCKERFILE and "vendor.txt" in DOCKERFILE
    assert "-path '*/pip/_vendor/*' -delete" in DOCKERFILE


def test_cmd_is_exec_form_and_execs_gunicorn():
    cmd = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD"))
    assert cmd.startswith('CMD ["')
    assert "exec gunicorn" in cmd
