import requests
from flask import current_app

# Obtener los umbrales de notificación configurados por el usuario
def get_user_thresholds(user_id: str) -> dict:
    base_url = current_app.config["USERS_API_BASE_URL"]
    # Endpoint interno de la API de usuarios
    # GET /internal/users/<user_id>/thresholds
    resp = requests.get(f"{base_url}/internal/users/{user_id}/thresholds", timeout=3)
    if resp.status_code != 200:
        return {}
    return resp.json() or {}
