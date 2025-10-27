import os
import re
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, g
from werkzeug.utils import secure_filename
from pdfminer.high_level import extract_text as extract_text_from_pdf
import docx2txt

# Config
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "docx"}
DB_PATH = "resumes.db"
MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.secret_key = os.environ.get("FLASK_SECRET", "change-me-in-prod")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database helpers
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            filename TEXT,
            score REAL,
            matches TEXT,
            years_experience INTEGER,
            education TEXT,
            job_description TEXT,
            created_at TEXT
        )
        """
    )
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# Utility
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text(filepath, ext):
    try:
        if ext == "pdf":
            return extract_text_from_pdf(filepath)
        elif ext == "docx":
            return docx2txt.process(filepath)
    except Exception as e:
        app.logger.exception("Error extracting text: %s", e)
        return ""
    return ""

def find_years_of_experience(text):
    # naive search: patterns like "5 years", "10+ years", "three years" not handled
    matches = re.findall(r"(\d+)\s*\+\s*years|(\d+)\s+years|(\d+)-year", text, flags=re.I)
    nums = []
    for t in matches:
        for token in t:
            if token and token.isdigit():
                nums.append(int(token))
    return max(nums) if nums else 0

def find_education(text):
    text_l = text.lower()
    if "phd" in text_l or "ph.d" in text_l or "doctorate" in text_l:
        return "PhD"
    if "master" in text_l or "ms " in text_l or "m.sc" in text_l or "Post-graduate" in text_l:
        return "Master"
    if "bachelor" in text_l or "b.s" in text_l or "bs " in text_l or "under-graduate" in text_l or "be" in text_l:
        return "Bachelor"
    return "Not specified"

def score_resume(text, required_skills):
    text_l = text.lower()
    skills = [s.strip().lower() for s in required_skills if s.strip()]
    if not skills:
        skills = []

    matched_skills = [s for s in skills if s in text_l]
    skills_score = (len(matched_skills) / len(skills) * 70) if skills else 0  # 0-70 points

    years = find_years_of_experience(text)
    # years score: 0 years => 0, 10+ => 30
    years_score = min(years, 10) / 10 * 30

    education = find_education(text)
    edu_score = 0
    if education == "PhD":
        edu_score = 10
    elif education == "Master":
        edu_score = 7
    elif education == "Bachelor":
        edu_score = 4
    # Cap total to 100
    total = skills_score + years_score + edu_score
    total = round(min(total, 100), 1)

    return {
        "score": total,
        "matched_skills": matched_skills,
        "years": years,
        "education": education
    }

# Routes
#@app.before_first_request
#def setup():
 #   init_db()

@app.route("/")
def index():
    # Provide some default skill suggestions for UI
    default_skills = "Python, Flask, SQL, REST, Docker, AWS"
    return render_template("index.html", default_skills=default_skills)

@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    job_description = request.form.get("job_description", "").strip()
    skills_raw = request.form.get("skills", "").strip()
    skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

    file = request.files.get("resume")
    if not file or file.filename == "":
        flash("Please attach a resume (PDF or DOCX).")
        return redirect(url_for("index"))

    if not allowed_file(file.filename):
        flash("Unsupported file type. Allowed: pdf, docx")
        return redirect(url_for("index"))

    filename = secure_filename(f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    ext = filename.rsplit(".", 1)[1].lower()
    text = extract_text(filepath, ext)
    if not text:
        flash("Could not extract text from the resume. Make sure the file is valid.")
        return redirect(url_for("index"))

    # If user didn't provide skills, try to get top words from job_description
    if not skills:
        # naive keywords from job description (split by commas/space, remove common stopwords)
        # For a production app use real NLP keyword extraction.
        words = re.findall(r"[A-Za-z\+#]{2,}", job_description)
        stop = {"and","or","the","with","to","for","of","in","on","a","an"}
        skills = [w for w in words if w.lower() not in stop][:10]

    result = score_resume(text, skills)

    # Save record to DB
    db = get_db()
    db.execute(
        "INSERT INTO resumes (name, email, filename, score, matches, years_experience, education, job_description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            email,
            filename,
            result["score"],
            ",".join(result["matched_skills"]),
            result["years"],
            result["education"],
            job_description,
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()

    return render_template("result.html",
        name=name,
        email=email,
        score=result["score"],
        matched_skills=result["matched_skills"],
        years=result["years"],
        education=result["education"],
        filename=filename,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

@app.route("/admin")
def admin():
    db = get_db()
    cur = db.execute("SELECT * FROM resumes ORDER BY created_at DESC")
    rows = cur.fetchall()
    return render_template("admin.html", rows=rows)

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
