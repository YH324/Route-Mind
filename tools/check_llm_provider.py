#!/usr/bin/env python3
"""
Check whether the configured external LLM provider is reachable.

This script does not print API keys. It exercises the same intent-classification
path used by the planner and reports whether an external provider was used.
"""
import json

from route_planner_v3 import _INTENT_LLM_UNAVAILABLE_UNTIL, classify_intent_with_llm


def main():
    _INTENT_LLM_UNAVAILABLE_UNTIL.clear()
    result = classify_intent_with_llm("春熙路附近想吃火锅")
    print(json.dumps({
        "intent_type": result.get("intent_type"),
        "llm_used": bool(result.get("llm_used")),
        "provider": result.get("provider"),
        "raw_intent_type": result.get("raw_intent_type"),
        "guardrail": result.get("guardrail"),
        "error": result.get("llm_error"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
