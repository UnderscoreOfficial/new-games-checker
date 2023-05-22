import sqlite3

connect = sqlite3.connect("games.db")
cursor = connect.cursor()


# cursor.execute("update games set released=0")
# cursor.execute("alter table games add column released integer")
# cursor.execute("alter table games drop column released")

connect.commit()
connect.close()
