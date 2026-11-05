"""Activate R01–R14 through logged commands in a new replay-verified save copy."""

import argparse
from pathlib import Path

from training.enable_attempts_copy import activate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    activate(a.input, a.output, owner_rules=True)
    print("Создана проверенная копия с R01–R14. Исходный файл сохранён без изменений.")


if __name__ == "__main__":
    main()
