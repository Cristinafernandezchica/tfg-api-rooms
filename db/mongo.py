from flask import current_app, g
from pymongo import MongoClient

def get_db():
    """
    Devuelve la base de datos MongoDB asociada a la app.
    Usa g para guardar la conexión por request.
    """
    if "mongo_db" not in g:
        mongo_uri = current_app.config["MONGO_URI"]
        client = MongoClient(mongo_uri)
        g.mongo_client = client
        # Si en la URI no viene el nombre de la DB, usa la "default"
        g.mongo_db = client.get_default_database()
    return g.mongo_db

def close_db(e=None):
    """
    Cierra la conexión a MongoDB al final del request/app context.
    """
    client = g.pop("mongo_client", None)
    if client is not None:
        client.close()
