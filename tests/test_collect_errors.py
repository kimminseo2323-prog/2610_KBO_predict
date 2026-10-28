import json

from scripts.collect_errors import summarize


def test_summarize_empty_when_no_errors(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"collect_errors": [], "generated_at": "x"}), encoding="utf-8")
    assert summarize(p) == ""


def test_summarize_lists_errors_and_run_url(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(
        json.dumps(
            {
                "collect_errors": ["/games/1: boom", "/games/2: bad"],
                "generated_at": "2026-10-29T09:07:00+09:00",
                "run_url": "https://x/run/1",
            }
        ),
        encoding="utf-8",
    )
    body = summarize(p)
    assert "/games/1: boom" in body and "/games/2: bad" in body
    assert "https://x/run/1" in body and "2026-10-29" in body


def test_summarize_missing_file_is_empty(tmp_path):
    assert summarize(tmp_path / "nope.json") == ""
