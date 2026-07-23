# InterviewAce AI

## MySQL Setup

Update `.env` with your local MySQL credentials before testing login or registration:

```env
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=InterviewAI
```

Then run `database/database.sql` in MySQL to create the database, tables, and starter questions.

Or run the setup script from the project folder:

```powershell
python setup_database.py
```

Start the Flask app:

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5000/
```
