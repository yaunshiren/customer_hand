from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from scripts.run_agent_eval import load_eval_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "data" / "catalog" / "cleaning_products.yml"
TAXONOMY_PATH = PROJECT_ROOT / "data" / "taxonomy" / "cleaning_issue_types.yml"
EVAL_PATH = PROJECT_ROOT / "data" / "eval" / "cleaning_mvp_v1.jsonl"
KNOWLEDGE_ROOT = PROJECT_ROOT / "data" / "knowledge" / "bitselect"

SUPPORTED_MODELS = {"T7", "T7S Plus", "G10", "G10S Pro"}
PHASE_ONE_ISSUES = {
    "POWER_CHARGING_FAILURE",
    "CLEANING_INTERRUPTION_OR_STUCK",
    "CLEANING_PERFORMANCE_DROP",
    "MOPPING_OR_BASE_STATION_FAILURE",
    "ERROR_CODE_DIAGNOSIS",
}
PHASE_TWO_ISSUES = {
    "NETWORK_OR_MAP_FAILURE",
    "MAINTENANCE_AND_CONSUMABLE",
    "WARRANTY_AND_REPAIR",
}


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        value = yaml.safe_load(file)
    assert isinstance(value, dict)
    return value


def _knowledge_doc_ids() -> set[str]:
    doc_ids: set[str] = set()
    for path in KNOWLEDGE_ROOT.rglob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines()[:20]:
            if line.startswith("doc_id:"):
                doc_ids.add(line.split(":", 1)[1].strip())
                break
    return doc_ids


def _catalog_doc_ids(catalog: dict) -> set[str]:
    doc_ids: set[str] = set()
    for model in catalog["supported_models"]:
        knowledge = model["knowledge"]
        doc_ids.add(knowledge["product_detail_doc_id"])
        doc_ids.update(knowledge["manual_doc_ids"])
        doc_ids.update(knowledge["faq_doc_ids"])
        doc_ids.update(knowledge["error_code_doc_ids"])
    for model in catalog["excluded_models"]:
        doc_ids.update(model["evidence_doc_ids"])
    return doc_ids


def test_product_catalog_matches_approved_v1_scope_and_evidence() -> None:
    catalog = _load_yaml(CATALOG_PATH)
    models = {item["model_id"]: item for item in catalog["supported_models"]}

    assert set(models) == SUPPORTED_MODELS
    assert {item["model_id"] for item in catalog["excluded_models"]} == {"B205"}
    assert models["T7S Plus"]["support_level"] == "limited"
    assert all(
        item["support_level"] == "standard"
        for model_id, item in models.items()
        if model_id != "T7S Plus"
    )

    assert models["T7"]["capabilities"]["mop_auto_lift"] == "unsupported"
    assert models["T7S Plus"]["capabilities"]["auto_empty"] == "optional_dedicated_dock"
    assert models["G10"]["capabilities"]["auto_empty"] == "unsupported"
    assert models["G10"]["capabilities"]["mop_self_wash"] == "supported"
    assert models["G10S Pro"]["capabilities"]["auto_empty"] == "supported"
    assert models["G10S Pro"]["capabilities"]["hot_air_dry"] == "supported"

    known_doc_ids = _knowledge_doc_ids()
    assert _catalog_doc_ids(catalog) <= known_doc_ids
    for item in [*catalog["supported_models"], *catalog["excluded_models"]]:
        assert all((PROJECT_ROOT / path).is_file() for path in item["evidence_paths"])


def test_taxonomy_separates_supported_and_planned_issue_types() -> None:
    taxonomy = _load_yaml(TAXONOMY_PATH)
    phase_one = {
        item["id"]
        for item in taxonomy["issue_types"]
        if item["phase"] == 1 and item["status"] == "supported"
    }
    phase_two = {
        item["id"]
        for item in taxonomy["issue_types"]
        if item["phase"] == 2 and item["status"] == "planned_only"
    }

    assert phase_one == PHASE_ONE_ISSUES
    assert phase_two == PHASE_TWO_ISSUES
    assert taxonomy["model_missing_policy"] == {
        "resolution": "clarify_first",
        "allow_model_guess": False,
        "allow_model_specific_guidance": False,
        "safe_universal_checks_only": True,
        "clarification_sources": ["订单商品名", "机身铭牌", "APP 中显示的型号"],
    }

    known_doc_ids = _knowledge_doc_ids()
    for item in taxonomy["issue_types"]:
        assert set(item["knowledge_doc_ids"]) <= known_doc_ids


def test_cleaning_eval_is_current_evalcase_compatible_and_exactly_eight_cases() -> None:
    cases = load_eval_cases(EVAL_PATH, minimum_cases=8)

    assert len(cases) == 8
    assert len({case.case_id for case in cases}) == 8
    assert all(case.metadata.golden for case in cases)
    assert all(case.metadata.golden["dataset_version"] == "cleaning_mvp_v1" for case in cases)
    assert all(case.expected_tool is None for case in cases)
    assert all(case.expected_args == {} for case in cases)
    assert all(case.metadata.writes_state is False for case in cases)


def test_eval_covers_models_issue_types_and_required_special_cases() -> None:
    cases = load_eval_cases(EVAL_PATH, minimum_cases=8)
    golden_rows = [case.metadata.golden for case in cases]
    covered_models = {
        row["product_model"]
        for row in golden_rows
        if row["model_status"] == "resolved"
    }
    covered_issues = {row["issue_type"] for row in golden_rows}
    tags = Counter(tag for row in golden_rows for tag in row["case_tags"])

    assert covered_models == SUPPORTED_MODELS
    assert covered_issues == PHASE_ONE_ISSUES
    assert tags["model_missing"] == 1
    assert tags["cross_model_negative"] == 1
    assert tags["danger_symptom"] == 1
    assert tags["prompt_injection"] == 1
    assert all(row["product_model"] != "B205" for row in golden_rows)


def test_eval_knowledge_references_and_error_codes_are_repository_backed() -> None:
    cases = load_eval_cases(EVAL_PATH, minimum_cases=8)
    known_doc_ids = _knowledge_doc_ids()
    error_code_text = (
        KNOWLEDGE_ROOT / "04_faq" / "error_code" / "CODE_VAC_001.md"
    ).read_text(encoding="utf-8")

    for case in cases:
        golden = case.metadata.golden
        expected_docs = set(golden["expected_doc_ids"])
        forbidden_docs = set(golden["forbidden_doc_ids"])
        assert expected_docs <= known_doc_ids
        assert forbidden_docs <= known_doc_ids
        assert expected_docs.isdisjoint(forbidden_docs)
        assert all(code in error_code_text for code in golden["error_codes"])


def test_missing_model_cross_model_danger_and_injection_contracts() -> None:
    cases = load_eval_cases(EVAL_PATH, minimum_cases=8)

    missing = next(case for case in cases if "model_missing" in case.metadata.golden["case_tags"])
    assert missing.expected_route == "clarify"
    assert missing.expected_rag_keywords == []
    assert missing.metadata.golden["product_model"] is None
    assert missing.metadata.golden["expected_doc_ids"] == []
    assert missing.metadata.golden["safe_universal_checks_only"] is True

    cross_model = next(
        case for case in cases if "cross_model_negative" in case.metadata.golden["case_tags"]
    )
    assert cross_model.metadata.golden["product_model"] == "T7"
    assert set(cross_model.metadata.golden["forbidden_doc_ids"]) == {
        "PROD_VAC_002",
        "PROD_VAC_003",
        "PROD_VAC_004",
    }

    danger = next(case for case in cases if "danger_symptom" in case.metadata.golden["case_tags"])
    assert danger.metadata.golden["expected_handoff"] == "yes"
    assert danger.metadata.golden["halt_normal_troubleshooting"] is True
    assert "UNSAFE_ACTION" in danger.metadata.golden["target_badcase_types"]

    injection = next(
        case for case in cases if "prompt_injection" in case.metadata.golden["case_tags"]
    )
    assert injection.expected_safety_behavior == "flag_prompt_injection"
    assert "PROMPT_INJECTION_RISK" in injection.metadata.golden["target_badcase_types"]
    assert "忽略" in injection.user_input
