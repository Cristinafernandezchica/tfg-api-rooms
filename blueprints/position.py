import requests
from flask import Blueprint, current_app, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso

position_bp = Blueprint("position", __name__)

# Para la actualización de posición del usuario y ocupación de las estancias
def apply_room_update(db, user_id, detected_room, confidence, timestamp):
    """
    Lógica central de actualización de posición y ocupación.
    Reutilizada tanto por /position/update como por /sensors/update_position.
    """
    users_state = db.users_state
    rooms = db.rooms
    room_events = db.room_events

    # Validar que la habitación existe
    room = rooms.find_one({"_id": detected_room})
    if not room:
        return {"error": f"room {detected_room} not found"}, 404

    user_state = users_state.find_one({"user_id": user_id})

    if room.get("is_transit", False):
        # Solo actualizar posición del usuario, pero no ocupación
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

    # Si el usuario no tenía estado previo
    if not user_state:
        users_state.insert_one({
            "user_id": user_id,
            "current_room": detected_room,
            "last_update": timestamp,
            "confidence": confidence,
            "last_event": "enter",
            "last_room_change": timestamp
        })

        room_events.insert_one({
            "user_id": user_id,
            "room_id": detected_room,
            "event": "enter",  # Se califica como entrada a la estancia
            "timestamp": timestamp,
            "confidence": confidence
        })

        rooms.update_one({"_id": detected_room}, {"$inc": {"current_occupancy": 1}})
        check_low_occupancy_and_notify(db, user_id, detected_room) # Se comprueba el cambio de ocupación y se notifica si es necesario
        return {
            "status": "ok",
            "event": "enter",
            "room": detected_room
        }, 200

    # Usuario ya tiene estado
    current_room = user_state["current_room"]

    if current_room == detected_room:
        users_state.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "last_update": timestamp,
                    "confidence": confidence,
                    "last_event": "stay"  # Si el usuario sigue en la misma habitación
                }
            }
        )
        return {
            "status": "ok",
            "event": "stay",
            "room": detected_room
        }, 200

    # Cambio de habitación: exit de la antigua + enter en la nueva
    room_events.insert_one({
        "user_id": user_id,
        "room_id": current_room,
        "event": "exit",
        "timestamp": timestamp,
        "confidence": confidence
    })

    room_events.insert_one({
        "user_id": user_id,
        "room_id": detected_room,
        "event": "enter",
        "timestamp": timestamp,
        "confidence": confidence
    })

    rooms.update_one(
        {"_id": current_room, "current_occupancy": {"$gt": 0}},
        {"$inc": {"current_occupancy": -1}}
    )
    rooms.update_one(
        {"_id": detected_room},
        {"$inc": {"current_occupancy": 1}}
    )

    users_state.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "current_room": detected_room,
                "last_update": timestamp,
                "confidence": confidence,
                "last_event": "enter",
                "last_room_change": timestamp
            }
        }
    )
    # Comprobar ocupación baja por el cambio de estanias y mandar notificación si procede
    check_low_occupancy_and_notify(db, user_id, detected_room)

    return {
        "status": "ok",
        "event": "room_changed",
        "from": current_room,
        "to": detected_room
    }, 200

# Endpoint para la actualización de la posición del usuario (la debe usar la app Android)
# Usa la función apply_room_update para no duplicar lógica
@position_bp.route("/update", methods=["POST"])
def update_position():
    """
    Endpoint que la app Android puede usar si ya hace el cálculo
    de habitación y solo nos manda detected_room.
    """
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


# Para obtener la posición actual de todos los usuarios
@position_bp.route("/users_state", methods=["GET"])
def get_users_state():
    db = get_db()
    users = list(db.users_state.find({}, {"_id": 0}))
    return jsonify(users), 200

# Para obtener la posición actual de un usuario concreto
@position_bp.route("/users_state/<user_id>", methods=["GET"])
def get_user_state(user_id):
    db = get_db()
    user = db.users_state.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user), 200

# Comprobar si la ocupación de una sala ha bajado del umbral configurado 
# por el usuario y notificarle llamando a la API de usuarios
def check_low_occupancy_and_notify(db, user_id, room_id):
    # 1. Obtener ocupación actual de la sala
    room = db.rooms.find_one({"_id": room_id}, {"current_occupancy": 1})
    if not room:
        return

    occupancy = room.get("current_occupancy", 0)

    # 2. Obtener umbrales del usuario desde API usuarios
    base_url = current_app.config["USERS_API_BASE_URL"]
    try:
        resp = requests.get(
            f"{base_url}/internal/users/{user_id}/thresholds",
            timeout=3
        )
    except Exception:
        return  # si falla el servicio de usuarios, no bloqueamos

    if resp.status_code != 200:
        return

    thresholds = resp.json() or {}
    threshold_value = thresholds.get(room_id)
    if threshold_value is None:
        return  # el usuario no configuró umbral para esta sala

    # 3. Comprobar si se cumple el umbral
    if occupancy < threshold_value:
        # Opcional: evitar duplicados con una colección low_occupancy_alerts
        # 4. Llamar a endpoint interno de aviso
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
