import asyncio
from pathlib import Path

from zhaoxi.tools.packages import create_package_tools, discover_tool_packages


def test_markitdown_package_is_discoverable():
    packages = discover_tool_packages("tools")
    package = next(item for item in packages if item.package_id == "markitdown-tool")
    assert package.capability_declaration().tool is True
    assert [tool.name for tool in create_package_tools(package, {})] == ["markitdown_convert"]


def test_markitdown_tool_converts_local_markdown(tmp_path: Path):
    package = next(item for item in discover_tool_packages("tools") if item.package_id == "markitdown-tool")
    tool = create_package_tools(package, {})[0]
    source = tmp_path / "sample.md"
    source.write_text("# Hello\n", encoding="utf-8")
    result = asyncio.run(tool.run({"input_path": str(source)}))
    assert result.success is True
    assert "# Hello" in result.data["markdown"]
