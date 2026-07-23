<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=32&pause=1000&color=2E86FF&center=true&vCenter=true&width=600&lines=InterviewAce+AI;AI-Powered+Mock+Interviews;Practice.+Get+Scored.+Improve." alt="Typing SVG" />

<p>
An AI-powered mock interview platform that evaluates your answers in real time, tracks your progress, and helps you interview-ready faster.
</p>

<img src="https://img.shields.io/badge/Flask-3.0.3-000000?style=for-the-badge&logo=flask&logoColor=white" />
<img src="https://img.shields.io/badge/MySQL-Database-4479A1?style=for-the-badge&logo=mysql&logoColor=white" />
<img src="https://img.shields.io/badge/Gemini-API-8E75FF?style=for-the-badge&logo=googlegemini&logoColor=white" />
<img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />

<br/>

<img src="https://img.shields.io/github/stars/your-username/InterviewAce-AI?style=social" />
<img src="https://img.shields.io/github/forks/your-username/InterviewAce-AI?style=social" />
<img src="https://img.shields.io/github/last-commit/your-username/InterviewAce-AI?color=blue" />
<img src="https://img.shields.io/github/license/your-username/InterviewAce-AI?color=green" />

</div>

<br/>

<!-- Demo GIF - replace with your own screen recording -->
<div align="center">
  <img src="docs/demo.gif" alt="InterviewAce AI demo" width="800"/>
  <p><i>⬆️ Replace this with a screen recording of your app (see "Adding the Demo GIF" below)</i></p>
</div>

---

## ✨ Features

- 🎯 **Timed mock interviews** across five subjects — Python, DBMS, SQL, OOP, and OS — at Easy, Medium, or Hard difficulty
- 🤖 **AI-powered answer evaluation** using Google's Gemini API combined with a trained ML model (scikit-learn model + vectorizer)
- ⚡ **Instant feedback** highlighting missing concepts, correct answers, and improvement suggestions
- 📊 **Personal dashboard** with score history, interview readiness, and subject-wise performance
- 🏆 **Achievement badges** based on interviews completed, highest score, and consistency
- 🥇 **Leaderboard** ranking top performers across all users
- 📄 **PDF reports** with a question-by-question breakdown, scores, and recommendations
- 🎓 **Certificates of completion** unlocked once a score threshold is reached
- 🔐 **User authentication** with hashed passwords and session-based login

---

## 🛠️ Tech Stack

<div align="center">

| Layer           | Technology                                |
|-----------------|--------------------------------------------|
| Backend         | Flask 3 (Python)                           |
| Database        | MySQL                                      |
| AI / Evaluation | Google Gemini API (`google-genai`)         |
| ML Model        | scikit-learn model + vectorizer (`.pkl`)   |
| Auth            | Werkzeug password hashing, Flask sessions  |
| PDF Generation  | Custom dependency-free PDF builder         |

</div>

---

## 📁 Project Structure

```
InterviewAce-AI/
├── app.py                  # Main Flask application and routes
├── config.py                # App configuration (env-based)
├── setup_database.py        # Script to initialize the MySQL database
├── requirements.txt
├── database/
│   └── database.sql         # Schema + starter questions
├── models/
│   ├── interview_model.pkl  # Trained ML model
│   └── vectorizer.pkl       # Text vectorizer
├── services/
│   ├── ai.py                 # Gemini-based evaluation logic
│   └── ml_model.py           # ML model prediction logic
├── templates/                # Jinja2 HTML templates
└── static/                   # CSS/JS/assets
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- MySQL Server (running locally or remotely)
- A Google Gemini API key ([Google AI Studio](https://aistudio.google.com/))

### 1. Clone the repository

```bash
git clone https://github.com/your-username/InterviewAce-AI.git
cd InterviewAce-AI
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
SECRET_KEY=your-random-secret-key
SESSION_COOKIE_SECURE=false

MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=InterviewAI

GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

> `.env` is already listed in `.gitignore` — never commit real credentials.

### 4. Set up the database

```bash
mysql -u root -p < database/database.sql
```

Or use the provided setup script:

```bash
python setup_database.py
```

### 5. Run the app

```bash
python app.py
```

Open your browser at:

```
http://127.0.0.1:5000/
```

---

## 📖 Usage

1. **Register** an account and **log in**.
2. From the dashboard, start a new interview by choosing a **subject** and **difficulty**.
3. Answer each question within the time limit — answers are evaluated instantly with AI-generated feedback.
4. View your **results**, download a **PDF report**, and unlock a **certificate** at a score of 8/10 or higher.
5. Track your progress on your **profile** and see how you rank on the **leaderboard**.

---

## ⚙️ Configuration Notes

- `MAX_CONTENT_LENGTH` is capped at 2 MB per request in `config.py`.
- Sessions use `HttpOnly` and `SameSite=Lax` cookies by default; set `SESSION_COOKIE_SECURE=true` in production (behind HTTPS).
- Database indexes and schema migrations for new columns (e.g. `duration_seconds`, `report_summary`) are applied automatically on first relevant request.

---

## 🗺️ Roadmap

- [ ] Add more subjects and question banks
- [ ] Support for voice-based answers
- [ ] Admin panel for managing questions
- [ ] Docker support for easier deployment

---

## 📄 License

LOVELY PROFESSIONAL UNIVERSITY.

---

<div align="center">
Made with ❤️ and a lot of debugging.
</div>
