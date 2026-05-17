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

# Herística para determinar la habitación, basada en patrones de rssi de datos reales
def heuristic_room_override(sensors):
    # Diccionario con los rssi de cada beacon
    def rssi(beacon_id):
        s = next((x for x in sensors if x["sensor_id"] == beacon_id), None)
        return s["rssi"] if s else None

    salon_r   = rssi("BEACON_SALON")
    cocina_r  = rssi("BEACON_COCINA")
    hab1_r    = rssi("BEACON_HAB1")
    hab2_r    = rssi("BEACON_HAB2")
    hab3_r    = rssi("BEACON_HAB3")
    ban2_r    = rssi("BEACON_BANO2")

    # Se tratan los None como -100
    def v(x):
        return x if x is not None else -100

    # ------------- HABITACIONES ---------------------------------
    # Umbral basado en p75 de cada beacon en su habitación + margen
    if v(hab1_r) > -62:
        print(f"   [H] HAB1 fuerte ({hab1_r}) -> HAB1")
        return "HAB1"
    if v(hab2_r) > -62:
        print(f"   [H] HAB2 fuerte ({hab2_r}) -> HAB2")
        return "HAB2"
    if v(hab3_r) > -62:
        print(f"   [H] HAB3 fuerte ({hab3_r}) -> HAB3")
        return "HAB3"

    # ── REGLA 2: BAN2 vs HAB3 — usar diferencia relativa ──────────────────────
    # En BAN2: BEACON_BANO2 > BEACON_HAB3 siempre (media +8 dBm)
    # En HAB3: BEACON_HAB3 > BEACON_BANO2 siempre (media +12 dBm)
    if v(ban2_r) > -78 and v(hab3_r) > -78:
        diff = v(ban2_r) - v(hab3_r)
        if diff >= 3:
            print(f"   [H] BAN2({ban2_r}) > HAB3({hab3_r}) diff={diff} -> BAN2")
            return "BAN2"
        elif diff <= -3:
            print(f"   [H] HAB3({hab3_r}) > BAN2({ban2_r}) diff={diff} -> HAB3")
            return "HAB3"
    elif v(ban2_r) > -75 and v(hab3_r) == -100:
        print(f"   [H] Solo BAN2 visible ({ban2_r}) -> BAN2")
        return "BAN2"
    elif v(hab3_r) > -70 and v(ban2_r) == -100:
        print(f"   [H] Solo HAB3 visible ({hab3_r}) -> HAB3")
        return "HAB3"

    # ── REGLA 3: COCINA — BEACON_HAB1 muy débil es clave discriminadora ───────
    # En COCINA: HAB1 siempre < -75 (min real -75, media -85.6)
    # En HAB1:   COCINA puede solaparse (-66 a -89), pero HAB1 siempre domina
    if v(cocina_r) > -72:
        if v(hab1_r) <= -75 or hab1_r is None:
            print(f"   [H] COCINA({cocina_r}), HAB1 débil({hab1_r}) -> COCINA")
            return "COCINA"

    # ── REGLA 4: HAB1 — BEACON_COCINA siempre débil en HAB1 ──────────────────
    # En HAB1: COCINA nunca supera -66 (cuando presente), HAB1 siempre domina
    if v(hab1_r) > -67 and v(cocina_r) < -70:
        print(f"   [H] HAB1({hab1_r}) domina, COCINA débil({cocina_r}) -> HAB1")
        return "HAB1"

    # ── REGLA 5: SALON vs ENTRADA — diferencia relativa ───────────────────────
    # Discriminador clave: diff(salon - cocina)
    # SALON:   diff ≥ 3  (min real), media 14.5
    # ENTRADA: diff puede ser negativa hasta -9, media 7.1
    if v(salon_r) > -82:
        if cocina_r is not None:
            diff = v(salon_r) - v(cocina_r)
            if diff >= 12:
                # Diferencia grande → claramente en SALON
                print(f"   [H] SALON({salon_r}) - COCINA({cocina_r}) = {diff} -> SALON")
                return "SALON"
            elif diff <= 5:
                # SALON y COCINA equiparados o COCINA domina → ENTRADA
                print(f"   [H] SALON({salon_r}) ≈ COCINA({cocina_r}) diff={diff} -> ENTRADA")
                return "ENTRADA"
            else:
                # Zona gris (diff 6-11): usar umbral absoluto de SALON
                if v(salon_r) > -63:
                    print(f"   [H] Zona gris: SALON fuerte ({salon_r}) -> SALON")
                    return "SALON"
                else:
                    print(f"   [H] Zona gris: SALON moderado ({salon_r}) -> ENTRADA")
                    return "ENTRADA"
        else:
            # COCINA no visible: si SALON es fuerte → SALON; si es débil → ENTRADA
            if v(salon_r) > -70:
                print(f"   [H] SALON({salon_r}) sin COCINA visible -> SALON")
                return "SALON"
            else:
                print(f"   [H] SALON débil ({salon_r}) sin COCINA -> ENTRADA")
                return "ENTRADA"

    print(f"   [H] Ningún patrón coincidió")
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
    try:
        all_samples = list(db.training_sensor_data.find({}, {"_id": 0, "room_id": 1, "zone_id": 1}))
        
        total_samples = len(all_samples)
        samples_by_room = {}
        
        for sample in all_samples:
            room = sample.get("room_id", "desconocido")
            zone = sample.get("zone_id", "desconocido")
            
            if room not in samples_by_room:
                samples_by_room[room] = {
                    "total": 0,
                    "zones": {}
                }
            
            if zone not in samples_by_room[room]["zones"]:
                samples_by_room[room]["zones"][zone] = 0
            
            samples_by_room[room]["zones"][zone] += 1
            samples_by_room[room]["total"] += 1
        
        result = {
            "status": "ok",
            "total_samples": total_samples,
            "samples_by_room": samples_by_room
        }
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


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