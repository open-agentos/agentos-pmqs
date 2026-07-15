"""Test fixtures. Force LLM off so unit tests are deterministic and offline.

The real LLM path is exercised separately (test_llm.py, guarded to skip if no
provider is configured, and by manual end-to-end verification).
"""
import os

os.environ.setdefault("PMQS_LLM_MODE", "off")
