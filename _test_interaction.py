#!/usr/bin/env python3
"""
Smoke tests for next-generation interaction behavior.

These checks focus on the local competition implementation:
- multi-speaker dialogue can be parsed from plain goal text
- generic food sequence does not collapse to hotpot
- profile feedback is applied as a hard avoid constraint
- status reads do not create empty sessions or profiles
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_service import run_agent
from interaction_intelligence import interaction_manager, PROFILE_PATH


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def cleanup(user_id, session_id):
    interaction_manager.clear_profile(user_id)
    interaction_manager.clear_session(session_id)
    if os.path.exists(PROFILE_PATH):
        try:
            os.remove(PROFILE_PATH)
        except OSError:
            pass


def main():
    user_id = "interaction-smoke-user"
    session_id = "interaction-smoke-session"
    cleanup(user_id, session_id)

    assert_true(interaction_manager.session_status(session_id) == {}, "session read should be non-creating")
    assert_true(interaction_manager.profile_status(user_id) == {}, "profile read should be non-creating")

    plan = run_agent({
        "session_id": session_id,
        "user_id": user_id,
        "goal": "小明：春熙路附近吃川菜\n小红：吃完想逛街\n小明：不要太贵",
    }, request_id="interaction-smoke-plan")
    assert_true(plan.get("ok"), plan.get("error"))
    constraints = plan["result"]["constraints"]
    interaction = plan.get("interaction") or {}
    assert_true(constraints["intent_type"] == "simple_route", "dialogue sequence should force simple_route")
    assert_true("中餐" in constraints.get("sequence", []), "generic eating sequence should inherit mentioned food type")
    assert_true("商场" in constraints.get("sequence", []), "shopping activity should become mall sequence")
    assert_true(interaction.get("dialogue_state"), "dialogue state should be exposed")

    feedback = interaction_manager.apply_feedback({
        "user_id": user_id,
        "feedback": {"avoid_tags": ["KTV"], "preferred_tags": ["茶馆"], "dietary": ["不吃辣"]},
    })
    assert_true(feedback is True, "valid feedback should be accepted")

    avoid_plan = run_agent({
        "session_id": session_id,
        "user_id": user_id,
        "goal": "春熙路附近找个KTV",
    }, request_id="interaction-smoke-avoid")
    assert_true(avoid_plan.get("ok"), avoid_plan.get("error"))
    recs = avoid_plan["result"]["variants"][0].get("recommendations", [])
    assert_true(not any(r.get("type") == "KTV" for r in recs), "profile avoid_tags should hard-filter KTV")

    assert_true(interaction_manager.clear_profile(user_id) is True, "profile should be clearable")
    assert_true(interaction_manager.profile_status(user_id) == {}, "cleared profile should stay empty")
    cleanup(user_id, session_id)
    print("interaction smoke ok")


if __name__ == "__main__":
    main()

