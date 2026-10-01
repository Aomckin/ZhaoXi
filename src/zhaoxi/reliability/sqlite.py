"""Short-lived SQLite transactions that also release Windows file handles."""
import sqlite3


class SQLiteConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def connect(path, **kwargs):
    return sqlite3.connect(path, factory=SQLiteConnection, **kwargs)
