import subprocess

from flask import Blueprint, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from utils.positioning import estimate_room_from_sensors
from utils.ml_model import get_sensor_ids, predict_room, predict_zone
from utils.ml_model import load_models


sensors_bp = Blueprint("sensors", __name__)


def build_sensor_room_map(db):
    rooms = db.rooms.find({}, {"_id": 1, "beacons": 1})
    mapping = {}

    for r in rooms:
        room_id = r["_id"]
        for b in r.get("beacons", []):
            sensor_id = b.get("id")
            if sensor_id:
                mapping[sensor_id] = room_id

    return mapping


def build_feature_vector_from_sensors(sensors):
    sensor_ids = get_sensor_ids()
    sensor_map = {s["sensor_id"]: s["rssi"] for s in sensors}
    return [sensor_map.get(sid, -100) for sid in sensor_ids]


@sensors_bp.route("/update_position", methods=["POST"])
def update_position_from_sensors():
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    sensors = data.get("sensors")
    timestamp = data.get("timestamp", now_iso())

    if not user_id or not sensors:
        return jsonify({"error": "user_id and sensors are required"}), 400

    # Fallback map
    sensor_room_map = build_sensor_room_map(db)

    # Vector para ML
    feature_vector = build_feature_vector_from_sensors(sensors)

    # Intentar ML
    try:
        detected_room = predict_room(feature_vector)
        detected_zone = predict_zone(feature_vector)
    except Exception:
        detected_room = estimate_room_from_sensors(
            sensors=sensors,
            sensor_room_map=sensor_room_map,
            min_sensors=1
        )
        detected_zone = None

    if not detected_room:
        return jsonify({"error": "could not estimate room"}), 400

    # Reusar lógica de position
    from blueprints.position import apply_room_update

    result, status_code = apply_room_update(
        db=db,
        user_id=user_id,
        detected_room=detected_room,
        confidence=None,
        timestamp=timestamp
    )

    # Añadir info de zona si existe
    if detected_zone:
        zone_doc = db.room_zones.find_one(
            {"room_id": detected_room, "zone_id": detected_zone},
            {"_id": 0}
        )
        if zone_doc:
            result["zone"] = detected_zone
            result["zone_info"] = zone_doc

    return jsonify(result), status_code




@sensors_bp.route("/training_data", methods=["POST"])
def save_training_data():
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    room_id = data.get("room_id")
    zone_id = data.get("zone_id")
    sensors = data.get("sensors")
    timestamp = data.get("timestamp", now_iso())

    if not user_id or not room_id or not sensors:
        return jsonify({"error": "user_id, room_id y sensors son obligatorios"}), 400

    doc = {
        "user_id": user_id,
        "room_id": room_id,
        "zone_id": zone_id,
        "timestamp": timestamp,
        "sensors": sensors
    }

    db.training_sensor_data.insert_one(doc)
    return jsonify({"status": "ok"}), 200

# Para resetear el entrenamiento desde la aplicación
@sensors_bp.route("/ml/reset_training", methods=["POST"])
def reset_training():
    db = get_db()
    db.training_sensor_data.delete_many({})
    return jsonify({"status": "reset_ok"}), 200

# Para entrenar desde la aplicación
@sensors_bp.route("/ml/train", methods=["POST"])
def train_models_api():
    try:
        subprocess.run(["python", "scripts/train_models.py"], check=True)
        return jsonify({"status": "training_completed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Para recargar los modelos sin necesidad de reiniciar la api
@sensors_bp.route("/ml/reload_models", methods=["POST"])
def reload_models():
    try:
        load_models()
        return jsonify({"status": "models_reloaded"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Muestras por habitación y zona
@sensors_bp.route("/ml/status", methods=["GET"])
def training_status():
    db = get_db()
    pipeline = [
        {"$group": {
            "_id": {"room": "$room_id", "zone": "$zone_id"},
            "count": {"$sum": 1}
        }}
    ]
    data = list(db.training_sensor_data.aggregate(pipeline))
    return jsonify(data), 200

