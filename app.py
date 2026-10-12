import calendar as month_calendar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required, login_user, logout_user
from authlib.integrations.base_client.errors import OAuthError
from requests.exceptions import RequestException
from sqlalchemy import func, inspect, text

load_dotenv()

from config import Config
from extensions import db, login_manager, oauth
from models import Mistake, MistakeImage, MockTest, PYQAttempt, Resource, StudySession, Topic, TopicProgress, User
from seed import seed_syllabus
from storage import MAX_UPLOAD_BYTES, delete_upload, local_path, save_upload, upload_size_bytes, upload_url


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config["UPLOAD_FOLDER"] = Path(app.config["UPLOAD_FOLDER"])
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_active_study_timer():
        started_at = None
        paused_at = None
        total_paused_seconds = 0
        if current_user.is_authenticated:
            active_session = (StudySession.query
                              .filter_by(user_id=current_user.id, ended_at=None)
                              .order_by(StudySession.started_at.desc())
                              .first())
            if active_session:
                started_at = active_session.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                else:
                    started_at = started_at.astimezone(timezone.utc)
                paused_at = active_session.paused_at
                if paused_at:
                    paused_at = paused_at.replace(tzinfo=timezone.utc) if paused_at.tzinfo is None else paused_at.astimezone(timezone.utc)
                total_paused_seconds = active_session.total_paused_seconds or 0
        return {
            "active_study_started_at": started_at.isoformat() if started_at else "",
            "active_study_paused_at": paused_at.isoformat() if paused_at else "",
            "active_study_paused_seconds": total_paused_seconds,
        }

    @app.errorhandler(413)
    def upload_too_large(_error):
        back_url = url_for("mistakes_page") if request.path.startswith("/mistakes") else url_for("resources_page")
        return render_template("upload_error.html", back_url=back_url), 413

    with app.app_context():
        db.create_all()
        user_columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
        user_migrations = {
            "exam_year": "INTEGER",
            "college": "VARCHAR(160) NOT NULL DEFAULT ''",
            "course": "VARCHAR(120) NOT NULL DEFAULT ''",
            "daily_goal_minutes": "INTEGER NOT NULL DEFAULT 180",
        }
        for column_name, column_definition in user_migrations.items():
            if column_name not in user_columns:
                db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {column_name} {column_definition}'))
                db.session.commit()
        if "is_active" not in {column["name"] for column in inspect(db.engine).get_columns("topic")}:
            db.session.execute(text("ALTER TABLE topic ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"))
            db.session.commit()
        if "resource_type" not in {column["name"] for column in inspect(db.engine).get_columns("resource")}:
            db.session.execute(text("ALTER TABLE resource ADD COLUMN resource_type VARCHAR(20) NOT NULL DEFAULT 'notes'"))
            db.session.commit()
        resource_columns = {column["name"] for column in inspect(db.engine).get_columns("resource")}
        if "subject_name" not in resource_columns:
            db.session.execute(text("ALTER TABLE resource ADD COLUMN subject_name VARCHAR(120)"))
            db.session.execute(text("UPDATE resource SET subject_name = (SELECT topic.subject FROM topic WHERE topic.id = resource.topic_id) WHERE subject_name IS NULL AND topic_id IS NOT NULL"))
            db.session.commit()
        pyq_columns = {column["name"] for column in inspect(db.engine).get_columns("pyq_attempt")}
        if "questions_attempted" not in pyq_columns:
            db.session.execute(text("ALTER TABLE pyq_attempt ADD COLUMN questions_attempted INTEGER NOT NULL DEFAULT 1"))
            db.session.commit()
        if "correct_count" not in pyq_columns:
            db.session.execute(text("ALTER TABLE pyq_attempt ADD COLUMN correct_count INTEGER NOT NULL DEFAULT 0"))
            db.session.execute(text("UPDATE pyq_attempt SET correct_count = CASE WHEN correct THEN 1 ELSE 0 END"))
            db.session.commit()
        if "review_refs" not in pyq_columns:
            db.session.execute(text("ALTER TABLE pyq_attempt ADD COLUMN review_refs TEXT NOT NULL DEFAULT ''"))
            db.session.commit()
        if "practice_type" not in pyq_columns:
            db.session.execute(text("ALTER TABLE pyq_attempt ADD COLUMN practice_type VARCHAR(10) NOT NULL DEFAULT 'pyq'"))
            db.session.commit()
        study_columns = {column["name"] for column in inspect(db.engine).get_columns("study_session")}
        if "duration_seconds" not in study_columns:
            db.session.execute(text("ALTER TABLE study_session ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0"))
            db.session.execute(text("UPDATE study_session SET duration_seconds = duration_minutes * 60 WHERE duration_seconds = 0 AND duration_minutes > 0"))
            db.session.commit()
        if "paused_at" not in study_columns:
            db.session.execute(text("ALTER TABLE study_session ADD COLUMN paused_at TIMESTAMP WITH TIME ZONE"))
            db.session.commit()
        if "total_paused_seconds" not in study_columns:
            db.session.execute(text("ALTER TABLE study_session ADD COLUMN total_paused_seconds INTEGER NOT NULL DEFAULT 0"))
            db.session.commit()
        seed_syllabus()

    def topics():
        return Topic.query.filter_by(is_active=True).order_by(Topic.subject, Topic.order_index).all()

    @app.get("/")
    def index():
        return redirect(url_for("dashboard")) if current_user.is_authenticated else redirect(url_for("auth"))

    @app.route("/auth", methods=["GET", "POST"])
    def auth():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        mode = request.args.get("mode", "login")
        if request.method == "POST":
            mode = request.form.get("mode", "login")
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if mode == "register":
                name = request.form.get("name", "").strip()
                if not name or len(password) < 8:
                    flash("Enter your name and a password of at least 8 characters.", "danger")
                elif User.query.filter_by(email=email).first():
                    flash("An account with that email already exists.", "danger")
                else:
                    user = User(name=name, email=email)
                    user.set_password(password)
                    db.session.add(user)
                    db.session.commit()
                    login_user(user)
                    return redirect(url_for("dashboard"))
            else:
                user = User.query.filter_by(email=email).first()
                if user and user.check_password(password):
                    login_user(user)
                    return redirect(url_for("dashboard"))
                flash("Email or password is incorrect.", "danger")
        return render_template(
            "auth.html",
            mode=mode,
            google_login_enabled=bool(app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET")),
        )

    @app.get("/auth/google")
    def google_login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if not (app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET")):
            flash("Google sign-in is not configured yet.", "warning")
            return redirect(url_for("auth"))
        callback_url = url_for("google_callback", _external=True)
        try:
            return oauth.google.authorize_redirect(callback_url)
        except RequestException:
            flash("Could not reach Google sign-in. Check your internet connection and try again.", "danger")
            return redirect(url_for("auth"))

    @app.get("/auth/google/callback")
    def google_callback():
        if not (app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET")):
            flash("Google sign-in is not configured yet.", "warning")
            return redirect(url_for("auth"))
        try:
            token = oauth.google.authorize_access_token()
        except OAuthError:
            flash("Google sign-in was not completed. Please try again.", "danger")
            return redirect(url_for("auth"))
        except RequestException:
            flash("Could not reach Google sign-in. Check your internet connection and try again.", "danger")
            return redirect(url_for("auth"))

        profile = token.get("userinfo") or {}
        email = (profile.get("email") or "").strip().lower()
        if not email or profile.get("email_verified") is not True:
            flash("Google did not provide a verified email address.", "danger")
            return redirect(url_for("auth"))

        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(name=(profile.get("name") or email.split("@", 1)[0])[:80], email=email)
            user.set_password(secrets.token_urlsafe(48))
            db.session.add(user)
            db.session.commit()
        login_user(user)
        return redirect(url_for("dashboard"))

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("auth"))

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            college = request.form.get("college", "").strip()
            course = request.form.get("course", "").strip()
            exam_year_text = request.form.get("exam_year", "").strip()
            goal_text = request.form.get("daily_goal_hours", "3").strip()
            try:
                exam_year = int(exam_year_text) if exam_year_text else None
                daily_goal_hours = float(goal_text)
                if exam_year is not None and not 2026 <= exam_year <= 2040:
                    raise ValueError
                if not 0.5 <= daily_goal_hours <= 16:
                    raise ValueError
            except ValueError:
                flash("Choose an exam year from 2026 to 2040 and a daily goal from 0.5 to 16 hours.", "danger")
                return render_template("profile.html")
            if not name or len(name) > 80 or len(college) > 160 or len(course) > 120:
                flash("Please check your name, college, and course details.", "danger")
                return render_template("profile.html")
            current_user.name = name
            current_user.college = college
            current_user.course = course
            current_user.exam_year = exam_year
            current_user.daily_goal_minutes = round(daily_goal_hours * 60)
            db.session.commit()
            flash("Your profile has been saved.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html")

    @app.get("/dashboard")
    @login_required
    def dashboard():
        all_topics = topics()
        progress = {p.topic_id: p for p in TopicProgress.query.filter_by(user_id=current_user.id).all()}
        completed = sum(bool(progress.get(t.id) and progress[t.id].status == "completed") for t in all_topics)
        today = date.today()
        sessions = StudySession.query.filter_by(user_id=current_user.id).filter(StudySession.ended_at.isnot(None)).all()
        today_minutes = sum(s.duration_minutes for s in sessions if s.started_at.date() == today)
        week_start = today - timedelta(days=today.weekday())
        week_minutes = sum(s.duration_minutes for s in sessions if s.started_at.date() >= week_start)
        pyqs = PYQAttempt.query.filter_by(user_id=current_user.id, practice_type="pyq").order_by(PYQAttempt.attempted_at.desc()).all()
        pyq_questions = sum(p.questions_attempted for p in pyqs)
        pyq_correct = sum(p.correct_count for p in pyqs)
        mocks = MockTest.query.filter_by(user_id=current_user.id).order_by(MockTest.test_date.desc()).all()
        subjects = {}
        for topic in all_topics:
            subjects.setdefault(topic.subject, {"total": 0, "completed": 0})
            subjects[topic.subject]["total"] += 1
            subjects[topic.subject]["completed"] += bool(progress.get(topic.id) and progress[topic.id].status == "completed")
        chart = {"labels": [], "minutes": [], "scores": []}
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            chart["labels"].append(day.strftime("%a"))
            chart["minutes"].append(sum(s.duration_minutes for s in sessions if s.started_at.date() == day))
            test = next((m for m in mocks if m.test_date == day), None)
            chart["scores"].append(round(test.score / test.max_score * 100, 1) if test and test.max_score else None)
        active_session = StudySession.query.filter_by(user_id=current_user.id, ended_at=None).first()
        gate_exam_date = date(2027, 2, 6)
        gate_days_left = (gate_exam_date - datetime.now(ZoneInfo("Asia/Kolkata")).date()).days
        return render_template("dashboard.html", topics=all_topics, subjects=subjects, progress=progress,
                               completed=completed, total_topics=len(all_topics), today_minutes=today_minutes,
                               week_minutes=week_minutes, pyq_count=pyq_questions, accuracy=round(100 * pyq_correct / pyq_questions) if pyq_questions else 0,
                               mocks=mocks, chart=chart, active_session=active_session,
                               active_started_at=(active_session.started_at.astimezone(timezone.utc) if active_session.started_at.tzinfo else active_session.started_at.replace(tzinfo=timezone.utc)).isoformat() if active_session else None,
                               active_paused_at=(active_session.paused_at.astimezone(timezone.utc) if active_session and active_session.paused_at and active_session.paused_at.tzinfo else active_session.paused_at.replace(tzinfo=timezone.utc) if active_session and active_session.paused_at else None),
                               active_paused_seconds=(active_session.total_paused_seconds or 0) if active_session else 0,
                               gate_exam_date=gate_exam_date, gate_days_left=gate_days_left,
                               open_mistakes=Mistake.query.filter_by(user_id=current_user.id, reviewed=False).count(), now=datetime.now)

    @app.get("/syllabus")
    @login_required
    def syllabus():
        all_topics = topics()
        progress = {p.topic_id: p for p in TopicProgress.query.filter_by(user_id=current_user.id).all()}
        grouped = {}
        for topic in all_topics:
            grouped.setdefault(topic.subject, []).append(topic)
        selected_subject = request.args.get("subject")
        if selected_subject and selected_subject not in grouped:
            abort(404)
        selected_topics = {selected_subject: grouped[selected_subject]} if selected_subject else {}
        subject_stats = {subject: {"total": len(items), "done": sum(bool(progress.get(t.id) and progress[t.id].status == "completed") for t in items)} for subject, items in grouped.items()}
        return render_template("syllabus.html", grouped=selected_topics, subjects=list(grouped),
                               selected_subject=selected_subject, subject_stats=subject_stats, progress=progress)

    @app.post("/topics/<int:topic_id>/progress")
    @login_required
    def update_progress(topic_id):
        topic = db.get_or_404(Topic, topic_id)
        status = request.form.get("status")
        if status not in {"not_started", "in_progress", "completed"}:
            abort(400)
        item = TopicProgress.query.filter_by(user_id=current_user.id, topic_id=topic.id).first()
        if item is None:
            item = TopicProgress(user_id=current_user.id, topic_id=topic.id)
            db.session.add(item)
        item.status = status
        item.confidence = min(5, max(1, int(request.form.get("confidence", 1))))
        db.session.commit()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": True, "status": status, "confidence": item.confidence})
        flash("Topic progress saved.", "success")
        return redirect(request.referrer or url_for("syllabus"))

    @app.post("/sessions/start")
    @login_required
    def start_session():
        if StudySession.query.filter_by(user_id=current_user.id, ended_at=None).first():
            flash("Finish your active session before starting another.", "warning")
            return redirect(url_for("dashboard"))
        topic_id = request.form.get("topic_id", type=int) or None
        if topic_id and not db.session.get(Topic, topic_id):
            abort(400)
        db.session.add(StudySession(user_id=current_user.id, topic_id=topic_id))
        db.session.commit()
        flash("Study session started. Keep this page open to see your timer.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/sessions/<int:session_id>/stop")
    @login_required
    def stop_session(session_id):
        item = db.get_or_404(StudySession, session_id)
        if item.user_id != current_user.id:
            abort(404)
        # PostgreSQL returns timezone-aware values, while SQLite may return
        # naive values. New timestamps are stored as aware UTC in both cases.
        started_at = item.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        else:
            started_at = started_at.astimezone(timezone.utc)
        ended_at = datetime.now(timezone.utc)
        item.ended_at = ended_at
        paused_seconds = item.total_paused_seconds or 0
        if item.paused_at:
            paused_at = item.paused_at.replace(tzinfo=timezone.utc) if item.paused_at.tzinfo is None else item.paused_at.astimezone(timezone.utc)
            paused_seconds += max(0, int((ended_at - paused_at).total_seconds()))
        item.total_paused_seconds = paused_seconds
        item.paused_at = None
        item.duration_seconds = max(0, int((ended_at - started_at).total_seconds()) - paused_seconds)
        item.duration_minutes = item.duration_seconds // 60
        item.notes = request.form.get("notes", "")[:500]
        db.session.commit()
        if item.duration_seconds < 60:
            duration_label = f"{item.duration_seconds} sec"
        else:
            duration_label = f"{item.duration_minutes // 60} hr {item.duration_minutes % 60} min"
        flash(f"Session saved: {duration_label}.", "success")
        return redirect(url_for("history"))

    @app.post("/sessions/<int:session_id>/toggle-pause")
    @login_required
    def toggle_session_pause(session_id):
        item = db.get_or_404(StudySession, session_id)
        if item.user_id != current_user.id or item.ended_at is not None:
            abort(404)
        if item.paused_at:
            paused_at = item.paused_at.replace(tzinfo=timezone.utc) if item.paused_at.tzinfo is None else item.paused_at.astimezone(timezone.utc)
            item.total_paused_seconds = (item.total_paused_seconds or 0) + max(0, int((datetime.now(timezone.utc) - paused_at).total_seconds()))
            item.paused_at = None
            flash("Study timer resumed.", "success")
        else:
            item.paused_at = datetime.now(timezone.utc)
            flash("Study timer paused.", "success")
        db.session.commit()
        return redirect(url_for("dashboard"))

    @app.post("/sessions/<int:session_id>/delete")
    @login_required
    def delete_session(session_id):
        item = db.get_or_404(StudySession, session_id)
        if item.user_id != current_user.id:
            abort(404)
        db.session.delete(item)
        db.session.commit()
        flash("Study session deleted.", "success")
        return redirect(url_for("history"))

    @app.get("/history")
    @login_required
    def history():
        all_sessions = StudySession.query.filter_by(user_id=current_user.id).filter(StudySession.ended_at.isnot(None)).order_by(StudySession.started_at.desc()).all()
        items = all_sessions[:100]
        today = date.today()
        selected_value = request.args.get("date", "")
        month_value = request.args.get("month", "")
        try:
            selected_date = date.fromisoformat(selected_value) if selected_value else (None if month_value else today)
        except ValueError:
            selected_date = today
        try:
            month_start = datetime.strptime(month_value, "%Y-%m").date().replace(day=1) if month_value else (selected_date or today).replace(day=1)
        except ValueError:
            month_start = (selected_date or today).replace(day=1)
        calendar = month_calendar.Calendar(firstweekday=6)
        daily_seconds = {}
        for session in all_sessions:
            session_day = session.started_at.date()
            seconds = session.duration_seconds or session.duration_minutes * 60
            daily_seconds[session_day] = daily_seconds.get(session_day, 0) + seconds
        weeks = [[{"day": day, "in_month": day.month == month_start.month, "seconds": daily_seconds.get(day, 0), "is_today": day == today, "is_selected": day == selected_date} for day in week] for week in calendar.monthdatescalendar(month_start.year, month_start.month)]
        selected_sessions = [session for session in all_sessions if selected_date and session.started_at.date() == selected_date]
        previous_month = (month_start - timedelta(days=1)).replace(day=1).strftime("%Y-%m")
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
        return render_template("history.html", sessions=items, topics=topics(), weeks=weeks,
                               month_start=month_start, previous_month=previous_month, next_month=next_month,
                               selected_date=selected_date, selected_sessions=selected_sessions,
                               selected_seconds=daily_seconds.get(selected_date, 0) if selected_date else 0)


    @app.route("/pyqs", methods=["GET", "POST"])
    @login_required
    def pyqs_page():
        practice_type = request.values.get("type", "").lower()
        if practice_type not in {"", "pyq", "dpp"}:
            abort(400)
        if request.method == "POST":
            if practice_type not in {"pyq", "dpp"}:
                abort(400)
            topic = db.session.get(Topic, request.form.get("topic_id", type=int))
            attempted = request.form.get("questions_attempted", type=int)
            correct_count = request.form.get("correct_count", type=int)
            year = request.form.get("year", type=int)
            if not topic or not attempted or attempted < 1 or correct_count is None or correct_count < 0 or correct_count > attempted or not year:
                flash("Enter a topic, year, and valid attempted/correct question totals.", "danger")
                return redirect(url_for("pyqs_page"))
            db.session.add(PYQAttempt(user_id=current_user.id, topic=topic, year=year,
                                      question_ref=request.form.get("source_label", "").strip()[:120],
                                      questions_attempted=attempted, correct_count=correct_count,
                                      correct=correct_count == attempted,
                                      review_refs=request.form.get("review_refs", "").strip()[:4000],
                                      practice_type=practice_type))
            db.session.commit()
            flash(f"{practice_type.upper()} practice set recorded.", "success")
            return redirect(url_for("pyqs_page", type=practice_type))
        items = PYQAttempt.query.filter_by(user_id=current_user.id, practice_type=practice_type).order_by(PYQAttempt.attempted_at.desc()).limit(100).all()
        return render_template("pyqs.html", attempts=items, topics=topics(), practice_type=practice_type)

    @app.post("/pyqs/<int:attempt_id>/delete")
    @login_required
    def delete_pyq(attempt_id):
        item = db.get_or_404(PYQAttempt, attempt_id)
        if item.user_id != current_user.id:
            abort(404)
        practice_type = item.practice_type
        db.session.delete(item)
        db.session.commit()
        flash(f"{practice_type.upper()} practice set deleted.", "success")
        return redirect(url_for("pyqs_page", type=practice_type))

    @app.route("/mocks", methods=["GET", "POST"])
    @login_required
    def mocks_page():
        if request.method == "POST":
            maximum, score = request.form.get("max_score", type=float), request.form.get("score", type=float)
            if not maximum or maximum <= 0 or score < 0 or score > maximum:
                flash("Enter a valid score within the test's maximum marks.", "danger")
            else:
                db.session.add(MockTest(user_id=current_user.id, title=request.form.get("title", "").strip()[:160], test_date=date.fromisoformat(request.form["test_date"]), score=score, max_score=maximum, notes=request.form.get("notes", "")[:500]))
                db.session.commit()
                flash("Mock test saved.", "success")
                return redirect(url_for("mocks_page"))
        items = MockTest.query.filter_by(user_id=current_user.id).order_by(MockTest.test_date.desc()).all()
        return render_template("mocks.html", mocks=items)

    @app.route("/mistakes", methods=["GET", "POST"])
    @login_required
    def mistakes_page():
        if request.method == "POST":
            question = request.form.get("question", "").strip()
            why_wrong = request.form.get("why_wrong", "").strip()
            if not question or not why_wrong:
                flash("Add the question or concept and what went wrong.", "danger")
                return redirect(url_for("mistakes_page"))
            uploaded = []
            image_files = [file for file in request.files.getlist("images") if file and file.filename]
            if sum(upload_size_bytes(file) for file in image_files) > MAX_UPLOAD_BYTES:
                flash("Selected images exceed the 100 MB total upload limit.", "danger")
                return redirect(url_for("mistakes_page"))
            try:
                for image_file in image_files:
                    uploaded.append(save_upload(image_file, {".png", ".jpg", ".jpeg", ".webp", ".gif"}, "mistakes"))
            except ValueError as exc:
                for key, _ in uploaded:
                    delete_upload(key)
                flash(str(exc), "danger")
                return redirect(url_for("mistakes_page"))
            item = Mistake(user_id=current_user.id, topic_id=request.form.get("topic_id", type=int) or None, question=question, why_wrong=why_wrong, takeaway=request.form.get("takeaway", "").strip())
            db.session.add(item)
            db.session.flush()
            for key, filename in uploaded:
                db.session.add(MistakeImage(mistake_id=item.id, original_filename=filename, storage_key=key))
            db.session.commit()
            flash("Mistake added to your review book.", "success")
            return redirect(url_for("mistakes_page"))
        items = Mistake.query.filter_by(user_id=current_user.id).order_by(Mistake.reviewed, Mistake.created_at.desc()).all()
        return render_template("mistakes.html", mistakes=items, topics=topics())

    @app.get("/mistake-images/<int:image_id>")
    @login_required
    def mistake_image(image_id):
        item = db.get_or_404(MistakeImage, image_id)
        if item.mistake.user_id != current_user.id:
            abort(404)
        if app.config["S3_BUCKET"]:
            return redirect(upload_url(item.storage_key))
        path = local_path(item.storage_key)
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=False)

    @app.post("/mistakes/<int:mistake_id>/reviewed")
    @login_required
    def review_mistake(mistake_id):
        item = db.get_or_404(Mistake, mistake_id)
        if item.user_id != current_user.id:
            abort(404)
        item.reviewed = not item.reviewed
        db.session.commit()
        return redirect(url_for("mistakes_page"))

    @app.route("/resources", methods=["GET", "POST"])
    def resources_page():
        active_topics = topics()
        available_subjects = list(dict.fromkeys(topic.subject for topic in active_topics))
        if request.method == "POST":
            if not current_user.is_authenticated:
                flash("Sign in to share a resource.", "info")
                return redirect(url_for("auth", mode="login"))
            file = request.files.get("file")
            if not file or not file.filename:
                flash("Choose a PDF or document to share.", "danger")
            else:
                resource_type = request.form.get("resource_type", "notes")
                if resource_type not in {"notes", "formula", "book"}:
                    abort(400)
                subject_name = request.form.get("subject_name", "").strip()
                if resource_type != "book" and subject_name not in available_subjects:
                    flash("Choose a subject folder for this resource.", "danger")
                    return redirect(url_for("resources_page", collection="subjects"))
                if resource_type == "book":
                    subject_name = None
                try:
                    allowed = {".pdf"} if resource_type == "book" else {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
                    key, filename = save_upload(file, allowed_extensions=allowed, category="books" if resource_type == "book" else "resources")
                except ValueError as exc:
                    flash(str(exc), "danger")
                    key = filename = None
                if key:
                    db.session.add(Resource(user_id=current_user.id, subject_name=subject_name, title=request.form.get("title", "").strip()[:160] or filename, description=request.form.get("description", "")[:500], original_filename=filename, storage_key=key, resource_type=resource_type))
                    db.session.commit()
                    flash("Resource uploaded and shared with the community.", "success")
                    return redirect(url_for("resources_page", collection="books") if resource_type == "book" else url_for("resources_page"))
        items = Resource.query.order_by(Resource.created_at.desc()).all()
        links = {item.id: upload_url(item.storage_key) for item in items}
        books = [item for item in items if item.resource_type == "book"]
        formulas = [item for item in items if item.resource_type == "formula"]
        notes = [item for item in items if item.resource_type != "book"]
        def subject_for(item):
            return item.subject_name or (item.topic.subject if item.topic else "General")
        subjects = list(dict.fromkeys(available_subjects + [subject_for(item) for item in notes]))
        counts = {subject: sum(subject_for(item) == subject for item in notes) for subject in subjects}
        selected_subject = request.args.get("subject")
        if selected_subject:
            if selected_subject not in subjects:
                abort(404)
            view = "subject"
            selected_resources = [item for item in notes if subject_for(item) == selected_subject]
        elif request.args.get("collection") == "books":
            view, selected_resources = "books", books
        elif request.args.get("collection") == "formulas":
            view, selected_resources = "formulas", formulas
        elif request.args.get("collection") == "subjects":
            view, selected_resources = "subjects", []
        else:
            view, selected_resources = "home", []
        return render_template("resources.html", view=view, books=books, formulas=formulas, subjects=subjects, counts=counts,
                               selected_subject=selected_subject, resources=selected_resources,
                               book_count=len(books), formula_count=len(formulas), subject_count=len(subjects), links=links, upload_subjects=available_subjects)

    @app.get("/resources/<path:key>")
    def serve_resource(key):
        if app.config["S3_BUCKET"]:
            return redirect(upload_url(key))
        path = local_path(key)
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=False)

    @app.post("/resources/<int:resource_id>/delete")
    @login_required
    def delete_resource(resource_id):
        item = db.get_or_404(Resource, resource_id)
        if item.user_id != current_user.id:
            abort(404)
        delete_upload(item.storage_key)
        db.session.delete(item)
        db.session.commit()
        flash("Your resource has been deleted.", "success")
        return redirect(url_for("resources_page"))

    @app.get("/api/analytics")
    @login_required
    def analytics_api():
        days = 14
        cutoff = date.today() - timedelta(days=days - 1)
        sessions = StudySession.query.filter_by(user_id=current_user.id).filter(StudySession.started_at >= datetime.combine(cutoff, datetime.min.time()), StudySession.ended_at.isnot(None)).all()
        return jsonify({"labels": [(cutoff + timedelta(days=i)).isoformat() for i in range(days)], "minutes": [sum(s.duration_minutes for s in sessions if s.started_at.date() == cutoff + timedelta(days=i)) for i in range(days)]})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
