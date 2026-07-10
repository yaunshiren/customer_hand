from __future__ import annotations

from collections import Counter

from scripts.run_agent_eval import DEFAULT_DATASET, load_eval_cases


def test_customer_service_eval_dataset_has_required_coverage() -> None:
    cases = load_eval_cases(DEFAULT_DATASET)

    assert len(cases) == 24
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.user_input for case in cases)
    assert all(case.expected_route for case in cases)
    assert all(isinstance(case.expected_args, dict) for case in cases)
    assert all(isinstance(case.expected_rag_keywords, list) for case in cases)

    routes = Counter(case.expected_route for case in cases)
    assert routes["rag"] >= 8
    assert routes["tool"] >= 4
    assert routes["ticket"] >= 2
    assert routes["chitchat"] >= 2
    assert sum(case.metadata.writes_state for case in cases) >= 2
    assert sum(bool(case.metadata.setup_turns) for case in cases) >= 2
    assert sum(case.expected_safety_behavior != "allow" for case in cases) >= 3


def test_writes_state_cases_declare_tool_and_non_chat_scenario() -> None:
    cases = load_eval_cases(DEFAULT_DATASET)

    for case in cases:
        if not case.metadata.writes_state:
            continue
        assert case.expected_tool
        assert case.metadata.scenario != "chat"

