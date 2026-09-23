"""The client edition must stay thin and must not collide with the full one."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMON = (ROOT / "installer.common.iss").read_text(encoding="utf-8")
CLIENT = (ROOT / "installer.client.iss").read_text(encoding="utf-8")
INSTALLER = (ROOT / "installer.iss").read_text(encoding="utf-8")
SPEC = (ROOT / "ScreenTranslatorClient.spec").read_text(encoding="utf-8")
BUILD = (ROOT / "scripts" / "build_client.ps1").read_text(encoding="utf-8")


def test_the_client_installer_reuses_the_shared_script_instead_of_copying_it():
    assert '#include "installer.iss"' in CLIENT
    assert "#define ClientEdition" in CLIENT
    # Everything that governs installation behaviour lives in the shared
    # script, so a fix cannot be applied to one edition and forgotten in the
    # other.
    for section in ("[Setup]", "[Files]", "[Icons]", "[Code]"):
        assert section not in CLIENT


def test_the_two_editions_have_distinct_identities():
    app_ids = set(re.findall(r'#define \w*AppId "(\{\{[0-9A-F-]+\})"', COMMON))
    assert len(app_ids) == 2, "each edition needs its own AppId or upgrades collide"
    assert 'ScreenTranslator.Client' in COMMON
    assert 'ScreenTranslatorClient' in COMMON


def test_the_client_installer_refuses_to_sit_beside_the_full_edition():
    # Both editions share the per-user configuration and single-instance
    # lock, so installing both would leave two entries fighting over them.
    assert "#ifdef ClientEdition" in INSTALLER
    assert "FullUninstallKey" in INSTALLER
    assert "已安装完整版屏译" in INSTALLER


def test_downgrade_protection_and_uninstall_cleanup_apply_to_both_editions():
    assert "CompareSemanticVersions(InstalledVersion, '{#AppVersion}') > 0" in INSTALLER
    assert "ShouldPurgeUserData" in INSTALLER
    # These live in the shared script, so the client inherits them verbatim.
    assert INSTALLER.count("function InitializeSetup") == 1


def test_the_payload_directory_and_output_name_are_edition_specific():
    assert "{#PayloadDir}" in INSTALLER
    assert "{#OutputBaseName}" in INSTALLER
    assert "{#InstallDirName}" in INSTALLER
    assert r"dist\ScreenTranslatorClient" in COMMON
    assert r"dist\ScreenTranslator" in COMMON


@pytest.mark.parametrize("runtime", ["paddle", "paddleocr", "paddlex", "nvidia"])
def test_the_client_spec_excludes_every_model_runtime(runtime):
    excludes = SPEC.split("EXCLUDED_RUNTIMES = [", 1)[1].split("]", 1)[0]
    assert f"'{runtime}'" in excludes


def test_the_client_spec_ships_no_llama_runtime():
    assert "runtime/llama" not in SPEC
    assert "llama" not in SPEC.split('"""', 2)[2]


def test_the_client_spec_keeps_what_the_capturing_device_needs():
    # Qt draws the overlay, OpenCV and NumPy composite and inpaint, requests
    # carries the tailnet transport.
    for package in ("PySide6", "opencv-contrib-python", "requests", "numpy"):
        assert package in SPEC


def test_the_client_build_enforces_the_size_and_content_it_promises():
    # A floor, not an exact number: raising it is progress and must not
    # mean editing a test that has nothing to do with coverage.
    floor = re.search(r"--cov-fail-under=(\d+)", BUILD)
    assert floor and int(floor.group(1)) >= 55
    assert "ruff check" in BUILD
    assert "release_manifest.py" in BUILD
    assert "--edition client" in BUILD
    assert "payloadMB -gt 400" in BUILD
    assert "llama-server.exe" in BUILD


def test_the_client_build_does_not_require_a_gpu_preflight():
    # The full build asserts a working Paddle CUDA runtime. Requiring that
    # here would make the edition unbuildable on the machine it targets.
    assert "is_compiled_with_cuda" not in BUILD
