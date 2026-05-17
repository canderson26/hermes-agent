import json

from tools.obsidian_tools import obsidian_read_tasks_tool


def test_obsidian_read_tasks_returns_only_active_tasks_by_default(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Tasks.md").write_text(
        "# Inbox\n"
        "- [ ] Call Lauren 📅 2026-05-09\n"
        "- [x] Completed thing\n"
        "# Work\n"
        "- [/] Waiting on Sean\n"
        "- [-] Cancelled errand\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    result = json.loads(obsidian_read_tasks_tool(path="Tasks.md", include_done=False, limit=10))

    assert result["path"] == "Tasks.md"
    assert result["total_tasks"] == 4
    assert result["active_tasks"] == 2
    assert result["matched_tasks"] == 2
    assert result["returned_tasks"] == 2
    assert result["truncated"] is False
    assert [task["text"] for task in result["tasks"]] == [
        "Call Lauren 📅 2026-05-09",
        "Waiting on Sean",
    ]
    assert result["tasks"][0]["due"] == "2026-05-09"
    assert result["tasks"][0]["section"] == "Inbox"
    assert result["tasks"][1]["status"] == "active"


def test_obsidian_read_tasks_can_include_done_and_cancelled(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Tasks.md").write_text(
        "# Inbox\n"
        "- [ ] Open\n"
        "- [x] Done\n"
        "- [-] Cancelled\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    result = json.loads(obsidian_read_tasks_tool(include_done=True, limit=10))

    assert [task["status"] for task in result["tasks"]] == ["open", "done", "cancelled"]
    assert result["matched_tasks"] == 3


def test_obsidian_read_tasks_honors_limit_but_keeps_counts(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Tasks.md").write_text(
        "# Inbox\n- [ ] One\n- [ ] Two\n- [ ] Three\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    result = json.loads(obsidian_read_tasks_tool(limit=2))

    assert result["matched_tasks"] == 3
    assert result["returned_tasks"] == 2
    assert result["truncated"] is True
    assert [task["text"] for task in result["tasks"]] == ["One", "Two"]


def test_obsidian_read_tasks_rejects_paths_outside_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("- [ ] nope\n", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    result = json.loads(obsidian_read_tasks_tool(path=str(outside)))

    assert "error" in result
    assert "inside the configured Obsidian vault" in result["error"]
