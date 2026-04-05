import subprocess
import sys
from collections import deque, defaultdict

from flask import Blueprint, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from utils.positioning import estimate_room_from_sensors
from utils.ml_model import get_sensor_ids, predict_room, predict_zone
from utils.ml_model import load_models

sensors_bp = Blueprint("sensors", __name__)

ROOM_HISTORY_SIZE = 3
ZONE_HISTORY_SIZE = 3
user_room_history = defaultdict(lambda: deque(maxlen=ROOM_HISTORY_SIZE))
user_zone_history = defaultdict(lambda: deque(maxlen=ZONE_HISTORY_SIZE))


def build_sensor_room_map(db):
    rooms = db.rooms.find({}, {"_id": 1, "beacons": 1})
    mapping = {}
    for r in rooms:
        room_id = r["_id"]
        for b in r.get("beacons", []):
            sid = b.get("id")
            if sid:
                mapping[sid] = room_id
    return mapping


def normalize_rssi(rssi):
    if rssi is None:
        return -100
    return max(-100, min(-40, int(rssi)))


def build_feature_vector_from_sensors(sensors):
    sensor_ids = get_sensor_ids()
    sensor_map = {
        s["sensor_id"]: normalize_rssi(s["rssi"])
        for s in sensors
    }
    return [sensor_map.get(sid, -100) for sid in sensor_ids]


def smooth_label(history, new_label):
    """
    Suavizado que respeta la nueva detección si es fuerte.
    """
    if new_label is None:
        return history[-1] if history else None
    
    if not history:
        history.append(new_label)
        return new_label
    
    last_room = history[-1]
    
    if new_label != last_room:
        history.clear()
        history.append(new_label)
        return new_label
    
    history.append(new_label)
    
    if len(history) >= ROOM_HISTORY_SIZE:
        counts = {}
        for v in history:
            counts[v] = counts.get(v, 0) + 1
        return max(counts, key=counts.get)
    
    return new_label


def heuristic_confidence(sensors):
    if not sensors:
        return 0.0
    n = len(sensors)
    best_rssi = max(s["rssi"] for s in sensors)
    n_factor = min(0.2 * n, 0.8)
    rssi_factor = max(0.0, min(1.0, (best_rssi + 100) / 60))
    return round(0.5 * n_factor + 0.5 * rssi_factor, 2)


def heuristic_room_override(sensors):
    sensors_sorted = sorted(sensors, key=lambda s: s["rssi"], reverse=True)

    sid = sensors_sorted[0]["sensor_id"]
    rssi = sensors_sorted[0]["rssi"]

    if sid == "BEACON_SALON" and rssi > -65:
        print(f"   [Heurística] Beacon SALON fuerte ({rssi}) -> SALON")
        return "SALON"

    if sid == "BEACON_COCINA" and rssi > -73:
        print(f"   [Heurística] Beacon COCINA fuerte ({rssi}) -> COCINA")
        return "COCINA"

    if sid == "BEACON_HAB1" and rssi > -70:
        print(f"   [Heurística] Beacon HAB1 fuerte ({rssi}) -> HAB1")
        return "HAB1"

    if sid == "BEACON_HAB2" and rssi > -70:
        print(f"   [Heurística] Beacon HAB2 fuerte ({rssi}) -> HAB2")
        return "HAB2"

    if sid == "BEACON_HAB3" and rssi > -70:
        print(f"   [Heurística] Beacon HAB3 fuerte ({rssi}) -> HAB3")
        return "HAB3"

    if sid == "BEACON_BANO2" and rssi > -75:
        print(f"   [Heurística] Beacon BAN2 fuerte ({rssi}) -> BAN2")
        return "BAN2"

    salon = [s for s in sensors if s["sensor_id"] == "BEACON_SALON"]
    cocina = [s for s in sensors if s["sensor_id"] == "BEACON_COCINA"]
    hab1 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB1"]
    hab2 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB2"]
    hab3 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB3"]
    ban2 = [s for s in sensors if s["sensor_id"] == "BEACON_BANO2"]
    
    avg_salon = sum(s["rssi"] for s in salon) / len(salon) if salon else -100
    avg_cocina = sum(s["rssi"] for s in cocina) / len(cocina) if cocina else -100
    avg_hab1 = hab1[0]["rssi"] if hab1 else -100
    avg_hab2 = hab2[0]["rssi"] if hab2 else -100
    avg_hab3 = hab3[0]["rssi"] if hab3 else -100
    avg_ban2 = ban2[0]["rssi"] if ban2 else -100
    
    print(f"   [Heurística] Promedios - SALÓN: {avg_salon:.1f}, COCINA: {avg_cocina:.1f}, HAB1: {avg_hab1:.1f}, BAN2: {avg_ban2:.1f}")
    
    if salon and avg_salon > -85:
        otras_habitaciones = 0
        if avg_cocina > -80: otras_habitaciones += 1
        if avg_hab1 > -80: otras_habitaciones += 1
        if avg_hab2 > -80: otras_habitaciones += 1
        if avg_hab3 > -80: otras_habitaciones += 1
        if avg_ban2 > -80: otras_habitaciones += 1
        
        if otras_habitaciones <= 1:
            print(f"   [Heurística] Patrón ENTRADA A: solo SALÓN detectable")
            return "ENTRADA"
    
    if salon and cocina:
        diferencia = abs(avg_salon - avg_cocina)
        if diferencia < 10 and avg_salon > -85 and avg_cocina > -85:
            print(f"   [Heurística] Patrón ENTRADA B: SALÓN y COCINA cercanos")
            return "ENTRADA"
    
    if salon and -80 < avg_salon < -65:
        if avg_cocina < -75 or avg_cocina == -100:
            print(f"   [Heurística] Patrón ENTRADA E: SALÓN en rango ENTRADA")
            return "ENTRADA"
    
    print(f"   [Heurística] Ningún patrón coincidió")
    return None


@sensors_bp.route("/update_position", methods=["POST"])
def update_position_from_sensors():
    """Endpoint para detección de posición desde sensores - CON sistema de confirmación"""
    db = get_db()
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    sensors = data.get("sensors") or []
    timestamp = data.get("timestamp", now_iso())
    
    if not user_id or not sensors:
        return jsonify({"error": "user_id and sensors are required"}), 400
    
    # Filtrar señales débiles
    sensors = [s for s in sensors if s.get("rssi", -100) > -85]
    
    if len(sensors) < 2:
        return jsonify({
            "room": None,
            "zone": None,
            "confidence": 0.0,
            "status": "insufficient_beacons"
        }), 200
    
    # Detectar habitación
    sensor_room_map = build_sensor_room_map(db)
    feature_vector = build_feature_vector_from_sensors(sensors)
    
    detected_room = None
    
    # Intentar heurística primero
    override = heuristic_room_override(sensors)
    if override:
        detected_room = override
        print(f"✓ Heurística: {detected_room}")
    else:
        # Usar ML
        try:
            ml_prediction = predict_room(feature_vector)
            if ml_prediction in ["ENTRADA", "SALON", "COCINA", "HAB1", "HAB2", "HAB3", "BAN2"]:
                detected_room = ml_prediction
                print(f"✓ ML predijo: {detected_room}")
        except Exception as e:
            print(f"Error ML: {e}")
        
        # Fallback si no hay detección
        if not detected_room:
            detected_room = estimate_room_from_sensors(
                sensors=sensors,
                sensor_room_map=sensor_room_map,
                last_room=None
            )
    
    if not detected_room:
        return jsonify({"error": "could_not_detect_room"}), 400
    
    confidence = heuristic_confidence(sensors)
    
    # IMPORTANTE: Importar las funciones de position.py DENTRO de la función
    # para evitar importaciones circulares
    from blueprints.position import add_pending_detection, get_confirmed_room, clear_pending_detections, pending_detections, apply_room_update
    
    # Añadir detección pendiente
    add_pending_detection(user_id, detected_room, confidence, timestamp)
    
    # Verificar si tenemos confirmación (3 detecciones iguales)
    confirmed_room = get_confirmed_room(user_id)
    
    if not confirmed_room:
        pending_count = len(pending_detections.get(user_id, []))
        return jsonify({
            "status": "pending",
            "message": f"Confirmando posición ({pending_count}/3)",
            "room": detected_room,
            "pending_count": pending_count,
            "zone": None,
            "confidence": confidence
        }), 200
    
    # Posición confirmada, actualizar estado
    result, status = apply_room_update(
        db=db,
        user_id=user_id,
        detected_room=confirmed_room,
        confidence=confidence,
        timestamp=timestamp
    )
    
    # Limpiar detecciones pendientes
    clear_pending_detections(user_id)
    
    # Añadir zona si existe
    if result.get("room") or confirmed_room:
        room_for_zone = result.get("room", confirmed_room)
        zones_for_room = list(db.room_zones.find({"room_id": room_for_zone}))
        if len(zones_for_room) == 1:
            result["zone"] = zones_for_room[0]["zone_id"]
            result["zone_info"] = zones_for_room[0]
    
    result["confidence"] = confidence
    result["status"] = "confirmed"
    
    return jsonify(result), status


@sensors_bp.route("/detect_once", methods=["POST"])
def detect_once():
    """
    Endpoint para detección INMEDIATA sin sistema de confirmación.
    Útil para pruebas y para el botón "Probar posicionamiento".
    """
    db = get_db()
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    sensors = data.get("sensors") or []
    
    if not user_id or not sensors:
        return jsonify({"error": "user_id and sensors are required"}), 400
    
    # Filtrar señales débiles
    sensors = [s for s in sensors if s.get("rssi", -100) > -85]
    
    if len(sensors) < 2:
        return jsonify({
            "room": None,
            "zone": None,
            "confidence": 0.0,
            "error": "not_enough_beacons"
        }), 200
    
    # Detectar habitación
    sensor_room_map = build_sensor_room_map(db)
    feature_vector = build_feature_vector_from_sensors(sensors)
    
    detected_room = None
    
    # Heurística
    override = heuristic_room_override(sensors)
    if override:
        detected_room = override
        print(f"[detect_once] Heurística: {detected_room}")
    else:
        try:
            ml_prediction = predict_room(feature_vector)
            if ml_prediction in ["ENTRADA", "SALON", "COCINA", "HAB1", "HAB2", "HAB3", "BAN2"]:
                detected_room = ml_prediction
                print(f"[detect_once] ML predijo: {detected_room}")
        except Exception as e:
            print(f"[detect_once] Error ML: {e}")
        
        if not detected_room:
            detected_room = estimate_room_from_sensors(
                sensors=sensors,
                sensor_room_map=sensor_room_map,
                last_room=None
            )
    
    if not detected_room:
        return jsonify({"error": "could_not_detect_room"}), 400
    
    # Detectar zona
    zone = None
    zones_for_room = list(db.room_zones.find({"room_id": detected_room}))
    if len(zones_for_room) == 1:
        zone = zones_for_room[0]["zone_id"]
    elif len(zones_for_room) > 1:
        try:
            detected_zone = predict_zone(feature_vector, detected_room)
            if detected_zone:
                zone = detected_zone
        except Exception as e:
            print(f"[detect_once] Error en predict_zone: {e}")
    
    return jsonify({
        "room": detected_room,
        "zone": zone,
        "confidence": heuristic_confidence(sensors),
        "sensors_count": len(sensors)
    }), 200


@sensors_bp.route("/training_data", methods=["POST"])
def save_training_data():
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    room_id = data.get("room_id")
    zone_id = data.get("zone_id")
    sensors = data.get("sensors") or []
    timestamp = data.get("timestamp", now_iso())

    if not user_id or not room_id or not sensors:
        return jsonify({"error": "user_id, room_id y sensors son obligatorios"}), 400

    sensors = [s for s in sensors if s.get("rssi", -100) > -95]
    if len(sensors) < 2:
        return jsonify({"error": "muestra descartada por tener menos de 2 beacons útiles"}), 400

    doc = {
        "user_id": user_id,
        "room_id": room_id,
        "zone_id": zone_id,
        "timestamp": timestamp,
        "sensors": sensors
    }

    db.training_sensor_data.insert_one(doc)
    return jsonify({"status": "ok"}), 200


@sensors_bp.route("/ml/reset_training", methods=["POST"])
def reset_training():
    db = get_db()
    db.training_sensor_data.delete_many({})
    return jsonify({"status": "reset_ok"}), 200


@sensors_bp.route("/ml/train", methods=["POST"])
def train_models_api():
    try:
        subprocess.run([sys.executable, "scripts/train_models.py"], check=True)
        return jsonify({"status": "training_completed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sensors_bp.route("/ml/reload_models", methods=["POST"])
def reload_models():
    try:
        load_models()
        return jsonify({"status": "models_reloaded"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@sensors_bp.route("/get_confirmed_position", methods=["GET"])
def get_confirmed_position():
    """
    Devuelve la posición confirmada del usuario (basada en 3 detecciones)
    """
    db = get_db()
    user_id = request.args.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    user_state = db.users_state.find_one({"user_id": user_id})
    
    if not user_state:
        return jsonify({
            "has_position": False,
            "room": None,
            "message": "No hay posición confirmada aún"
        }), 200
    
    return jsonify({
        "has_position": True,
        "room": user_state.get("current_room"),
        "last_update": user_state.get("last_update"),
        "confirmed_at": user_state.get("confirmed_at"),
        "confidence": user_state.get("confidence")
    }), 200