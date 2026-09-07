import os
from pathlib import Path

import pytest

from zhaoxi.archive.models import ArchiveAuthority, ArchiveScope
from zhaoxi.archive.parser import ArchiveParseError, chunk_markdown, parse_document
from zhaoxi.archive.service import ArchiveNotFoundError, ArchiveService
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.builtin.archive_tools import create_archive_tools


CANONICAL = """---
id: zhaoxi-lore-v1.2
title: 朝汐角色身世设定
scope: zhaoxi
type: lore
authority: canonical
updated_at: 2026-09-04
tags: [朝汐, 潮庭, 向日葵]
---
# 朝汐角色身世设定

## 害怕的事物

### 怕黑

朝汐怕黑，因为她最初独自在潮庭生活。

## 信物

向日葵发卡是暗苟专门送给朝汐的礼物。文档没有记录赠送日期。
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def service(tmp_path: Path, **kwargs) -> ArchiveService:
    return ArchiveService(tmp_path / "archive", tmp_path / "state" / "archive.db", **kwargs)


def test_front_matter_defaults_and_heading_chunking(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    parsed = parse_document(
        "# 无元数据文档\n\n正文",
        relative_path="projects/demo.md",
        modified_at=0,
        archive_root=root,
    )
    again = parse_document(
        "# 标题已改变\n\n正文",
        relative_path="projects/demo.md",
        modified_at=0,
        archive_root=root,
    )
    assert parsed.document_id == again.document_id
    assert parsed.scope is ArchiveScope.PROJECTS
    assert parsed.authority is ArchiveAuthority.REFERENCE
    assert parsed.title == "无元数据文档"
    chunks = chunk_markdown("# A\n开头\n## B\n" + "内容" * 100, max_chars=80, overlap=10)
    assert chunks[0].heading_path == "A"
    assert all(len(item.content) <= 80 for item in chunks)
    assert any(item.heading_path == "A > B" for item in chunks)


def test_malformed_front_matter_isolated_from_other_documents(tmp_path):
    archive = tmp_path / "archive"
    write(archive / "zhaoxi" / "good.md", CANONICAL)
    write(archive / "user" / "bad.md", "---\ntags: [broken\n---\n# bad")
    index = service(tmp_path)
    report = index.reindex()
    assert report.documents == 1
    assert len(report.errors) == 1
    assert report.errors[0]["source_path"] == "user/bad.md"
    assert index.status()["index_healthy"] is False


def test_incremental_update_delete_and_no_duplicate_chunks(tmp_path):
    document = tmp_path / "archive" / "zhaoxi" / "lore.md"
    write(document, CANONICAL)
    index = service(tmp_path)
    first = index.reindex()
    second = index.reindex()
    assert first.added == 1
    assert second.unchanged == 1
    assert second.chunks == first.chunks

    write(document, CANONICAL.replace("独自在潮庭", "曾经独自在潮庭"))
    changed = index.reindex()
    assert changed.updated == 1
    assert "曾经独自" in index.read_document("zhaoxi-lore-v1.2").content

    document.unlink()
    deleted = index.reindex()
    assert deleted.removed == 1
    assert index.search("怕黑") == []


def test_chinese_search_filters_ranking_and_context_limits(tmp_path):
    write(tmp_path / "archive" / "zhaoxi" / "lore.md", CANONICAL)
    write(
        tmp_path / "archive" / "user" / "plan.md",
        "---\nid: user-plan\ntitle: 长期研究\nscope: user\ntype: plan\n"
        "authority: personal\ntags: [桌面 Agent]\n---\n# 规划\n暗苟想长期研究桌面型生活 Agent。",
    )
    index = service(tmp_path, search_top_k=5, context_max_chars=1200)
    index.reindex()
    fear = index.search("朝汐为什么怕黑", scope=ArchiveScope.ZHAOXI, top_k=1)
    assert len(fear) == 1
    assert "怕黑" in fear[0].heading_path
    assert fear[0].authority is ArchiveAuthority.CANONICAL
    assert index.search("向日葵发卡", authority=ArchiveAuthority.PERSONAL) == []
    personal = index.search("我最近想长期研究什么", scope=ArchiveScope.USER)
    assert personal[0].document_id == "user-plan"
    bounded = index.search("朝汐", max_chars=200)
    assert sum(len(item.snippet) for item in bounded) <= 200


def test_read_by_heading_is_bounded_and_missing_is_clear(tmp_path):
    write(tmp_path / "archive" / "zhaoxi" / "lore.md", CANONICAL)
    index = service(tmp_path, max_document_chars=500)
    index.reindex()
    result = index.read_document("zhaoxi-lore-v1.2", section="怕黑", max_chars=10)
    assert len(result.content) <= 10
    assert result.truncated
    with pytest.raises(ArchiveNotFoundError, match="不存在文档"):
        index.read_document("missing")
    with pytest.raises(ArchiveNotFoundError, match="不存在章节"):
        index.read_document("zhaoxi-lore-v1.2", section="不存在")


def test_attachment_path_traversal_and_absolute_paths_are_rejected(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    base = "---\nid: sidecar\ntitle: 图\nscope: zhaoxi\ntype: visual\nauthority: canonical\n"
    for path in ("../../secret.png", str((tmp_path / "secret.png").resolve())):
        with pytest.raises(ArchiveParseError, match="attachment path"):
            parse_document(
                base + f"attachments:\n  - type: image\n    path: '{path}'\n---\n# 图",
                relative_path="zhaoxi/image.md",
                modified_at=0,
                archive_root=root,
            )


def test_symlink_outside_archive_is_not_indexed(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# secret", encoding="utf-8")
    link = tmp_path / "archive" / "reference" / "link.md"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    index = service(tmp_path)
    report = index.reindex()
    assert report.documents == 0
    assert report.errors


@pytest.mark.asyncio
async def test_archive_tools_are_read_only_and_return_source_metadata(tmp_path):
    write(tmp_path / "archive" / "zhaoxi" / "lore.md", CANONICAL)
    index = service(tmp_path)
    index.reindex()
    tools = create_archive_tools(index)
    assert all(tool.permission is PermissionLevel.READ for tool in tools)
    assert all(tool.side_effects == frozenset({SideEffect.NONE}) for tool in tools)
    result = await tools[1].run({"query": "向日葵发卡"})
    assert result.success
    assert result.metadata["source_kind"] == "tidecourt_archive"
    assert result.data[0]["source_path"] == "zhaoxi/lore.md"
