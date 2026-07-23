from functools import wraps
import json
import logging
import time

import mysql.connector
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from services.ai import evaluate_answer, evaluate_interview_summary
from services.ml_model import predict_answer


app = Flask(__name__)
app.config.from_object(Config)
logging.basicConfig(level=logging.INFO)

INTERVIEW_QUESTION_COUNT = 5
INTERVIEW_TIME_LIMIT_SECONDS = 20 * 60
ALLOWED_SUBJECTS = {"Python", "DBMS", "SQL", "OOP", "OS"}
ALLOWED_DIFFICULTIES = {"Easy", "Medium", "Hard"}
DATABASE_MAINTENANCE_DONE = False


def json_dumps(data):
    return json.dumps(data, ensure_ascii=True)


def json_loads(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_choice(value, allowed_values, default_value):
    value = (value or default_value).strip()
    return value if value in allowed_values else default_value


def clean_text(value, max_length):
    return (value or "").strip()[:max_length]


def infer_topic(subject, question, missing_concepts):
    if missing_concepts:
        return str(missing_concepts[0]).strip()

    text = f"{subject} {question}".lower()
    topic_keywords = [
        ("memory", "Memory Management"),
        ("garbage", "Memory Management"),
        ("dynamic typing", "Dynamic Typing"),
        ("typing", "Dynamic Typing"),
        ("list", "Lists"),
        ("tuple", "Tuples"),
        ("dictionary", "Dictionaries"),
        ("function", "Functions"),
        ("lambda", "Functions"),
        ("class", "Object-Oriented Programming"),
        ("object", "Object-Oriented Programming"),
        ("inheritance", "Object-Oriented Programming"),
        ("polymorphism", "Object-Oriented Programming"),
        ("encapsulation", "Object-Oriented Programming"),
        ("exception", "Exception Handling"),
        ("file", "File Handling"),
        ("sql", "SQL"),
        ("join", "Joins"),
        ("normal", "Normalization"),
        ("transaction", "Transactions"),
        ("acid", "Transactions"),
        ("process", "Process Management"),
        ("thread", "Threading"),
    ]

    for keyword, topic in topic_keywords:
        if keyword in text:
            return topic

    return f"{subject} Basics"


def get_db_connection():
    return mysql.connector.connect(
        host=app.config["MYSQL_HOST"],
        user=app.config["MYSQL_USER"],
        password=app.config["MYSQL_PASSWORD"],
        database=app.config["MYSQL_DATABASE"],
    )


def clear_interview_session():
    """Remove only active-interview keys so login/dashboard state remains intact."""
    for key in (
        "interview_id",
        "last_answer_id",
        "subject",
        "difficulty",
        "interview_question_ids",
        "current_question_index",
        "asked_question_ids",
        "current_score",
        "interview_started_at",
        "interview_duration_seconds",
        "interview_completed",
    ):
        session.pop(key, None)


def get_elapsed_seconds():
    started_at = session.get("interview_started_at")
    if not started_at:
        return 0
    return max(0, int(time.time() - float(started_at)))


def get_remaining_seconds():
    return max(0, INTERVIEW_TIME_LIMIT_SECONDS - get_elapsed_seconds())


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes} min {remaining_seconds:02d} sec"


def build_timeout_feedback(question):
    return {
        "missing_concepts": ["Time management"],
        "correct_answer": question.get("ideal_answer", ""),
        "suggestions": [
            "Submit an answer before the timer reaches zero.",
            "Practice concise answers for timed interviews.",
        ],
    }


def update_interview_score_and_duration(cursor, interview_id):
    """Keep interview score and duration synchronized after each submitted answer."""
    duration_seconds = min(get_elapsed_seconds(), INTERVIEW_TIME_LIMIT_SECONDS)
    cursor.execute(
        """
        UPDATE Interviews
        SET score = (
                SELECT COALESCE(AVG(AI_score), 0)
                FROM Answers
                WHERE interview_id = %s
            ),
            duration_seconds = %s
        WHERE interview_id = %s
        """,
        (interview_id, duration_seconds, interview_id),
    )
    session["interview_duration_seconds"] = duration_seconds


def ensure_interview_duration_column(cursor):
    """Add duration storage for existing databases without requiring a rebuild."""
    cursor.execute("SHOW COLUMNS FROM Interviews LIKE 'duration_seconds'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE Interviews ADD COLUMN duration_seconds INT DEFAULT 0")

    cursor.execute("SHOW COLUMNS FROM Interviews LIKE 'report_summary'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE Interviews ADD COLUMN report_summary TEXT")


def ensure_database_indexes(cursor):
    """Add helpful indexes for dashboard/report queries while preserving existing tables."""
    global DATABASE_MAINTENANCE_DONE
    if DATABASE_MAINTENANCE_DONE:
        return

    indexes = [
        ("Interviews", "idx_interviews_user_date", "CREATE INDEX idx_interviews_user_date ON Interviews(user_id, date)"),
        ("Interviews", "idx_interviews_score", "CREATE INDEX idx_interviews_score ON Interviews(score)"),
        ("Answers", "idx_answers_interview", "CREATE INDEX idx_answers_interview ON Answers(interview_id)"),
        ("Answers", "idx_answers_question", "CREATE INDEX idx_answers_question ON Answers(question_id)"),
        ("Questions", "idx_questions_subject_difficulty", "CREATE INDEX idx_questions_subject_difficulty ON Questions(subject, difficulty)"),
    ]

    for table_name, index_name, statement in indexes:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND index_name = %s
            """,
            (table_name, index_name),
        )
        if not cursor.fetchone()["total"]:
            cursor.execute(statement)

    DATABASE_MAINTENANCE_DONE = True


def pdf_escape(text):
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_simple_pdf(title, lines):
    """Generate a dependency-free PDF with clean text pages."""
    page_chunks = [lines[index:index + 38] for index in range(0, len(lines), 38)] or [[]]
    objects = []
    page_refs = []

    for page_index, chunk in enumerate(page_chunks):
        y = 760
        text_lines = ["BT", "/F1 18 Tf", f"72 {y} Td", f"({pdf_escape(title)}) Tj"]
        y -= 34
        text_lines.extend(["/F1 10 Tf", f"0 -34 Td"])

        for line in chunk:
            text_lines.append(f"({pdf_escape(line)}) Tj")
            text_lines.append("0 -16 Td")

        text_lines.append("ET")
        stream = "\n".join(text_lines)
        content_id = len(objects) + 1
        objects.append(f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream")
        page_id = len(objects) + 1
        page_refs.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 0 0 R >> >> /Contents {content_id} 0 R >>"
        )

    font_id = len(objects) + 1
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objects) + 1
    kids = " ".join(f"{page_id} 0 R" for page_id in page_refs)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>")
    catalog_id = len(objects) + 1
    objects.append(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    patched_objects = []
    for obj in objects:
        patched_objects.append(
            obj.replace("/Parent 0 0 R", f"/Parent {pages_id} 0 R").replace("/F1 0 0 R", f"/F1 {font_id} 0 R")
        )

    pdf = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(patched_objects, start=1):
        offsets.append(len(pdf.encode("latin-1", errors="replace")))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"

    xref_offset = len(pdf.encode("latin-1", errors="replace"))
    pdf += f"xref\n0 {len(patched_objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(patched_objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return pdf.encode("latin-1", errors="replace")


def pdf_response(filename, title, lines):
    return Response(
        generate_simple_pdf(title, lines),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def get_owned_interview(cursor, interview_id, user_id):
    cursor.execute(
        """
        SELECT i.interview_id, i.date, i.score, i.duration_seconds, u.name, u.email, u.college, u.branch,
               COALESCE(MAX(q.subject), 'Interview') AS subject,
               COALESCE(MAX(q.difficulty), 'Mixed') AS difficulty
        FROM Interviews i
        JOIN Users u ON u.id=i.user_id
        LEFT JOIN Answers a ON a.interview_id=i.interview_id
        LEFT JOIN Questions q ON q.question_id=a.question_id
        WHERE i.interview_id=%s AND i.user_id=%s
        GROUP BY i.interview_id, i.date, i.score, i.duration_seconds, u.name, u.email, u.college, u.branch
        """,
        (interview_id, user_id),
    )
    return cursor.fetchone()


def achievement_badges(total_interviews, highest_score, average_score, subject_scores):
    badges = [
        {"name": "First Interview", "unlocked": total_interviews >= 1},
        {"name": "5 Interviews", "unlocked": total_interviews >= 5},
        {"name": "10 Interviews", "unlocked": total_interviews >= 10},
        {"name": "90% Score", "unlocked": highest_score >= 9},
        {"name": "SQL Expert", "unlocked": subject_scores.get("SQL", 0) >= 8},
        {"name": "Python Expert", "unlocked": subject_scores.get("Python", 0) >= 8},
        {"name": "DBMS Master", "unlocked": subject_scores.get("DBMS", 0) >= 8},
        {"name": "Interview Ready", "unlocked": average_score >= 8},
    ]
    return badges


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    app.logger.exception("Unhandled application error: %s", exc)
    flash("Something went wrong. Please try again.", "error")

    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/welcome")
def welcome():
    return render_template("welcome.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = clean_text(request.form.get("name"), 100)
        college = clean_text(request.form.get("college"), 150)
        branch = clean_text(request.form.get("branch"), 100)
        email = clean_text(request.form.get("email"), 150).lower()
        password = request.form.get("password", "")

        if not all([name, college, branch, email, password]):
            flash("Please fill all registration fields.", "error")
            return render_template("register.html")

        if "@" not in email or len(password) < 6:
            flash("Enter a valid email and a password of at least 6 characters.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id FROM Users WHERE email = %s", (email,))

            if cursor.fetchone():
                flash("Email already registered. Please login.", "error")
                return redirect(url_for("login"))

            cursor.execute(
                """
                INSERT INTO Users (name, email, password, college, branch)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, email, password_hash, college, branch),
            )
            connection.commit()

            session["user_id"] = cursor.lastrowid
            session["user_name"] = name
            flash("Registration successful.", "success")
            return redirect(url_for("dashboard"))
        except Error as exc:
            flash(f"Database error: {exc}", "error")
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = clean_text(request.form.get("email"), 150).lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter email and password.", "error")
            return render_template("login.html")

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, name, password FROM Users WHERE email = %s",
                (email,),
            )
            user = cursor.fetchone()

            if user and check_password_hash(user["password"], password):
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                flash("Login successful.", "success")
                return redirect(url_for("dashboard"))

            flash("Invalid email or password.", "error")
        except Error as exc:
            flash(f"Database error: {exc}", "error")
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)
        ensure_database_indexes(cursor)

        user_id = session["user_id"]

        # Dashboard-level analytics from MySQL.
        cursor.execute("""
            SELECT
                COUNT(*) AS total_interviews,
                ROUND(AVG(score),2) AS average_score,
                MAX(score) AS highest_score,
                MIN(score) AS lowest_score,
                ROUND(AVG(duration_seconds),0) AS average_duration_seconds
            FROM Interviews
            WHERE user_id=%s
        """, (user_id,))
        stats = cursor.fetchone()
        total_interviews = int(stats["total_interviews"] or 0)

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM Answers a
            JOIN Interviews i ON a.interview_id=i.interview_id
            WHERE i.user_id=%s
        """, (user_id,))
        questions_attempted = int(cursor.fetchone()["total"] or 0)

        # Every interview appears in dashboard history and links to its full report.
        cursor.execute("""
            SELECT
                i.interview_id,
                i.date,
                i.score,
                i.duration_seconds,
                COUNT(a.answer_id) AS questions_attempted,
                COALESCE(MAX(q.subject), 'Interview') AS subject,
                COALESCE(MAX(q.difficulty), 'Mixed') AS difficulty
            FROM Interviews i
            LEFT JOIN Answers a
            ON a.interview_id=i.interview_id
            LEFT JOIN Questions q
            ON a.question_id=q.question_id
            WHERE i.user_id=%s
            GROUP BY i.interview_id, i.date, i.score, i.duration_seconds
            ORDER BY i.date DESC
        """, (user_id,))
        history = cursor.fetchall()

        # Fixed subject performance table with average score, interview count, and best score.
        subject_aliases = {
            "Python": ["Python"],
            "SQL": ["SQL"],
            "DBMS": ["DBMS"],
            "Operating System": ["OS", "Operating Systems", "Operating System"],
            "OOP": ["OOP"],
        }
        cursor.execute("""
            SELECT
                q.subject,
                ROUND(AVG(a.AI_score),2) AS avg_score
                ,COUNT(DISTINCT i.interview_id) AS interview_count
                ,MAX(a.AI_score) AS best_score
            FROM Answers a
            JOIN Questions q
            ON a.question_id=q.question_id
            JOIN Interviews i
            ON a.interview_id=i.interview_id
            WHERE i.user_id=%s
            GROUP BY q.subject
        """, (user_id,))
        raw_performance = cursor.fetchall()
        performance_lookup = {row["subject"]: row for row in raw_performance}
        performance = []

        for display_subject, aliases in subject_aliases.items():
            matched_rows = [performance_lookup[alias] for alias in aliases if alias in performance_lookup]
            if matched_rows:
                weighted_total = sum(float(row["avg_score"] or 0) * int(row["interview_count"] or 0) for row in matched_rows)
                interview_count = sum(int(row["interview_count"] or 0) for row in matched_rows)
                avg_score = weighted_total / interview_count if interview_count else 0
                best_score = max(float(row["best_score"] or 0) for row in matched_rows)
            else:
                interview_count = 0
                avg_score = 0
                best_score = 0

            performance.append(
                {
                    "subject": display_subject,
                    "avg_score": avg_score,
                    "percent": int(round(avg_score * 10)),
                    "interview_count": interview_count,
                    "best_score": best_score,
                }
            )

        cursor.execute("""
            SELECT
                i.interview_id,
                i.score
            FROM Interviews i
            WHERE i.user_id=%s
            ORDER BY i.date ASC, i.interview_id ASC
        """, (user_id,))
        trend_rows = cursor.fetchall()

        cursor.execute("""
            SELECT a.AI_feedback
            FROM Answers a
            JOIN Interviews i ON a.interview_id=i.interview_id
            WHERE i.user_id=%s AND a.AI_feedback IS NOT NULL
        """, (user_id,))
        feedback_rows = cursor.fetchall()
        missed_topic_counts = {}

        for row in feedback_rows:
            feedback = json_loads(row.get("AI_feedback") or "{}")
            for topic in feedback.get("missing_concepts", []):
                topic = str(topic).strip()
                if topic:
                    missed_topic_counts[topic] = missed_topic_counts.get(topic, 0) + 1

        weak_topics = [
            {"topic": topic, "count": count}
            for topic, count in sorted(missed_topic_counts.items(), key=lambda item: item[1], reverse=True)
        ][:8]

        history = [
            {
                **row,
                "score": float(row["score"] or 0),
                "duration": format_duration(row.get("duration_seconds") or 0),
                "status": "Excellent"
                if float(row["score"] or 0) >= 8
                else "Good"
                if float(row["score"] or 0) >= 6
                else "Needs Practice",
            }
            for row in history
        ]

        average_score = float(stats["average_score"] or 0)
        highest_score = float(stats["highest_score"] or 0)
        lowest_score = float(stats["lowest_score"] or 0)
        accuracy = int(round(average_score * 10))
        subjects_with_data = [row for row in performance if row["interview_count"] > 0]
        strongest_subject = max(subjects_with_data, key=lambda row: row["avg_score"])["subject"] if subjects_with_data else "Not available"
        weakest_subject = min(subjects_with_data, key=lambda row: row["avg_score"])["subject"] if subjects_with_data else "Not available"
        ai_confidence = min(96, max(72, accuracy + 8)) if total_interviews else 0
        recommendations = [
            f"Keep practicing {weakest_subject} to improve consistency."
            if subjects_with_data
            else "Complete your first interview to unlock personalized insights.",
            "Review ideal answers after every session.",
            "Try one higher difficulty level when your score crosses 8/10.",
        ]

        return render_template(
            "dashboard.html",
            user_name=session["user_name"],
            total_interviews=total_interviews,
            average_score=average_score,
            highest_score=highest_score,
            lowest_score=lowest_score,
            accuracy=accuracy,
            questions_attempted=questions_attempted,
            average_duration=format_duration(stats["average_duration_seconds"] or 0),
            strongest_subject=strongest_subject,
            weakest_subject=weakest_subject,
            ai_confidence=ai_confidence,
            recommendations=recommendations,
            chart_labels=[row["subject"] for row in performance],
            chart_values=[row["percent"] for row in performance],
            trend_labels=[f"Interview {index}" for index, _ in enumerate(trend_rows, start=1)],
            trend_values=[float(row["score"] or 0) for row in trend_rows],
            weak_topics=weak_topics,
            history=history,
            performance=performance
        )

    except Error as e:
        flash(str(e), "error")
        return redirect(url_for("home"))

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

@app.route("/interview", methods=["GET", "POST"])
@login_required
def interview():
    connection = None
    cursor = None

    if request.method == "POST":
        question_id = parse_positive_int(request.form.get("question_id"))
        student_answer = clean_text(request.form.get("student_answer"), 5000)
        interview_id = parse_positive_int(session.get("interview_id"))
        is_time_up = request.form.get("time_up") == "1" or get_remaining_seconds() <= 0

        if not question_id or not interview_id:
            flash("Please start an interview from the dashboard.", "error")
            return redirect(url_for("dashboard"))

        expected_question_ids = session.get("interview_question_ids", [])
        current_index = int(session.get("current_question_index", 0))
        expected_question_id = (
            expected_question_ids[current_index]
            if current_index < len(expected_question_ids)
            else None
        )

        if expected_question_id and question_id != int(expected_question_id):
            flash("This question was already submitted. Continue with the current question.", "error")
            return redirect(url_for("interview"))

        if question_id in session.get("asked_question_ids", []):
            flash("This answer is already saved. Continue with the next question.", "error")
            return redirect(url_for("interview"))

        if not student_answer and not is_time_up:
            flash("Please type your answer before submitting.", "error")
            return redirect(url_for("interview"))

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            ensure_interview_duration_column(cursor)
            cursor.execute(
                """
                SELECT question_id, question, ideal_answer
                FROM Questions
                WHERE question_id = %s
                """,
                (question_id,),
            )
            question = cursor.fetchone()

            if not question:
                flash("Question not found.", "error")
                return redirect(url_for("dashboard"))

            if is_time_up and not student_answer:
                student_answer = "No answer submitted before the timer ended."
                evaluation = {
                    "score": 0,
                    **build_timeout_feedback(question),
                }
            else:
                evaluation = evaluate_answer(
                    app.config["GEMINI_API_KEY"],
                    app.config["GEMINI_MODEL"],
                    question["question"],
                    question["ideal_answer"],
                    student_answer,
                )
            ml_result = predict_answer(student_answer)
            print(ml_result)
            print("Prediction:", ml_result.get("prediction"))
            print("Confidence:", ml_result.get("confidence"))

            feedback = {
                "missing_concepts": evaluation["missing_concepts"],
                "correct_answer": evaluation["correct_answer"],
                "suggestions": evaluation["suggestions"],
            }

            cursor.execute(
            """
            INSERT INTO Answers
            (
                interview_id,
                question_id,
                student_answer,
                AI_feedback,
                AI_score,
                ml_prediction,
                ml_confidence
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                interview_id,
                question_id,
                student_answer,
                json_dumps(feedback),
                evaluation["score"],
                ml_result["prediction"],
                ml_result["confidence"],
            ),
            )
            answer_id = cursor.lastrowid
            asked_question_ids = session.get("asked_question_ids", [])
            if question_id not in asked_question_ids:
                asked_question_ids.append(question_id)
            session["asked_question_ids"] = asked_question_ids
            session["current_score"] = float(session.get("current_score", 0)) + float(evaluation["score"])
            update_interview_score_and_duration(cursor, interview_id)
            connection.commit()

            session["last_answer_id"] = answer_id
            current_index = int(session.get("current_question_index", 0))
            is_finished = is_time_up or current_index >= INTERVIEW_QUESTION_COUNT - 1

            if is_finished:
                session["interview_completed"] = True
                session["current_question_index"] = min(current_index + 1, INTERVIEW_QUESTION_COUNT)
                flash("Interview completed. Final report is ready.", "success")
                return redirect(url_for("result"))

            session["current_question_index"] = current_index + 1
            flash("Answer saved. Next question loaded.", "success")
            return redirect(url_for("interview"))
        except Error as exc:
            flash(f"Database error: {exc}", "error")
        except Exception as exc:
            flash(f"Evaluation error: {exc}", "error")
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

        return redirect(url_for("interview"))

    subject = normalize_choice(request.args.get("subject") or session.get("subject"), ALLOWED_SUBJECTS, "Python")
    difficulty = normalize_choice(request.args.get("difficulty") or session.get("difficulty"), ALLOWED_DIFFICULTIES, "Easy")
    is_new_interview = "subject" in request.args or "difficulty" in request.args

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)

        if is_new_interview:
            clear_interview_session()
            session["subject"] = subject
            session["difficulty"] = difficulty

        if not session.get("interview_id"):
            session["subject"] = subject
            session["difficulty"] = difficulty
            cursor.execute(
                "INSERT INTO Interviews (user_id, score, duration_seconds) VALUES (%s, %s, %s)",
                (session["user_id"], 0, 0),
            )
            connection.commit()
            session["interview_id"] = cursor.lastrowid
            session["current_question_index"] = 0
            session["asked_question_ids"] = []
            session["current_score"] = 0
            session["interview_started_at"] = time.time()
            session["interview_completed"] = False

            cursor.execute(
                """
                SELECT question_id
                FROM Questions
                WHERE subject = %s AND difficulty = %s
                ORDER BY RAND()
                LIMIT %s
                """,
                (subject, difficulty, INTERVIEW_QUESTION_COUNT),
            )
            question_rows = cursor.fetchall()

            if len(question_rows) < INTERVIEW_QUESTION_COUNT:
                cursor.execute("DELETE FROM Interviews WHERE interview_id = %s", (session["interview_id"],))
                connection.commit()
                clear_interview_session()
                flash(
                    f"At least {INTERVIEW_QUESTION_COUNT} questions are required for {subject} / {difficulty}.",
                    "error",
                )
                return redirect(url_for("dashboard"))

            session["interview_question_ids"] = [row["question_id"] for row in question_rows]
        else:
            subject = session.get("subject", subject)
            difficulty = session.get("difficulty", difficulty)

        if session.get("interview_completed"):
            return redirect(url_for("result"))

        if get_remaining_seconds() <= 0:
            question_ids = session.get("interview_question_ids", [])
            current_index = int(session.get("current_question_index", 0))
            if current_index < len(question_ids) and int(question_ids[current_index]) not in session.get("asked_question_ids", []):
                cursor.execute(
                    """
                    SELECT question_id, ideal_answer
                    FROM Questions
                    WHERE question_id = %s
                    """,
                    (question_ids[current_index],),
                )
                timed_out_question = cursor.fetchone()
                if timed_out_question:
                    feedback = build_timeout_feedback(timed_out_question)
                    cursor.execute(
                        """
                        INSERT INTO Answers (interview_id, question_id, student_answer, AI_feedback, AI_score)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            session["interview_id"],
                            timed_out_question["question_id"],
                            "No answer submitted before the timer ended.",
                            json_dumps(feedback),
                            0,
                        ),
                    )
                    session["last_answer_id"] = cursor.lastrowid
                    session["asked_question_ids"] = session.get("asked_question_ids", []) + [int(timed_out_question["question_id"])]
            update_interview_score_and_duration(cursor, session["interview_id"])
            connection.commit()
            session["interview_completed"] = True
            flash("Time is up. Your final report is ready.", "error")
            return redirect(url_for("result"))

        question_ids = session.get("interview_question_ids", [])
        current_index = int(session.get("current_question_index", 0))

        if not question_ids or current_index >= INTERVIEW_QUESTION_COUNT:
            session["interview_completed"] = True
            return redirect(url_for("result"))

        current_question_id = question_ids[current_index]
        cursor.execute(
            """
            SELECT question_id, subject, difficulty, question
            FROM Questions
            WHERE question_id = %s
            """,
            (current_question_id,),
        )
        question = cursor.fetchone()

        if not question:
            flash("Question not found.", "error")
            return redirect(url_for("dashboard"))

        progress_percent = int(((current_index + 1) / INTERVIEW_QUESTION_COUNT) * 100)

        return render_template(
            "interview.html",
            question=question,
            current_question=current_index + 1,
            total_questions=INTERVIEW_QUESTION_COUNT,
            progress_percent=progress_percent,
            remaining_seconds=get_remaining_seconds(),
            answered_count=len(session.get("asked_question_ids", [])),
        )
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/result")
@login_required
def result():
    answer_id = session.get("last_answer_id")
    requested_interview_id = parse_positive_int(request.args.get("interview_id"))
    interview_id = requested_interview_id or parse_positive_int(session.get("interview_id"))

    if not answer_id and not interview_id:
        flash("Submit an interview answer to see results.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)
        ensure_database_indexes(cursor)

        if requested_interview_id:
            cursor.execute(
                """
                SELECT interview_id
                FROM Interviews
                WHERE interview_id = %s AND user_id = %s
                """,
                (requested_interview_id, session["user_id"]),
            )
            if not cursor.fetchone():
                flash("Interview report not found.", "error")
                return redirect(url_for("dashboard"))

        if interview_id:
            query_filter = "a.interview_id = %s"
            query_value = interview_id
        else:
            query_filter = "a.answer_id = %s"
            query_value = parse_positive_int(answer_id)

        cursor.execute(
            f"""
            SELECT a.answer_id,
            a.interview_id,
            a.student_answer,
            a.AI_feedback,
            a.AI_score,
            a.ml_prediction,
            a.ml_confidence,
            i.score AS interview_score,
            i.duration_seconds,
            i.report_summary,
            q.subject,
            q.difficulty,
            q.question
            FROM Answers a
            JOIN Questions q ON q.question_id = a.question_id
            JOIN Interviews i ON i.interview_id = a.interview_id
            WHERE {query_filter}
            ORDER BY a.answer_id ASC
            """,
            (query_value,),
        )
        answer_rows = cursor.fetchall()

        if not answer_rows:
            flash("No evaluated answers found yet.", "error")
            return redirect(url_for("interview"))

        question_reports = []
        all_missing_concepts = []
        all_suggestions = []
        scores = []

        for index, row in enumerate(answer_rows, start=1):
            feedback = json_loads(row.get("AI_feedback") or "{}")
            score = float(row.get("AI_score") or 0)
            score_percent = max(0, min(100, int(round(score * 10))))
            missing_concepts = feedback.get("missing_concepts", [])
            suggestions = feedback.get("suggestions", [])
            confidence = max(50, min(96, int(round(score_percent * 0.93))))
            technical_accuracy = max(35, min(100, score_percent - (len(missing_concepts) * 4)))
            completeness = max(35, min(100, score_percent - (len(missing_concepts) * 7)))
            technical_terms = max(35, min(100, score_percent - 6 if missing_concepts else score_percent))

            all_missing_concepts.extend(missing_concepts)
            all_suggestions.extend(suggestions)
            scores.append(score)
            question_reports.append(
                {
                    "number": index,
                    "question": row["question"],
                    "student_answer": row["student_answer"],
                    "score": score,
                    "score_percent": score_percent,
                    "missing_concepts": missing_concepts,
                    "suggestions": suggestions,
                    "correct_answer": feedback.get("correct_answer", ""),
                    "confidence": confidence,
                    "technical_accuracy": technical_accuracy,
                    "completeness": completeness,
                    "technical_terms": technical_terms,
                    "understanding": max(35, min(100, int(round((technical_accuracy + completeness) / 2)))),
                    "communication": max(40, min(100, confidence - 4)),
                }
            )

        average_score = sum(scores) / len(scores)
        highest_score = max(scores)
        lowest_score = min(scores)
        score_percent = max(0, min(100, int(round(average_score * 10))))
        confidence_percent = max(62, min(94, int(round(score_percent * 0.94))))
        attempted_count = len(question_reports)
        unique_weak_topics = list(dict.fromkeys(str(item) for item in all_missing_concepts if item))[:8]
        strong_topics = [
            report["question"].split("?")[0][:36]
            for report in question_reports
            if report["score"] >= 7
        ]
        weak_topics = unique_weak_topics or ["No major weak topic"]
        technical_accuracy = int(round(sum(item["technical_accuracy"] for item in question_reports) / attempted_count))
        completeness = int(round(sum(item["completeness"] for item in question_reports) / attempted_count))
        technical_terms = int(round(sum(item["technical_terms"] for item in question_reports) / attempted_count))
        understanding = int(round(sum(item["understanding"] for item in question_reports) / attempted_count))
        communication = int(round(sum(item["communication"] for item in question_reports) / attempted_count))
        interview_readiness = (
            "Interview Ready"
            if average_score >= 8
            else "Nearly Ready"
            if average_score >= 6
            else "Needs More Practice"
        )

        if score_percent >= 85:
            confidence_label = "High"
            topic_status = "Strong"
            topic_status_class = "strong"
            summary_points = [
                "Answer covered most key concepts.",
                "Technical accuracy is good.",
                "Explanation could include more examples.",
            ]
        elif score_percent >= 60:
            confidence_label = "Moderate"
            topic_status = "Moderate"
            topic_status_class = "moderate"
            summary_points = [
                "Answer covers the core idea.",
                "Technical accuracy is acceptable.",
                "A few important details need stronger explanation.",
            ]
        else:
            confidence_label = "Needs Revision"
            topic_status = "Needs Revision"
            topic_status_class = "needs-revision"
            summary_points = [
                "Answer needs clearer coverage of key concepts.",
                "Technical accuracy should be improved.",
                "Add examples and important terminology.",
            ]

        first_row = answer_rows[0]
        interview_summary = json_loads(first_row.get("report_summary") or "")
        if not interview_summary:
            interview_summary = evaluate_interview_summary(
                app.config["GEMINI_API_KEY"],
                app.config["GEMINI_MODEL"],
                question_reports,
            )
            cursor.execute(
                "UPDATE Interviews SET report_summary=%s WHERE interview_id=%s",
                (json_dumps(interview_summary), first_row["interview_id"]),
            )
            connection.commit()

        result_data = {
            "AI_score": average_score,
            "interview_id": first_row["interview_id"],
            "average_score": average_score,
            "highest_score": highest_score,
            "lowest_score": lowest_score,
            "subject": first_row["subject"],
            "difficulty": first_row["difficulty"],
            "question_type": "Technical",
            "topic": infer_topic(first_row["subject"], first_row["question"], unique_weak_topics),
            "duration": format_duration(
                first_row.get("duration_seconds") or session.get("interview_duration_seconds") or get_elapsed_seconds()
            ),
            "questions_attempted": attempted_count,
            "total_questions": INTERVIEW_QUESTION_COUNT,
            "accuracy": score_percent,
            "score_percent": score_percent,
            "confidence_percent": confidence_percent,
            "confidence_label": confidence_label,
            "interview_readiness": interview_summary.get("interview_readiness", interview_readiness),
            "overall_ai_feedback": interview_summary,
            "final_recommendation": interview_summary.get("final_recommendation", "Keep practicing weak topics."),
            "missing_concepts": unique_weak_topics,
            "suggestions": all_suggestions[:6],
            "correct_answer": question_reports[-1]["correct_answer"],
            "summary_points": summary_points,
            "topic_status": topic_status,
            "topic_status_class": topic_status_class,
            "question_reports": question_reports,
            "question_chart_labels": [f"Q{item['number']}" for item in question_reports],
            "question_chart_scores": [item["score"] for item in question_reports],
            "radar_labels": [
                "Accuracy",
                "Confidence",
                "Technical Terms",
                "Completeness",
                "Understanding",
                "Communication",
            ],
            "radar_values": [
                score_percent,
                confidence_percent,
                technical_terms,
                completeness,
                understanding,
                communication,
            ],
            "topic_chart_labels": ["Strong Topics", "Weak Topics"],
            "topic_chart_values": [max(1, len(strong_topics)), max(1, len(weak_topics))],
            "strong_topics": strong_topics[:6] or ["Core concepts"],
            "weak_topics": weak_topics,
            "recommendations": {
                "topics_to_revise": interview_summary.get("topics_to_revise", weak_topics),
                "estimated_study_time": interview_summary.get("estimated_study_time", "3-5 hours"),
                "practice_questions_recommendation": interview_summary.get(
                    "practice_questions_recommendation",
                    "Practice 10 questions from weak topics.",
                ),
                "difficulty_recommendation": interview_summary.get(
                    "difficulty_recommendation",
                    "Continue with the current difficulty until your average score reaches 8/10.",
                ),
                "learning_path": interview_summary.get("learning_path", []),
            },
        }
        result_data["performance_metrics"] = [
            {"label": "Accuracy", "value": score_percent},
            {"label": "Completeness", "value": completeness},
            {"label": "Technical Terms", "value": technical_terms},
            {"label": "Confidence", "value": confidence_percent},
        ]

        return render_template("result.html", result=result_data)
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/profile")
@login_required
def profile():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)
        ensure_database_indexes(cursor)
        user_id = session["user_id"]

        cursor.execute("SELECT name, email, college, branch FROM Users WHERE id=%s", (user_id,))
        user = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*) AS total_interviews,
                   ROUND(AVG(score),2) AS average_score,
                   MAX(score) AS highest_score
            FROM Interviews
            WHERE user_id=%s
            """,
            (user_id,),
        )
        stats = cursor.fetchone()
        total_interviews = int(stats["total_interviews"] or 0)
        average_score = float(stats["average_score"] or 0)
        highest_score = float(stats["highest_score"] or 0)
        interview_readiness = "Interview Ready" if average_score >= 8 else "Keep Practicing"

        cursor.execute(
            """
            SELECT q.subject, ROUND(AVG(a.AI_score),2) AS avg_score
            FROM Answers a
            JOIN Questions q ON q.question_id=a.question_id
            JOIN Interviews i ON i.interview_id=a.interview_id
            WHERE i.user_id=%s
            GROUP BY q.subject
            """,
            (user_id,),
        )
        subject_scores = {row["subject"]: float(row["avg_score"] or 0) for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT i.interview_id, i.date, i.score,
                   COALESCE(MAX(q.subject), 'Interview') AS subject
            FROM Interviews i
            LEFT JOIN Answers a ON a.interview_id=i.interview_id
            LEFT JOIN Questions q ON q.question_id=a.question_id
            WHERE i.user_id=%s
            GROUP BY i.interview_id, i.date, i.score
            ORDER BY i.date DESC
            LIMIT 6
            """,
            (user_id,),
        )
        recent_activity = cursor.fetchall()

        return render_template(
            "profile.html",
            user=user,
            total_interviews=total_interviews,
            average_score=average_score,
            highest_score=highest_score,
            interview_readiness=interview_readiness,
            achievements=achievement_badges(total_interviews, highest_score, average_score, subject_scores),
            recent_activity=recent_activity,
        )
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/leaderboard")
@login_required
def leaderboard():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_database_indexes(cursor)
        cursor.execute(
            """
            SELECT u.name AS student,
                   COALESCE(MAX(q.subject), 'Interview') AS subject,
                   ROUND(i.score,2) AS average_score,
                   i.date
            FROM Interviews i
            JOIN Users u ON u.id=i.user_id
            LEFT JOIN Answers a ON a.interview_id=i.interview_id
            LEFT JOIN Questions q ON q.question_id=a.question_id
            GROUP BY i.interview_id, u.name, i.score, i.date
            ORDER BY i.score DESC, i.date ASC
            LIMIT 10
            """
        )
        leaders = [
            {**row, "rank": index}
            for index, row in enumerate(cursor.fetchall(), start=1)
        ]
        return render_template("leaderboard.html", leaders=leaders)
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/report/pdf")
@login_required
def report_pdf():
    interview_id = parse_positive_int(request.args.get("interview_id")) or parse_positive_int(session.get("interview_id"))
    if not interview_id:
        flash("No interview report selected.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)
        ensure_database_indexes(cursor)
        interview = get_owned_interview(cursor, interview_id, session["user_id"])
        if not interview:
            flash("Interview report not found.", "error")
            return redirect(url_for("dashboard"))

        cursor.execute(
            """
            SELECT q.question, a.student_answer, a.AI_score, a.AI_feedback
            FROM Answers a
            JOIN Questions q ON q.question_id=a.question_id
            WHERE a.interview_id=%s
            ORDER BY a.answer_id ASC
            """,
            (interview_id,),
        )
        answers = cursor.fetchall()
        lines = [
            "InterviewAce AI - Professional Interview Report",
            f"Student: {interview['name']}",
            f"Interview Date: {interview['date']}",
            f"Subject: {interview['subject']}",
            f"Difficulty: {interview['difficulty']}",
            f"Overall Score: {float(interview['score'] or 0):.1f}/10",
            f"Duration: {format_duration(interview.get('duration_seconds') or 0)}",
            "",
            "Question-wise Report",
        ]

        for index, answer in enumerate(answers, start=1):
            feedback = json_loads(answer.get("AI_feedback") or "{}")
            lines.extend(
                [
                    "",
                    f"Q{index}: {answer['question']}",
                    f"Student Answer: {answer['student_answer']}",
                    f"AI Score: {float(answer['AI_score'] or 0):.1f}/10",
                    f"Weak Topics: {', '.join(feedback.get('missing_concepts', [])) or 'None'}",
                    f"Correct Answer: {feedback.get('correct_answer', '')}",
                    f"Suggestions: {', '.join(feedback.get('suggestions', [])) or 'Keep practicing.'}",
                ]
            )

        lines.extend(
            [
                "",
                "Charts Summary",
                "Bar Chart: Question-wise AI scores.",
                "Radar Chart: Accuracy, Confidence, Technical Terms, Completeness, Understanding, Communication.",
                "Doughnut Chart: Strong Topics vs Weak Topics.",
                "",
                "Overall Feedback",
                "Review weak topics and retake a timed interview for improvement.",
                "",
                "Recommendations",
                "Practice similar questions, revise missed concepts, and move to higher difficulty after 8/10.",
            ]
        )
        return pdf_response(f"interviewace-report-{interview_id}.pdf", "InterviewAce AI Report", lines)
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/certificate/pdf")
@login_required
def certificate_pdf():
    interview_id = parse_positive_int(request.args.get("interview_id")) or parse_positive_int(session.get("interview_id"))
    if not interview_id:
        flash("No interview selected for certificate.", "error")
        return redirect(url_for("dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        ensure_interview_duration_column(cursor)
        ensure_database_indexes(cursor)
        interview = get_owned_interview(cursor, interview_id, session["user_id"])
        if not interview:
            flash("Interview not found.", "error")
            return redirect(url_for("dashboard"))

        score = float(interview["score"] or 0)
        if score < 8:
            flash("Certificate unlocks when average score is at least 8/10.", "error")
            return redirect(url_for("result", interview_id=interview_id))

        lines = [
            "Certificate of Completion",
            "",
            "InterviewAce AI proudly certifies that",
            f"{interview['name']}",
            "has successfully completed an AI-powered mock interview.",
            "",
            f"Score: {score:.1f}/10",
            f"Subject: {interview['subject']}",
            f"Date: {interview['date']}",
            "",
            "Awarded for interview readiness and strong technical performance.",
            "",
            "InterviewAce AI",
        ]
        return pdf_response(f"interviewace-certificate-{interview_id}.pdf", "Certificate of Completion", lines)
    except Error as exc:
        flash(f"Database error: {exc}", "error")
        return redirect(url_for("dashboard"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=False)
