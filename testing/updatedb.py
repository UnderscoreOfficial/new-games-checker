import sqlite3

connect = sqlite3.connect("games.db")
cursor = connect.cursor()

# cursor.execute("alter table games add column platform integer")

# cursor.execute("update games set released=0")
# cursor.execute("alter table games add column released integer")
# cursor.execute("alter table games drop column platform")

# cursor.execute("alter table games rename datetime TO release_date")

connect.commit()
connect.close()
