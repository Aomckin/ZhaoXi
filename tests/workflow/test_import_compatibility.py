"""Import regressions for supported Python versions with eager annotations."""


def test_sqlite_workflow_store_annotations_do_not_shadow_builtin_list():
    from zhaoxi.workflow.sqlite import SQLiteWorkflowStore

    assert SQLiteWorkflowStore.__name__ == "SQLiteWorkflowStore"
