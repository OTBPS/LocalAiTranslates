import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screen_translator.diagnostics import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?")
    parser.add_argument("--model-id", default="qwen3-8b-q5-k-m")
    parser.add_argument("--report", default="build/inference-report.json")
    args = parser.parse_args()
    main(args.root, args.report, args.model_id)
