import sqlite3

conn = sqlite3.connect("logs.db")
cursor = conn.cursor()

cursor.execute("DELETE FROM logs")
conn.commit()

# Optional: Compact the database
cursor.execute("VACUUM")
conn.commit()

conn.close()
print("Logs cleared successfully.")
