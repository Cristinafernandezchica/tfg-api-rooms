from flask import Flask
from config import Config
from db.mongo import close_db, get_db
from blueprints.position import position_bp, start_cleanup_thread
from blueprints.rooms import rooms_bp
from blueprints.routes import routes_bp
from blueprints.sensors import sensors_bp
from utils.ml_model import load_models


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(position_bp, url_prefix="/position")
    app.register_blueprint(rooms_bp, url_prefix="/rooms")
    app.register_blueprint(routes_bp, url_prefix="/routes")
    app.register_blueprint(sensors_bp, url_prefix="/sensors")

    app.teardown_appcontext(close_db)
    load_models()

    with app.app_context():
        db = get_db()
        start_cleanup_thread(db)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
