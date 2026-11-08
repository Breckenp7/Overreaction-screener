"""Loads config.yaml."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    total = sum(cfg["scoring"]["weights"].values())
    if abs(total - 100) > 1e-6:
        raise ValueError(f"Scoring weights in config.yaml add up to {total}, but must add up to 100.")
    return cfg
