from flask import Blueprint, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from .graph import build_room_graph, bfs, dfs, rooms_to_pois

routes_bp = Blueprint("routes", __name__)

@routes_bp.route("/auto/<algorithm>", methods=["POST"])
def create_auto_route(algorithm):
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    # Obtener habitación actual del usuario
    user_state = db.users_state.find_one({"user_id": user_id})
    if not user_state:
        return jsonify({"error": "user has no position yet"}), 404

    start_room = user_state["current_room"]

    # Construir grafo real desde rooms
    graph = build_room_graph(db)

    # Generar ruta
    if algorithm == "bfs":
        room_route = bfs(graph, start_room)
    elif algorithm == "dfs":
        room_route = dfs(graph, start_room)
    else:
        return jsonify({"error": "invalid algorithm"}), 400

    # Convertir habitaciones → POIs
    poi_route = rooms_to_pois(db, room_route)

    # Crear route_id único
    route_id = f"{algorithm}_{user_id}_{now_iso()}"

    # Guardar ruta en MongoDB
    db.routes.insert_one({
        "_id": route_id,
        "name": f"Ruta {algorithm.upper()} para {user_id}",
        "description": f"Generada automáticamente usando {algorithm.upper()}",
        "steps": [{"room_id": r, "poi_id": p} for r, p in zip(room_route, poi_route)],
        "created_at": now_iso()
    })

    # Asignar ruta al usuario
    db.user_routes.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "route_id": route_id,
                "current_step": 0,
                "completed": False,
                "assigned_at": now_iso(),
                "updated_at": now_iso()
            }
        },
        upsert=True
    )

    return jsonify({
        "status": "ok",
        "algorithm": algorithm,
        "rooms": room_route,
        "pois": poi_route,
        "route_id": route_id
    }), 200



@routes_bp.route("/<route_id>", methods=["GET"])
def get_route(route_id):
    db = get_db()
    route = db.routes.find_one({"_id": route_id})
    if not route:
        return jsonify({"error": "route not found"}), 404

    # Convertir _id a string explícito para JSON
    route["route_id"] = route["_id"]
    del route["_id"]
    return jsonify(route), 200

@routes_bp.route("/assign", methods=["POST"])
def assign_route():
    """
    Asigna una ruta a un usuario.
    """
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    route_id = data.get("route_id")

    if not user_id or not route_id:
        return jsonify({"error": "user_id and route_id are required"}), 400

    route = db.routes.find_one({"_id": route_id})
    if not route:
        return jsonify({"error": "route not found"}), 404

    db.user_routes.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "route_id": route_id,
                "current_step": 0,
                "completed": False,
                "assigned_at": now_iso(),
                "updated_at": now_iso()
            }
        },
        upsert=True
    )

    return jsonify({"status": "ok"}), 200

@routes_bp.route("/user/<user_id>", methods=["GET"])
def get_user_route(user_id):
    """
    Devuelve la ruta asignada a un usuario + su progreso.
    """
    db = get_db()
    user_route = db.user_routes.find_one({"user_id": user_id})
    if not user_route:
        return jsonify({"error": "no route assigned"}), 404

    route = db.routes.find_one({"_id": user_route["route_id"]})
    if not route:
        return jsonify({"error": "route not found"}), 404

    # Ajustar IDs para JSON
    route_response = {
        "route_id": route["_id"],
        "name": route.get("name"),
        "description": route.get("description"),
        "steps": route.get("steps", [])
    }

    user_route_response = {
        "user_id": user_route["user_id"],
        "route_id": user_route["route_id"],
        "current_step": user_route.get("current_step", 0),
        "completed": user_route.get("completed", False),
        "assigned_at": user_route.get("assigned_at"),
        "updated_at": user_route.get("updated_at")
    }

    return jsonify({
        "user_route": user_route_response,
        "route": route_response
    }), 200

@routes_bp.route("/progress", methods=["POST"])
def update_progress():
    """
    Actualiza el progreso del usuario en la ruta.
    Se espera que la app llame cuando detecta que el usuario ha llegado
    a una habitación concreta de la ruta.
    """
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    reached_room_id = data.get("room_id")   # habitación donde ha llegado

    if not user_id or not reached_room_id:
        return jsonify({"error": "user_id and room_id are required"}), 400

    user_route = db.user_routes.find_one({"user_id": user_id})
    if not user_route:
        return jsonify({"error": "no route assigned"}), 404

    route = db.routes.find_one({"_id": user_route["route_id"]})
    if not route:
        return jsonify({"error": "route not found"}), 404

    current_step = user_route.get("current_step", 0)
    steps = route.get("steps", [])

    if current_step >= len(steps):
        return jsonify({"status": "already_completed"}), 200

    expected_room = steps[current_step].get("room_id")

    if expected_room != reached_room_id:
        return jsonify({
            "status": "mismatch",
            "expected_room": expected_room,
            "reached_room": reached_room_id
        }), 200

    # Avanzar un paso
    new_step = current_step + 1
    completed = new_step >= len(steps)

    db.user_routes.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "current_step": new_step,
                "completed": completed,
                "updated_at": now_iso()
            }
        }
    )

    return jsonify({
        "status": "ok",
        "current_step": new_step,
        "completed": completed
    }), 200


# Ver todas las rutas
@routes_bp.route("", methods=["GET"])
def list_routes():
    db = get_db()
    routes = list(db.routes.find({}, {"_id": 1, "name": 1, "created_at": 1, "steps": 1}))
    return jsonify(routes), 200

# Borrar ruta
@routes_bp.route("/<route_id>", methods=["DELETE"])
def delete_route(route_id):
    db = get_db()
    result = db.routes.delete_one({"_id": route_id})
    if result.deleted_count == 0:
        return jsonify({"error": "route not found"}), 404
    return jsonify({"status": "deleted"}), 200


# Preview de la ruta (por si quiere elegir entre varias rutas antes de asignar)
@routes_bp.route("/preview/<algorithm>", methods=["POST"])
def preview_route(algorithm):
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    user_state = db.users_state.find_one({"user_id": user_id})
    if not user_state:
        return jsonify({"error": "user has no position"}), 404

    start_room = user_state["current_room"]

    graph = build_room_graph(db)

    if algorithm == "bfs":
        room_route = bfs(graph, start_room)
    elif algorithm == "dfs":
        room_route = dfs(graph, start_room)
    else:
        return jsonify({"error": "invalid algorithm"}), 400

    poi_route = rooms_to_pois(db, room_route)

    return jsonify({
        "status": "ok",
        "rooms": room_route,
        "pois": poi_route
    }), 200


# Quitar ruta asignada a un usuario
@routes_bp.route("/reset_user", methods=["POST"])
def reset_user_route():
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    db.user_routes.delete_one({"user_id": user_id})

    return jsonify({"status": "reset"}), 200


# Obtener siguiente paso (siguiente estancia)
@routes_bp.route("/user/<user_id>/next", methods=["GET"])
def get_next_step(user_id):
    db = get_db()

    user_route = db.user_routes.find_one({"user_id": user_id})
    if not user_route:
        return jsonify({"error": "no route assigned"}), 404

    route = db.routes.find_one({"_id": user_route["route_id"]})
    if not route:
        return jsonify({"error": "route not found"}), 404

    current_step = user_route.get("current_step", 0)
    steps = route.get("steps", [])

    if current_step >= len(steps):
        return jsonify({"status": "completed"}), 200

    next_step = steps[current_step]

    return jsonify({
        "status": "ok",
        "next_room": next_step["room_id"],
        "next_poi": next_step["poi_id"]
    }), 200
