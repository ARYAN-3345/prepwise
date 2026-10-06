from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow():
    # DateTime(timezone=True) columns must receive aware UTC timestamps so
    # PostgreSQL does not interpret them in the server's local timezone.
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    exam_year = db.Column(db.Integer)
    college = db.Column(db.String(160), default="", nullable=False)
    course = db.Column(db.String(120), default="", nullable=False)
    daily_goal_minutes = db.Column(db.Integer, default=180, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    sessions = db.relationship("StudySession", backref="user", cascade="all, delete-orphan")
    topic_progress = db.relationship("TopicProgress", backref="user", cascade="all, delete-orphan")
    pyqs = db.relationship("PYQAttempt", backref="user", cascade="all, delete-orphan")
    mocks = db.relationship("MockTest", backref="user", cascade="all, delete-orphan")
    mistakes = db.relationship("Mistake", backref="user", cascade="all, delete-orphan")
    resources = db.relationship("Resource", backref="uploader", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    progress = db.relationship("TopicProgress", backref="topic", cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint("subject", "name"),)


class TopicProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id"), nullable=False)
    status = db.Column(db.String(20), default="not_started", nullable=False)
    confidence = db.Column(db.Integer, default=1, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "topic_id"),)


class StudySession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id"))
    topic = db.relationship("Topic")
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at = db.Column(db.DateTime(timezone=True))
    duration_minutes = db.Column(db.Integer, default=0, nullable=False)
    duration_seconds = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.String(500), default="")


class PYQAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id"), nullable=False)
    topic = db.relationship("Topic")
    year = db.Column(db.Integer, nullable=False)
    question_ref = db.Column(db.String(120), default="")
    correct = db.Column(db.Boolean, nullable=False, default=False)
    questions_attempted = db.Column(db.Integer, nullable=False, default=1)
    correct_count = db.Column(db.Integer, nullable=False, default=0)
    review_refs = db.Column(db.Text, default="", nullable=False)
    practice_type = db.Column(db.String(10), nullable=False, default="pyq", index=True)
    attempted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class MockTest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    test_date = db.Column(db.Date, nullable=False)
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False, default=100)
    notes = db.Column(db.String(500), default="")


class Mistake(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id"))
    topic = db.relationship("Topic")
    question = db.Column(db.Text, nullable=False)
    why_wrong = db.Column(db.Text, nullable=False)
    takeaway = db.Column(db.Text, default="")
    reviewed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    images = db.relationship("MistakeImage", backref="mistake", cascade="all, delete-orphan")


class MistakeImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mistake_id = db.Column(db.Integer, db.ForeignKey("mistake.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id"))
    topic = db.relationship("Topic")
    subject_name = db.Column(db.String(120), index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(500), default="")
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(500), nullable=False)
    resource_type = db.Column(db.String(20), nullable=False, default="notes", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
