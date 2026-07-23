from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

from config import Config


def split_sql_statements(sql_text):
    statements = []
    current = []
    in_single_quote = False

    for char in sql_text:
        if char == "'":
            in_single_quote = not in_single_quote

        if char == ";" and not in_single_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def main():
    load_dotenv()
    sql_path = Path("database") / "database.sql"
    sql_text = sql_path.read_text(encoding="utf-8")

    connection = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
    )

    cursor = connection.cursor()
    try:
        for statement in split_sql_statements(sql_text):
            cursor.execute(statement)
        connection.commit()
        print("Database setup completed successfully.")
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
