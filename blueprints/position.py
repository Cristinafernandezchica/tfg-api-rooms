# position.py - Versión completa y corregida
import requests
from flask import Blueprint, current_app, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from collections import defaultdict, deque

position_bp = Blueprint("position", __name__)

# Almacenar detecciones pendientes de confirmación (por usuario)
pending_detections = defaultdict(lambda: deque(maxlen=3))

# Almacenar última posición confirmada para evitar llamadas repetidas a BD
confirmed_positions = {}


def add_pending_detection(user_id, detected_room, confidence, timestamp):
    """Añade una detección pendiente para un usuario"""
    pending_detections[user_id].append({
        "room": detected_room,
        "confidence": confidence,
        "timestamp": timestamp
    })
    # Mostrar el estado actual de las detecciones
    current_list = [d["room"] for d in pending_detections[user_id]]
    print(f"   [Detección] {user_id} -> {detected_room} (confianza: {confidence}) - Historial: {current_list}")


def get_confirmed_room(user_id):
    """Verifica si hay 3 detecciones iguales seguidas"""
    detections = list(pending_detections.get(user_id, []))
    
    if len(detections) < 3:
        return None
    
    # Verificar las 3 últimas
    last_three = detections[-3:]
    rooms = [d["room"] for d in last_three]
    
    # Si las 3 son iguales
    if len(set(rooms)) == 1:
        return rooms[0]
    
    # Si 2 de 3 son iguales (modo más tolerante)
    from collections import Counter
    counter = Counter(rooms)
    most_common = counter.most_common(1)[0]
    if most_common[1] >= 2:  # al menos 2 de 3 iguales
        print(f"   ✅ CONFIRMADO (mayoría): {most_common[0]} (2/3 coinciden)")
        return most_common[0]
    
    # Limpiar si no hay consenso
    clear_pending_detections(user_id)
    return None


def clear_pending_detections(user_id):
    """Limpia las detecciones pendientes"""
    print(f"   [DEBUG] Limpiando detecciones pendientes para {user_id}")
    pending_detections[user_id].clear()


def apply_room_update(db, user_id, detected_room, confidence, timestamp):
    """
    Lógica central de actualización de posición y ocupación.
    AHORA con sistema de confirmación de 3 detecciones.
    """
    users_state = db.users_state
    rooms = db.rooms
    room_events = db.room_events

    # Validar que la habitación existe
    room = rooms.find_one({"_id": detected_room})
    if not room:
        return {"error": f"room {detected_room} not found"}, 404

    # Si es zona de tránsito, solo actualizar posición sin confirmación
    if room.get("is_transit", False):
        users_state.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "current_room": detected_room,
                    "last_update": timestamp,
                    "confidence": confidence,
                    "last_event": "transit",
                    "last_room_change": timestamp
                }
            },
            upsert=True
        )
        return {
            "status": "ok",
            "event": "transit",
            "room": detected_room,
            "message": "Zona de tránsito - no se registra ocupación"
        }, 200

    # Añadir detección pendiente
    add_pending_detection(user_id, detected_room, confidence, timestamp)
    
    # Verificar si tenemos confirmación (3 detecciones iguales)
    confirmed_room = get_confirmed_room(user_id)
    
    if not confirmed_room:
        pending_count = len(pending_detections.get(user_id, []))
        return {
            "status": "pending",
            "message": f"Confirmando posición ({pending_count}/3)",
            "current_detection": detected_room,
            "pending_count": pending_count
        }, 200
    
    # Si hay confirmación, procesar el cambio
    user_state = users_state.find_one({"user_id": user_id})
    
    if not user_state:
        # Usuario nuevo - primera vez
        print(f"   🆕 Usuario nuevo {user_id} -> {confirmed_room}")
        users_state.insert_one({
            "user_id": user_id,
            "current_room": confirmed_room,
            "last_update": timestamp,
            "confidence": confidence,
            "last_event": "enter",
            "last_room_change": timestamp,
            "confirmed_at": timestamp
        })

        room_events.insert_one({
            "user_id": user_id,
            "room_id": confirmed_room,
            "event": "enter",
            "timestamp": timestamp,
            "confidence": confidence,
            "confirmed": True
        })

        rooms.update_one({"_id": confirmed_room}, {"$inc": {"current_occupancy": 1}})
        check_low_occupancy_and_notify(db, user_id, confirmed_room)
        
        clear_pending_detections(user_id)
        
        # Actualizar caché
        confirmed_positions[user_id] = confirmed_room
        
        return {
            "status": "ok",
            "event": "enter",
            "room": confirmed_room
        }, 200

    current_room = user_state["current_room"]

    if current_room == confirmed_room:
        # Misma habitación, registrar permanencia
        print(f"   📍 Permanencia en {confirmed_room}")
        users_state.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "last_update": timestamp, 
                    "last_event": "stay",
                    "confidence": confidence
                }
            }
        )
        
        clear_pending_detections(user_id)
        confirmed_positions[user_id] = confirmed_room
        
        return {
            "status": "ok",
            "event": "stay",
            "room": confirmed_room
        }, 200

    # Cambio de habitación confirmado
    print(f"   🔄 Cambio confirmado: {current_room} -> {confirmed_room}")
    
    # Registrar salida de la habitación anterior
    room_events.insert_one({
        "user_id": user_id,
        "room_id": current_room,
        "event": "exit",
        "timestamp": timestamp,
        "confidence": confidence,
        "confirmed": True
    })

    # Registrar entrada a la nueva habitación
    room_events.insert_one({
        "user_id": user_id,
        "room_id": confirmed_room,
        "event": "enter",
        "timestamp": timestamp,
        "confidence": confidence,
        "confirmed": True
    })

    # Actualizar ocupación
    rooms.update_one(
        {"_id": current_room, "current_occupancy": {"$gt": 0}},
        {"$inc": {"current_occupancy": -1}}
    )
    rooms.update_one(
        {"_id": confirmed_room},
        {"$inc": {"current_occupancy": 1}}
    )

    users_state.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "current_room": confirmed_room,
                "last_update": timestamp,
                "confidence": confidence,
                "last_event": "enter",
                "last_room_change": timestamp,
                "confirmed_at": timestamp
            }
        }
    )
    
    check_low_occupancy_and_notify(db, user_id, confirmed_room)
    clear_pending_detections(user_id)
    
    # Actualizar caché
    confirmed_positions[user_id] = confirmed_room

    return {
        "status": "ok",
        "event": "room_changed",
        "from": current_room,
        "to": confirmed_room
    }, 200


@position_bp.route("/update", methods=["POST"])
def update_position():
    """Endpoint para actualizar posición desde la app Android"""
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    detected_room = data.get("detected_room")
    confidence = data.get("confidence", None)
    timestamp = data.get("timestamp", now_iso())

    if not user_id or not detected_room:
        return jsonify({"error": "user_id and detected_room are required"}), 400

    result, status_code = apply_room_update(
        db=db,
        user_id=user_id,
        detected_room=detected_room,
        confidence=confidence,
        timestamp=timestamp
    )

    return jsonify(result), status_code


@position_bp.route("/users_state", methods=["GET"])
def get_users_state():
    db = get_db()
    users = list(db.users_state.find({}, {"_id": 0}))
    return jsonify(users), 200


@position_bp.route("/users_state/<user_id>", methods=["GET"])
def get_user_state(user_id):
    db = get_db()
    user = db.users_state.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user), 200


@position_bp.route("/confirmed_position/<user_id>", methods=["GET"])
def get_confirmed_position(user_id):
    """Endpoint para obtener la posición confirmada actual"""
    db = get_db()
    
    # Primero buscar en caché
    if user_id in confirmed_positions:
        return jsonify({
            "has_position": True,
            "room": confirmed_positions[user_id],
            "cached": True
        }), 200
    
    # Buscar en BD
    user_state = db.users_state.find_one({"user_id": user_id})
    if user_state:
        confirmed_positions[user_id] = user_state["current_room"]
        return jsonify({
            "has_position": True,
            "room": user_state["current_room"],
            "cached": False
        }), 200
    
    return jsonify({
        "has_position": False,
        "room": None
    }), 200


@position_bp.route("/force_start", methods=["POST"])
def force_start_from_entrada():
    """Fuerza la posición del usuario a ENTRADA"""
    db = get_db()
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    timestamp = now_iso()
    
    # Limpiar detecciones pendientes
    clear_pending_detections(user_id)
    
    users_state = db.users_state
    rooms = db.rooms
    room_events = db.room_events
    
    user_state = users_state.find_one({"user_id": user_id})
    current_room = user_state.get("current_room") if user_state else None
    
    if current_room and current_room != "ENTRADA":
        # Registrar salida de la habitación actual
        room_events.insert_one({
            "user_id": user_id,
            "room_id": current_room,
            "event": "exit",
            "timestamp": timestamp,
            "confidence": 1.0,
            "confirmed": True,
            "forced": True
        })
        
        # Disminuir ocupación
        rooms.update_one(
            {"_id": current_room, "current_occupancy": {"$gt": 0}},
            {"$inc": {"current_occupancy": -1}}
        )
    
    # Registrar entrada a ENTRADA
    room_events.insert_one({
        "user_id": user_id,
        "room_id": "ENTRADA",
        "event": "enter",
        "timestamp": timestamp,
        "confidence": 1.0,
        "confirmed": True,
        "forced": True
    })
    
    # Aumentar ocupación de ENTRADA
    rooms.update_one({"_id": "ENTRADA"}, {"$inc": {"current_occupancy": 1}})
    
    # Actualizar estado
    users_state.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "current_room": "ENTRADA",
                "last_update": timestamp,
                "confidence": 1.0,
                "last_event": "enter",
                "last_room_change": timestamp,
                "confirmed_at": timestamp
            }
        },
        upsert=True
    )
    
    # Actualizar caché
    confirmed_positions[user_id] = "ENTRADA"
    
    return jsonify({
        "status": "ok",
        "message": "Posición forzada a ENTRADA",
        "room": "ENTRADA"
    }), 200


def check_low_occupancy_and_notify(db, user_id, room_id):
    """Comprobar ocupación baja y notificar"""
    room = db.rooms.find_one({"_id": room_id}, {"current_occupancy": 1})
    if not room:
        return

    occupancy = room.get("current_occupancy", 0)
    base_url = current_app.config["USERS_API_BASE_URL"]
    
    try:
        resp = requests.get(
            f"{base_url}/internal/users/{user_id}/thresholds",
            timeout=3
        )
    except Exception:
        return

    if resp.status_code != 200:
        return

    thresholds = resp.json() or {}
    threshold_value = thresholds.get(room_id)
    if threshold_value is None:
        return

    if occupancy < threshold_value:
        try:
            requests.post(
                f"{base_url}/internal/low_occupancy_alert",
                json={
                    "user_id": user_id,
                    "room_id": room_id,
                    "occupancy": occupancy
                },
                timeout=3
            )
        except Exception:
            pass


@position_bp.route("/position_status/<user_id>", methods=["GET"])
def get_position_status(user_id):
    """
    Devuelve la posición actual con el estado de confirmación
    """
    db = get_db()
    
    # Obtener estado actual
    user_state = db.users_state.find_one({"user_id": user_id})
    
    # Obtener detecciones pendientes
    pending_detections_list = list(pending_detections.get(user_id, []))
    pending_count = len(pending_detections_list)
    
    if user_state:
        current_room = user_state.get("current_room")
        confirmed_at = user_state.get("confirmed_at")
        
        # Verificar si hay una detección diferente pendiente
        if pending_count > 0:
            latest_pending = pending_detections_list[-1]
            if latest_pending["room"] != current_room:
                # Estamos en proceso de cambio
                return jsonify({
                    "has_position": True,
                    "room": current_room,
                    "pending_room": latest_pending["room"],
                    "pending_count": pending_count,
                    "confirmed": True,
                    "last_update": user_state.get("last_update"),
                    "confirmed_at": confirmed_at
                }), 200
        
        return jsonify({
            "has_position": True,
            "room": current_room,
            "pending_count": 0,
            "confirmed": True,
            "last_update": user_state.get("last_update"),
            "confirmed_at": confirmed_at
        }), 200
    
    # Si no hay estado pero hay detecciones pendientes
    if pending_count > 0:
        latest_pending = pending_detections_list[-1]
        return jsonify({
            "has_position": False,
            "pending_room": latest_pending["room"],
            "pending_count": pending_count,
            "confirmed": False
        }), 200
    
    return jsonify({
        "has_position": False,
        "pending_count": 0,
        "confirmed": False
    }), 200