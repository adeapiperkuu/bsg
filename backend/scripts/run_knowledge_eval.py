from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.knowledge.evaluation import run_static_golden_evaluation  # noqa: E402


def main() -> int:
    report = run_static_golden_evaluation()
    output_dir = ROOT / ".artifacts"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "knowledge_eval_latest.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(output_path), **report}, indent=2, sort_keys=True))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
