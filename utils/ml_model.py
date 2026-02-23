import joblib
import os

_room_model = None
_zone_model = None
_sensor_ids = None


def load_models():
    """
    Carga los modelos entrenados desde disco.
    Se llama una vez al iniciar la API.
    """
    global _room_model, _zone_model, _sensor_ids

    base_path = os.getenv("ML_MODELS_PATH", ".")

    # Modelo de habitación
    room_model_path = os.path.join(base_path, "scripts/room_model.pkl")
    sensor_ids_path = os.path.join(base_path, "scripts/sensor_ids.pkl")

    if not os.path.exists(room_model_path):
        print("⚠️ No se encontró room_model.pkl — usando fallback clásico.")
        return

    _room_model = joblib.load(room_model_path)
    _sensor_ids = joblib.load(sensor_ids_path)

    # Modelo de zonas (opcional)
    zone_model_path = os.path.join(base_path, "scripts/zone_model.pkl")
    if os.path.exists(zone_model_path):
        _zone_model = joblib.load(zone_model_path)
        print("Modelo de zonas cargado.")
    else:
        print("⚠️ No se encontró zone_model.pkl — zonas desactivadas.")


def get_sensor_ids():
    return _sensor_ids


def predict_room(feature_vector):
    if _room_model is None:
        raise RuntimeError("Modelo de habitación no cargado")
    return _room_model.predict([feature_vector])[0]


def predict_zone(feature_vector):
    if _zone_model is None:
        return None
    return _zone_model.predict([feature_vector])[0]
