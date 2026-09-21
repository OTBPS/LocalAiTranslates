import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screen_translator.core import CancellationToken
from screen_translator.models import DEFAULT_MODEL_ID, DEFAULT_SHARED_MODEL_ROOT, install_models

if __name__ == "__main__":
    previous = [None]

    def report(name, current, total):
        key = name, int(current / total * 20)
        if key != previous[0]:
            print(f"{name}: {current / total:.0%}", flush=True)
            previous[0] = key

    install_models(
        Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SHARED_MODEL_ROOT,
        CancellationToken(),
        report,
        sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL_ID,
    )
