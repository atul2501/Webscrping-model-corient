import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    # threaded=True matters here: the UI fires an instant catalog lookup
    # (/api/model-options) and a live cross-source search (/api/search) at
    # the same time, and Werkzeug's dev server is single-threaded by
    # default - without this, the fast request queues up behind the slow
    # one instead of actually returning instantly. gunicorn (used in
    # Docker/Render) doesn't have this problem, since it runs multiple
    # worker processes already.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        threaded=True,
    )
