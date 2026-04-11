import sqlite3
from pathlib import Path


def clear_logs(db_path: Path) -> None:
	with sqlite3.connect(db_path) as conn:
		cursor = conn.cursor()
		cursor.execute("DELETE FROM logs")
		cursor.execute("VACUUM")
		conn.commit()


if __name__ == "__main__":
	database_file = Path(__file__).resolve().parent / "logs.db"
	clear_logs(database_file)
	print("Logs cleared successfully.")
