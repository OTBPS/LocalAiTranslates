from scripts.training.evaluate_hf_model import select_records


def test_select_records_balances_languages_deterministically():
    rows = [
        {"id": f"{language}-{index}", "source_language": language}
        for language in ("en", "ja", "ko")
        for index in range(5)
    ]
    first = select_records(rows, per_language=2, seed=42)
    second = select_records(rows, per_language=2, seed=42)
    assert first == second
    assert [row["source_language"] for row in first].count("en") == 2
    assert [row["source_language"] for row in first].count("ja") == 2
    assert [row["source_language"] for row in first].count("ko") == 2


def test_select_records_keeps_all_when_limit_is_none():
    rows = [{"id": "a", "source_language": "en"}]
    assert select_records(rows, per_language=None, seed=1) is rows
