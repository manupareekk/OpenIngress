import os

from flask import Flask
from flask_cors import CORS

from .api.ingress import ingress_bp, internal_bp
from .config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    if hasattr(app, "json") and hasattr(app.json, "ensure_ascii"):
        app.json.ensure_ascii = False
    CORS(
        app,
        resources={r"/api/*": {"origins": Config.CORS_ORIGINS or ["http://localhost:5175"]}},
        supports_credentials=True,
    )
    app.register_blueprint(ingress_bp, url_prefix="/api/ingress")
    app.register_blueprint(internal_bp, url_prefix="/internal")
    return app


def main() -> None:
    app = create_app()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5055"))
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1", threaded=True)
