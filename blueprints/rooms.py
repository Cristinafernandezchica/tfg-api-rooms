from datetime import datetime
from flask import Blueprint, jsonify, request
from db.mongo import get_db

rooms_bp = Blueprint("rooms", __name__)

# Lista todas las habitaciones con información básica y ocupación actual de cada una
@rooms_bp.route("", methods=["GET"])
def list_rooms():
    """
    Lista todas las habitaciones con información básica y ocupación actual.
    """
    db = get_db()
    cursor = db.rooms.find(
        {"is_transit": {"$ne": True}},
        {
            "_id": 1,
            "name": 1,
            "poi_id": 1,
            "current_occupancy": 1
        }
    )

    rooms = []
    for r in cursor:
        rooms.append({
            "room_id": r["_id"],
            "name": r.get("name"),
            "poi_id": r.get("poi_id"),
            "current_occupancy": r.get("current_occupancy", 0)
        })

    return jsonify(rooms), 200


# Número de personas en cada estancia actualmente (solo habría que agrupar por habitaciones)
@rooms_bp.route("/occupancy", methods=["GET"])
def occupancy():
    """
    Devuelve solo la ocupación por habitación (mapa simple).
    """
    db = get_db()
    cursor = db.rooms.find(
        {},
        {
            "_id": 1,
            "current_occupancy": 1
        }
    )

    result = {}
    for r in cursor:
        result[r["_id"]] = r.get("current_occupancy", 0)

    return jsonify(result), 200

# Devuelve todas las entradas/salidas registradas en las habitaciones
@rooms_bp.route("/room_events", methods=["GET"])
def get_room_events():
    db = get_db()
    events = list(db.room_events.find({}, {"_id": 0}))
    return jsonify(events), 200

# Devuelve todas las entradas/salidas registradas de un usuario concreto
@rooms_bp.route("/room_events/<user_id>", methods=["GET"])
def get_room_events_user(user_id):
    db = get_db()
    events = list(db.room_events.find({"user_id": user_id}, {"_id": 0}))
    return jsonify(events), 200


# Número de personas en cada estancia en cualquier momento del pasado (rango de fechas)
@rooms_bp.route("/occupancy/history", methods=["GET"])
def occupancy_history():
    """
    Devuelve la ocupación (entradas/salidas) de una habitación
    en un rango de fechas.
    Parámetros:
      - room_id (obligatorio)
      - from (ISO string, opcional)
      - to (ISO string, opcional)
    """
    db = get_db()

    room_id = request.args.get("room_id")
    from_str = request.args.get("from")
    to_str = request.args.get("to")

    if not room_id:
        return jsonify({"error": "room_id is required"}), 400

    query = {"room_id": room_id}
    time_filter = {}

    def parse_iso(s):
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    if from_str:
        dt = parse_iso(from_str)
        if not dt:
            return jsonify({"error": "invalid from datetime"}), 400
        time_filter["$gte"] = dt

    if to_str:
        dt = parse_iso(to_str)
        if not dt:
            return jsonify({"error": "invalid to datetime"}), 400
        time_filter["$lte"] = dt

    if time_filter:
        query["timestamp"] = time_filter

    events = list(db.room_events.find(query, {"_id": 0}))

    return jsonify({
        "room_id": room_id,
        "count": len(events),
        "events": events
    }), 200

# Devulve la ocupación de una estancia en un momento concreto
@rooms_bp.route("/occupancy/at", methods=["GET"])
def occupancy_at():
    """
    Devuelve la ocupación de una habitación en un instante concreto.
    Parámetros:
      - room_id
      - at (ISO datetime)
    """
    db = get_db()
    room_id = request.args.get("room_id")
    at_str = request.args.get("at")

    if not room_id or not at_str:
        return jsonify({"error": "room_id and at are required"}), 400

    try:
        at_dt = datetime.fromisoformat(at_str)
    except:
        return jsonify({"error": "invalid datetime"}), 400

    events = list(db.room_events.find(
        {
            "room_id": room_id,
            "timestamp": {"$lte": at_dt}
        },
        {"event": 1, "_id": 0}
    ))

    occupancy = 0
    for e in events:
        if e["event"] == "enter":
            occupancy += 1
        elif e["event"] == "exit":
            occupancy -= 1

    return jsonify({
        "room_id": room_id,
        "at": at_str,
        "occupancy": occupancy
    }), 200

# Número de personas que han pasado por cada estancia actualmente
@rooms_bp.route("/visits/current", methods=["GET"])
def visits_current():
    db = get_db()
    rooms = db.rooms.find({}, {"_id": 1})

    result = {}
    for r in rooms:
        room_id = r["_id"]
        count = db.room_events.count_documents({
            "room_id": room_id,
            "event": "enter"
        })
        result[room_id] = count

    return jsonify(result), 200


# Número de personas que han pasado por cada estancia en un momento concreto
@rooms_bp.route("/visits/at", methods=["GET"])
def visits_at():
    db = get_db()
    room_id = request.args.get("room_id")
    at_str = request.args.get("at")

    if not room_id or not at_str:
        return jsonify({"error": "room_id and at are required"}), 400

    try:
        at_dt = datetime.fromisoformat(at_str)
    except:
        return jsonify({"error": "invalid datetime"}), 400

    count = db.room_events.count_documents({
        "room_id": room_id,
        "event": "enter",
        "timestamp": {"$lte": at_dt}
    })

    return jsonify({
        "room_id": room_id,
        "at": at_str,
        "visits": count
    }), 200

# Obtener las zonas de una habitación
@rooms_bp.route("/<room_id>/zones", methods=["GET"])
def get_zones(room_id):
    db = get_db()
    zones = list(db.room_zones.find({"room_id": room_id}, {"_id": 0}))
    return jsonify(zones), 200
