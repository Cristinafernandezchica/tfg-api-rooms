import joblib
import os

_room_model = None
_sensor_ids = None

def load_models():
    global _room_model, _sensor_ids

    base_path = os.getenv("ML_MODELS_PATH", ".")

    room_model_path = os.path.join(base_path, "scripts/room_model.pkl")
    sensor_ids_path = os.path.join(base_path, "scripts/sensor_ids.pkl")

    if not os.path.exists(room_model_path):
        print("⚠️ No se encontró room_model.pkl — usando fallback.")
        return

    _room_model = joblib.load(room_model_path)
    _sensor_ids = joblib.load(sensor_ids_path)

    print("Modelos cargados.")

def get_sensor_ids():
    return _sensor_ids

def predict_room(feature_vector):
    if _room_model is None:
        raise RuntimeError("Modelo de habitación no cargado")
    return _room_model.predict([feature_vector])[0]

def predict_zone(feature_vector, room):
    model_path = f"scripts/zone_model_{room}.pkl"
    if not os.path.exists(model_path):
        return None
    model = joblib.load(model_path)
    return model.predict([feature_vector])[0]
