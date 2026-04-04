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
    
    # Si no hay historial, usar nueva detección
    if not history:
        history.append(new_label)
        return new_label
    
    # Obtener última habitación del historial
    last_room = history[-1]
    
    # Si la nueva detección es diferente a la anterior
    if new_label != last_room:
        # Limpiar historial para evitar cambios bruscos
        history.clear()
        history.append(new_label)
        return new_label
    
    # Si es la misma, añadir al historial
    history.append(new_label)
    
    # Si el historial está lleno, devolver la más frecuente
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
    # Ordenar por intensidad
    sensors_sorted = sorted(sensors, key=lambda s: s["rssi"], reverse=True)

    # Beacon más fuerte
    sid = sensors_sorted[0]["sensor_id"]
    rssi = sensors_sorted[0]["rssi"]

    # 1) Habitaciones con beacon propio → detección directa
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

    # 2) Preparar señales para ENTRADA (única sin beacon)
    salon = [s for s in sensors if s["sensor_id"] == "BEACON_SALON"]
    cocina = [s for s in sensors if s["sensor_id"] == "BEACON_COCINA"]
    hab1 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB1"]
    hab2 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB2"]
    hab3 = [s for s in sensors if s["sensor_id"] == "BEACON_HAB3"]
    ban2 = [s for s in sensors if s["sensor_id"] == "BEACON_BANO2"]
    
    # Calcular promedios - Está pensado por si hay más de un beacon por habitación (con vistas a futuro)
    avg_salon = sum(s["rssi"] for s in salon) / len(salon) if salon else -100
    avg_cocina = sum(s["rssi"] for s in cocina) / len(cocina) if cocina else -100
    avg_hab1 = hab1[0]["rssi"] if hab1 else -100
    avg_hab2 = hab2[0]["rssi"] if hab2 else -100
    avg_hab3 = hab3[0]["rssi"] if hab3 else -100
    avg_ban2 = ban2[0]["rssi"] if ban2 else -100
    
    print(f"   [Heurística] Promedios - SALÓN: {avg_salon:.1f}, COCINA: {avg_cocina:.1f}, HAB1: {avg_hab1:.1f}, BAN2: {avg_ban2:.1f}")
    
    # 3) DETECCIÓN DE ENTRADA (múltiples patrones basados en datos reales)
    
    # Patrón A: SALÓN fuerte pero NO es SALÓN (porque el beacon no superó el umbral)
    # En ENTRADA, SALÓN puede estar entre -62 y -84
    if salon and avg_salon > -85:  # Hay señal de SALÓN
        # Contar cuántas otras habitaciones tienen señal significativa
        otras_habitaciones = 0
        if avg_cocina > -80: otras_habitaciones += 1
        if avg_hab1 > -80: otras_habitaciones += 1
        if avg_hab2 > -80: otras_habitaciones += 1
        if avg_hab3 > -80: otras_habitaciones += 1
        if avg_ban2 > -80: otras_habitaciones += 1
        
        # Si SOLO SALÓN tiene señal fuerte, es ENTRADA
        if otras_habitaciones <= 1:
            print(f"   [Heurística] Patrón ENTRADA A: solo SALÓN detectable ({otras_habitaciones} otras)")
            return "ENTRADA"
    
    # Patrón B: SALÓN y COCINA tienen señales similares (ambas moderadas)
    # En SALÓN real, COCINA sería más débil
    if salon and cocina:
        diferencia = abs(avg_salon - avg_cocina)
        # Si están cerca (diferencia < 10dB), probablemente ENTRADA
        if diferencia < 10 and avg_salon > -85 and avg_cocina > -85:
            print(f"   [Heurística] Patrón ENTRADA B: SALÓN y COCINA cercanos (dif {diferencia:.1f}dB)")
            return "ENTRADA"
    
    # Patrón C: SALÓN moderado y HAB1 débil
    if salon and avg_salon > -80 and avg_hab1 < -80:
        # Verificar que no sea SALÓN (en SALÓN, HAB1 sería más fuerte)
        if avg_hab1 < -85:  # HAB1 muy débil
            print(f"   [Heurística] Patrón ENTRADA C: SALÓN moderado ({avg_salon:.1f}), HAB1 débil ({avg_hab1:.1f})")
            return "ENTRADA"
    
    # Patrón D: Señales múltiples pero ninguna supera el umbral del beacon
    # Este es el caso más común: todas las señales son débiles o moderadas
    if not any([
        rssi > -75 for s in sensors if s["sensor_id"] == "BEACON_SALON"
    ]) and not any([
        rssi > -75 for s in sensors if s["sensor_id"] == "BEACON_COCINA"
    ]) and not any([
        rssi > -78 for s in sensors if s["sensor_id"] in ["BEACON_HAB1", "BEACON_HAB2", "BEACON_HAB3"]
    ]) and not any([
        rssi > -80 for s in sensors if s["sensor_id"] == "BEACON_BANO2"
    ]):
        # Ningún beacon superó su umbral
        if len(sensors) >= 2:
            print(f"   [Heurística] Patrón ENTRADA D: ningún beacon fuerte, {len(sensors)} sensores presentes")
            return "ENTRADA"
    
    # Patrón E: Basado en tus datos - cuando SALÓN está entre -70 y -80
    if salon and -80 < avg_salon < -65:
        # Verificar que COCINA no sea muy fuerte
        if avg_cocina < -75 or avg_cocina == -100:
            print(f"   [Heurística] Patrón ENTRADA E: SALÓN en rango ENTRADA ({avg_salon:.1f})")
            return "ENTRADA"
    
    print(f"   [Heurística] Ningún patrón coincidió")
    return None


@sensors_bp.route("/update_position", methods=["POST"])
def update_position_from_sensors():
    print("Actualizando posición desde sensores...")
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    sensors = data.get("sensors") or []
    timestamp = data.get("timestamp", now_iso())

    print(f"Datos recibidos: {data}")
    if not user_id or not sensors:
        return jsonify({"error": "user_id and sensors are required"}), 400

    # 1. FILTRADO INICIAL
    sensors = [s for s in sensors if s.get("rssi", -100) > -85]
    print(f"Señales filtradas (rssi > -85): {[s['sensor_id'] + ':' + str(s['rssi']) for s in sensors]}")

    # Necesitamos al menos 2 sensores
    if len(sensors) < 2:
        return jsonify({
            "error": "not_enough_beacons",
            "room": None,
            "zone": None,
            "confidence": 0.0
        }), 200

    sensor_room_map = build_sensor_room_map(db)
    print(f"Mapa de sensores a habitaciones: {sensor_room_map}")
    
    feature_vector = build_feature_vector_from_sensors(sensors)
    last_room = user_room_history[user_id][-1] if user_room_history[user_id] else None

    # 3. DETECCIÓN DE HABITACIÓN
    detected_room = None
    try:
        # PASO 1: Heurísticas fuertes (prioridad máxima)
        override = heuristic_room_override(sensors)
        if override:
            detected_room = override
            print(f"✓ Heurística fuerte activada: {detected_room}")
        else:
            print("ℹ️ No se activó heurística fuerte. Usando lógica para habitaciones sin beacon...")
            
            # PASO 2: Modelo ML para habitaciones sin beacon propio
            ml_prediction = predict_room(feature_vector)
            
            # Solo ENTRADA no tiene beacon propio ahora (COCINA ya tiene beacon)
            rooms_for_ml = ["ENTRADA"]
            
            if ml_prediction in rooms_for_ml:
                detected_room = ml_prediction
                print(f"✓ Modelo ML predijo habitación sin beacon: {detected_room}")
            else:
                print(f"⚠️ Modelo ML predijo '{ml_prediction}', que no está en la lista de confianza. Ignorando.")
                detected_room = None

            # PASO 3: Fallback inteligente
            if not detected_room:
                print("ℹ️ Usando fallback inteligente (estimate_room_from_sensors)...")
                detected_room = estimate_room_from_sensors(
                    sensors=sensors,
                    sensor_room_map=sensor_room_map,
                    last_room=last_room
                )
                print(f"✓ Fallback eligió: {detected_room}")

    except Exception as e:
        print(f"❌ Error en detección de habitación: {e}. Usando fallback de emergencia.")
        detected_room = estimate_room_from_sensors(
            sensors=sensors,
            sensor_room_map=sensor_room_map,
            last_room=last_room
        )

    # Suavizado final
    print(f"Habitación antes de suavizado: {detected_room}")
    room_smoothed = smooth_label(user_room_history[user_id], detected_room)
    print(f"Habitación suavizada a: {room_smoothed}")

    # Fallback duro
    if not room_smoothed:
        room_smoothed = estimate_room_from_sensors(
            sensors=sensors,
            sensor_room_map=sensor_room_map,
            last_room=None
        )
        print(f"⚠️ Fallback duro activado, habitación final: {room_smoothed}")

    if not room_smoothed:
        return jsonify({"error": "could_not_detect_room"}), 400

    # 4. DETECCIÓN DE ZONA
    zones_for_room = list(db.room_zones.find({"room_id": room_smoothed}))

    zone_smoothed = None
    if len(zones_for_room) == 0:
        print(f"Habitación {room_smoothed} no tiene zonas definidas.")
        zone_smoothed = None
    elif len(zones_for_room) == 1:
        zone_smoothed = zones_for_room[0]["zone_id"]
        print(f"Zona única para {room_smoothed}: {zone_smoothed}")
    else:
        try:
            detected_zone = predict_zone(feature_vector, room_smoothed)
            print(f"Zona detectada por ML para {room_smoothed}: {detected_zone}")
        except Exception as e:
            print(f"Error en predict_zone: {e}")
            detected_zone = None

        zone_smoothed = smooth_label(user_zone_history[user_id], detected_zone)
        print(f"Zona suavizada: {zone_smoothed}")

        zone_doc = db.room_zones.find_one(
            {"room_id": room_smoothed, "zone_id": zone_smoothed}
        )
        if not zone_doc:
            print(f"⚠️ Zona '{zone_smoothed}' no válida para {room_smoothed}. Reseteando.")
            zone_smoothed = None

    # 5. ACTUALIZAR ESTADO DEL USUARIO
    from blueprints.position import apply_room_update
    result, status = apply_room_update(
        db=db,
        user_id=user_id,
        detected_room=room_smoothed,
        confidence=None,
        timestamp=timestamp
    )

    if zone_smoothed:
        zone_doc = db.room_zones.find_one(
            {"room_id": room_smoothed, "zone_id": zone_smoothed},
            {"_id": 0}
        )
        if zone_doc:
            result["zone"] = zone_smoothed
            result["zone_info"] = zone_doc

    result["confidence"] = heuristic_confidence(sensors)
    result["room"] = room_smoothed
    print(f"Resultado final: {result}")

    return jsonify(result), status


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