"""`scripts/check_docs_links.py`: every relative link and `#anchor` in the Markdown
docs resolves (T33). GitHub's own heading slugs are the reference."""

from pathlib import Path

from scripts import check_docs_links as links


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_link_to_a_file_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "See [b](b.md) and [c](docs/c.md).\n")
    _write(tmp_path, "b.md", "# B\n")

    problems = links.check(tmp_path)

    assert [(p.file, p.target) for p in problems] == [("a.md", "docs/c.md")]


def test_an_anchor_must_match_a_heading_with_githubs_slugs(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "[ok](b.md#12-dashboards-in-apache-superset-t32) [bad](b.md#nope)\n"
        "[self](#top)\n# Top\n",
    )
    _write(tmp_path, "b.md", "## 12. Dashboards in Apache Superset (T32)\n")

    problems = links.check(tmp_path)

    assert [(p.file, p.target) for p in problems] == [("a.md", "b.md#nope")]


def test_repeated_headings_get_a_numeric_suffix(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "[second](#notes-1)\n## Notes\n## Notes\n")

    assert links.check(tmp_path) == []


def test_external_links_and_code_blocks_are_not_checked(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "[web](https://example.com/x) [mail](mailto:a@b.c)\n"
        "```\n[not a link](missing.md)\n```\n"
        "inline `[also not](missing.md)` code\n",
    )

    assert links.check(tmp_path) == []


def test_a_link_to_a_directory_and_one_with_a_query_are_fine_when_it_exists(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    _write(tmp_path, "a.md", "[dir](docs) [dir2](docs/)\n")

    assert links.check(tmp_path) == []


def test_main_exits_1_when_something_is_broken_and_0_when_not(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "[b](b.md)\n")
    assert links.main(["--root", str(tmp_path)]) == 1

    _write(tmp_path, "b.md", "# B\n")
    assert links.main(["--root", str(tmp_path)]) == 0
