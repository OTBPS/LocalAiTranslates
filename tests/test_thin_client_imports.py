"""The client edition must import the whole application without model runtimes.

``ScreenTranslatorClient.spec`` excludes PaddleOCR, PaddlePaddle and the CUDA
libraries. That only works if every reference to them is lazy. A subprocess
with those imports blocked is the honest way to check it, because an eager
import anywhere in the chain would be invisible in this test session, where
the packages are installed.
"""

import os
import subprocess
import sys
import textwrap

# The subprocesses print Chinese diagnostics; the Windows console default
# would decode them as GBK and fail.
UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

BLOCKER = """
import sys

BLOCKED = ("paddle", "paddleocr", "paddlex", "paddle2onnx", "nvidia")


class Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ImportError(f"{name} is not part of the client edition")
        return None


sys.meta_path.insert(0, Blocker())
"""


def run_without_runtimes(body: str) -> subprocess.CompletedProcess:
    script = BLOCKER + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=UTF8_ENV,
        timeout=180,
    )


def test_the_blocker_actually_blocks():
    result = run_without_runtimes(
        """
        try:
            import paddleocr
        except ImportError:
            print("BLOCKED")
        else:
            print("LEAKED")
        """
    )

    assert "BLOCKED" in result.stdout, result.stderr


def test_the_application_imports_without_paddle_or_cuda():
    result = run_without_runtimes(
        """
        import os

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        import screen_translator.app
        import screen_translator.backend
        import screen_translator.controller
        import screen_translator.remote.client
        import screen_translator.remote.service
        import screen_translator.settings
        print("IMPORTED")
        """
    )

    assert "IMPORTED" in result.stdout, result.stderr


def test_a_remote_backend_works_without_any_local_runtime():
    result = run_without_runtimes(
        """
        from screen_translator.backend import create_backend
        from screen_translator.capabilities import ocr_runtime_available
        from screen_translator.core import Config

        assert ocr_runtime_available() is False
        backend = create_backend(
            Config(
                mode="remote",
                remote_url="http://100.101.102.103:8765",
                remote_token="s" * 32,
            )
        )
        assert backend.kind == "remote"
        backend.stop()
        print("REMOTE OK")
        """
    )

    assert "REMOTE OK" in result.stdout, result.stderr


def test_a_local_backend_reports_the_missing_runtime_instead_of_crashing():
    result = run_without_runtimes(
        """
        from screen_translator.backend import create_backend
        from screen_translator.core import Config

        backend = create_backend(Config())
        assert backend.ready() is False
        print(backend.describe())
        """
    )

    assert "PaddleOCR" in result.stdout, result.stderr
    assert "远程主机模式" in result.stdout


def test_the_domain_layer_imports_without_qt():
    # The host service and the wire format must not drag in the widget stack.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "import screen_translator.remote.protocol;"
            "import screen_translator.remote.access;"
            "import screen_translator.contracts;"
            "assert 'PySide6.QtWidgets' not in sys.modules;"
            "print('NO QT')",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=UTF8_ENV,
        timeout=120,
    )

    assert "NO QT" in result.stdout, result.stderr
