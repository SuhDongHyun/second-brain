from pathlib import Path

from app.modules.financial.infra.files import (
    markdown_path,
    raw_path,
    write_json_atomic,
    write_text_atomic,
)


def test_writers_are_deterministic_and_paths_are_stable(tmp_path: Path) -> None:
    json_path = raw_path(tmp_path, "005930", 2025, "20250318000984", "CFS")
    assert write_json_atomic(json_path, {"b": 2, "a": 1})
    assert json_path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
    assert not write_json_atomic(json_path, {"a": 1, "b": 2})

    md_path = markdown_path(tmp_path, "005930", 2025, "20250318000984")
    assert write_text_atomic(md_path, "hello\r\n")
    assert md_path.read_text(encoding="utf-8") == "hello\n"
    assert not write_text_atomic(md_path, "hello")
