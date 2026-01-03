from flask import Blueprint, jsonify
from db.mongo import get_db

rooms_bp = Blueprint("rooms", __name__)

@rooms_bp.route("", methods=["GET"])
def list_rooms():
    """
    Lista todas las habitaciones con información básica y ocupación actual.
    """
    db = get_db()
    cursor = db.rooms.find(
        {},
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


@rooms_bp.route("/room_events", methods=["GET"])
def get_room_events():
    db = get_db()
    events = list(db.room_events.find({}, {"_id": 0}))
    return jsonify(events), 200


@rooms_bp.route("/room_events/<user_id>", methods=["GET"])
def get_room_events_user(user_id):
    db = get_db()
    events = list(db.room_events.find({"user_id": user_id}, {"_id": 0}))
    return jsonify(events), 200
