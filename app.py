from flask import Flask
from config import Config
from db.mongo import close_db
from blueprints.position import position_bp
from blueprints.rooms import rooms_bp
from blueprints.routes import routes_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Registrar blueprints
    app.register_blueprint(position_bp, url_prefix="/position")
    app.register_blueprint(rooms_bp, url_prefix="/rooms")
    app.register_blueprint(routes_bp, url_prefix="/routes")

    # Cerrar Mongo al terminar el contexto
    app.teardown_appcontext(close_db)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=True)
