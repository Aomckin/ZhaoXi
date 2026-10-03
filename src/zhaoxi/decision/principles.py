"""Query knowledge, not a keyword-to-verdict route or a PICK prerequisite."""
import re


def relevance(query: str, content: str) -> int:
    def terms(value):
        value = value.casefold()
        result = set(re.findall(r"[a-z0-9_]{2,}", value))
        result.update(part[i:i + 2] for part in re.findall(r"[\u4e00-\u9fff]{2,}", value)
                      for i in range(len(part) - 1))
        return result
    return len(terms(query) & terms(content))
