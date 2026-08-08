import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(BASE, "arc", "training.json")


def encode_grid(grid: List[List[int]]) -> str:
    return "\n".join("".join(str(c) for c in row) for row in grid)


def parse_grid(text: str) -> List[List[int]]:
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list) and all(isinstance(r, list) for r in data):
                return [[int(c) for c in r] for r in data]
            if isinstance(data, list) and all(isinstance(c, int) for c in data):
                return [data]
        except Exception:
            pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line or " " in line:
            try:
                row = [int(x) for x in line.replace(",", " ").split() if x.strip()]
            except ValueError:
                row = [int(ch) for ch in line if ch.isdigit()]
        else:
            row = [int(ch) for ch in line if ch.isdigit()]
        if row:
            rows.append(row)
    return rows


def build_prompt(puzzle: dict) -> str:
    lines = [
        "Solve the ARC reasoning task. Each cell is a color digit 0-9.",
        "Study the input/output examples, infer the transformation rule.",
    ]
    for i, ex in enumerate(puzzle.get("train", [])):
        lines.append(f"Example {i + 1} input:")
        lines.append(encode_grid(ex.get("input", [])))
        lines.append(f"Example {i + 1} output:")
        lines.append(encode_grid(ex.get("output", [])))
    test = (puzzle.get("test") or [{}])[0]
    lines.append("Now produce only the output grid for this input:")
    lines.append(encode_grid(test.get("input", [])))
    lines.append("Output grid:")
    return "\n".join(lines)


def _matches(pred_text: str, target: List[List[int]], exact: bool) -> bool:
    pred = parse_grid(pred_text)
    if pred == target:
        return True
    if exact or not pred or not target:
        return False
    return (len(pred) <= len(target)
            and all(len(r) == len(target[0]) for r in pred)
            and all(p == t for p, t in zip(pred, target)))


def run_arc_eval(model_manager=None, model_name: Optional[str] = None, limit: Optional[int] = None,
                 dataset_path: str = DEFAULT_DATASET, exact: bool = False) -> dict:
    if not os.path.exists(dataset_path):
        return {"dataset": False, "correct": 0, "total": 0, "accuracy": 0.0,
                "note": f"dataset not found at {dataset_path}"}
    try:
        with open(dataset_path, encoding="utf-8") as fh:
            puzzles = json.load(fh)
    except Exception as e:
        return {"dataset": False, "correct": 0, "total": 0, "accuracy": 0.0, "note": str(e)}
    if isinstance(puzzles, dict):
        puzzles = list(puzzles.values())
    if limit is not None:
        puzzles = puzzles[:limit]
    if model_manager is None:
        from models import ModelManager
        model_manager = ModelManager()
    name = (model_name or next(iter(getattr(model_manager, "configs", None) or {}), None)
            or "default")
    correct = 0
    for p in puzzles:
        try:
            text = model_manager.generate(name, build_prompt(p), max_tokens=512, temperature=0.0)
            target = (p.get("test") or [{"output": []}])[0].get("output", [])
            if _matches(text, target, exact):
                correct += 1
        except Exception as e:
            logger.warning(f"ARC puzzle failed: {e}")
    total = len(puzzles)
    return {"dataset": True, "correct": correct, "total": total,
            "accuracy": round(correct / total, 4) if total else 0.0, "model": name}
