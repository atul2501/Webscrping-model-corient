from flask import Blueprint, jsonify, render_template

from app.extensions import db
from app.scrapers.registry import available_sources

views_bp = Blueprint("views", __name__)


@views_bp.get("/")
def index():
    return render_template("index.html", sources=available_sources())


@views_bp.get("/health")
def health():
    db_status = "ok"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"
    return jsonify({"status": "ok", "db": db_status})
