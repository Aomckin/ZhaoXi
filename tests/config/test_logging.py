import logging

from zhaoxi.config.logging import CorrelationFilter
from zhaoxi.reliability import CorrelationContext, correlation_scope


def test_logging_filter_adds_correlation_without_user_content():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "safe", (), None)
    with correlation_scope(CorrelationContext(trace_id="trace-1", request_id="request-1")):
        assert CorrelationFilter().filter(record)
    assert record.trace_id == "trace-1"
    assert record.request_id == "request-1"
