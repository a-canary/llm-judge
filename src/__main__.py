#!/usr/bin/env python3
"""
llm-judge CLI entry point — thin wrapper that adds scripts/ to sys.path
and invokes the main judge function.
"""
import sys
from pathlib import Path

# Add repo root so `scripts/` is importable
_reporoot = Path(__file__).parent.parent  # src/ -> repo root
sys.path.insert(0, str(_reporoot))

from scripts.run_judge import main

main()