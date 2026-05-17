import os

from flask import Blueprint, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from .graph import bfs_with_transit, build_room_graph, bfs, dfs, expand_transit_points, rooms_to_pois

routes_bp = Blueprint("routes", __name__)


def pois_with_coords(db, poi_ids):
    result = []
    for pid in poi_ids:
        poi = db.pois.find_one({"puid": pid})
        if not poi:
            continue

        x = poi.get("x")
        y = poi.get("y")
        floor = poi.get("floor") or poi.get("floor_number")

        if x is None or y is None:
            continue

        result.append({
            "puid": pid,
            "x": x,
            "y": y,
            "floor": floor
        })

    return result

# Para la generación de las rutas
@routes_bp.route("/auto/<algorithm>", methods=["POST"])
def create_auto_route(algorithm):
    db = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    force_start = data.get("force_start", False)

    if force_start:
        start_room = "ENTRADA"
        print(f"Ruta forzada desde ENTRADA")
    else:
        # Obtener posición CONFIRMADA del usuario
        user_state = db.users_state.find_one({"user_id": user_id})
        if not user_state:
            return jsonify({"error": "user has no confirmed position yet"}), 404
        
        start_room = user_state.get("current_room")
        confirmed_at = user_state.get("confirmed_at")
        
        if not start_room:
            return jsonify({"error": "no confirmed room found"}), 404
            
        print(f"Ruta desde posición confirmada: {start_room} (confirmada en {confirmed_at})")

    # Obtener el grafo
    graph, transit_rooms = build_room_graph(db)
    
    # Obtener todas las habitaciones (excluyendo tránsito)
    all_rooms = [r["_id"] for r in db.rooms.find({"is_transit": {"$ne": True}})]
    
    # Generar ruta desde start_room
    full_route = [start_room]
    current = start_room
    rooms_to_visit = [r for r in all_rooms if r != start_room]
    
    while rooms_to_visit:
        best_room = None
        best_path = None
        best_distance = float('inf')
        
        for target in rooms_to_visit:
            path = bfs_with_transit(graph, current, target, transit_rooms)
            if path and len(path) < best_distance:
                best_distance = len(path)
                best_room = target
                best_path = path
        
        if best_path and len(best_path) > 1:
            for room in best_path[1:]:
                if room not in full_route:
                    full_route.append(room)
            current = best_room
            rooms_to_visit.remove(best_room)
        else:
            break
    
    # Expandir para incluir PASILLO
    full_route = expand_transit_points(full_route, transit_rooms)
    
    print(f"Ruta generada: {full_route}")
    
    # Convertir a POIs
    poi_ids = rooms_to_pois(db, full_route)
    poi_route_with_coords = pois_with_coords(db, poi_ids)
    
    route_id = f"{algorithm}_{user_id}_{now_iso()}"
    
    db.routes.insert_one({
        "_id": route_id,
        "name": f"Ruta {algorithm.upper()} para {user_id}",
        "description": f"Generada desde {start_room}",
        "steps": [{"room_id": r, "poi_id": p} for r, p in zip(full_route, poi_ids)],
        "created_at": now_iso()
    })
    
    return jsonify({
        "status": "ok",
        "algorithm": algorithm,
        "start_room": start_room,
        "rooms": full_route,
        "poi_ids": poi_ids,
        "pois": poi_route_with_coords,
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

# No se está utilizando
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


# Preview de la ruta (por si quiere elegir entre varias rutas antes de asignar)  --  No se está usando
'''
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

    # build_room_graph ahora devuelve una tupla (graph, transit_rooms)
    graph, transit_rooms = build_room_graph(db)

    if algorithm == "bfs":
        room_route = bfs(graph, start_room)
    elif algorithm == "dfs":
        room_route = dfs(graph, start_room)
    else:
        return jsonify({"error": "invalid algorithm"}), 400

    poi_ids = rooms_to_pois(db, room_route)
    poi_route_with_coords = pois_with_coords(db, poi_ids)

    return jsonify({
        "status": "ok",
        "rooms": room_route,
        "poi_ids": poi_ids,
        "pois": poi_route_with_coords
    }), 200
'''

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
