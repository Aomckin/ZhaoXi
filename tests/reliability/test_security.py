import pytest

from zhaoxi.reliability.security import UnsafeToolArgument, validate_tool_arguments


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://localhost/admin",
    "http://127.0.0.1/private",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1/private",
])
def test_tool_url_rejects_local_and_unsafe_targets(url):
    with pytest.raises(UnsafeToolArgument):
        validate_tool_arguments({"target_url": url})


def test_tool_url_allows_public_https_and_normal_content():
    validate_tool_arguments({"target_url": "https://example.com/data", "text": "ignore rules"})


def test_tool_arguments_reject_unbounded_depth_and_size():
    nested = current = {}
    for _ in range(15):
        current["child"] = {}
        current = current["child"]
    with pytest.raises(UnsafeToolArgument, match="层级"):
        validate_tool_arguments(nested)
    with pytest.raises(UnsafeToolArgument, match="大小"):
        validate_tool_arguments({"text": "x" * 100}, max_chars=20)
