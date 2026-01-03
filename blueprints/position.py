from flask import Blueprint, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso

position_bp = Blueprint("position", __name__)

@position_bp.route("/update", methods=["POST"])
def update_position():
    """
    Endpoint principal que la app Android llamará para actualizar
    la posición del usuario (habitación detectada).
    """
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    detected_room = data.get("detected_room")
    confidence = data.get("confidence", None)
    timestamp = data.get("timestamp", now_iso())

    if not user_id or not detected_room:
        return jsonify({"error": "user_id and detected_room are required"}), 400

    users_state = db.users_state
    rooms = db.rooms
    room_events = db.room_events

    # Validar que la habitación existe
    room = rooms.find_one({"_id": detected_room})
    if not room:
        return jsonify({"error": f"room {detected_room} not found"}), 404

    user_state = users_state.find_one({"user_id": user_id})

    # Si el usuario no tenía estado previo
    if not user_state:
        # Insertar estado nuevo
        users_state.insert_one({
            "user_id": user_id,
            "current_room": detected_room,
            "last_update": timestamp,
            "confidence": confidence,
            "last_event": "enter",
            "last_room_change": timestamp
        })

        # Evento de entrada
        room_events.insert_one({
            "user_id": user_id,
            "room_id": detected_room,
            "event": "enter",
            "timestamp": timestamp,
            "confidence": confidence
        })

        # Incrementar ocupación
        rooms.update_one({"_id": detected_room}, {"$inc": {"current_occupancy": 1}})

        return jsonify({
            "status": "ok",
            "event": "enter",
            "room": detected_room
        }), 200

    # Usuario ya tiene estado
    current_room = user_state["current_room"]

    if current_room == detected_room:
        # Mismo cuarto: "stay"
        users_state.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "last_update": timestamp,
                    "confidence": confidence,
                    "last_event": "stay"
                }
            }
        )
        return jsonify({
            "status": "ok",
            "event": "stay",
            "room": detected_room
        }), 200

    # Cambio de habitación: exit de la antigua + enter en la nueva
    # Evento exit de current_room
    room_events.insert_one({
        "user_id": user_id,
        "room_id": current_room,
        "event": "exit",
        "timestamp": timestamp,
        "confidence": confidence
    })

    # Evento enter de detected_room
    room_events.insert_one({
        "user_id": user_id,
        "room_id": detected_room,
        "event": "enter",
        "timestamp": timestamp,
        "confidence": confidence
    })

    # Actualizar ocupación (protegiendo negativos)
    rooms.update_one(
        {"_id": current_room, "current_occupancy": {"$gt": 0}},
        {"$inc": {"current_occupancy": -1}}
    )
    rooms.update_one(
        {"_id": detected_room},
        {"$inc": {"current_occupancy": 1}}
    )

    # Actualizar estado usuario
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

    return jsonify({
        "status": "ok",
        "event": "room_changed",
        "from": current_room,
        "to": detected_room
    }), 200

# Para ver donde están todos los usuarios (no tiene una utilidad real por el momento)
@position_bp.route("/users_state", methods=["GET"])
def get_users_state():
    db = get_db()
    users = list(db.users_state.find({}, {"_id": 0}))
    return jsonify(users), 200

# Para ver donde está cada usuario (no tiene una utilidad real por el momento)
@position_bp.route("/users_state/<user_id>", methods=["GET"])
def get_user_state(user_id):
    db = get_db()
    user = db.users_state.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user), 200
