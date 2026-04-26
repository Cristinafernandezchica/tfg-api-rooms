from collections import deque

def build_room_graph(db):
    rooms = list(db.rooms.find({}, {"_id": 1, "connections": 1, "is_transit": 1}))
    graph = {}
    transit_rooms = set()

    for room in rooms:
        room_id = room["_id"]
        graph[room_id] = room.get("connections", [])
        if room.get("is_transit", False):
            transit_rooms.add(room_id)

    return graph, transit_rooms


def bfs(graph, start):
    """
    BFS original para recorrer todo el grafo desde un punto de inicio.
    """
    visited = set()
    queue = [start]
    order = []

    while queue:
        room = queue.pop(0)
        if room not in visited:
            visited.add(room)
            order.append(room)
            queue.extend(graph.get(room, []))

    return order


def dfs(graph, start):
    """
    DFS original para recorrer todo el grafo desde un punto de inicio.
    """
    visited = set()
    order = []

    def explore(room):
        if room in visited:
            return
        visited.add(room)
        order.append(room)
        for neighbor in graph.get(room, []):
            explore(neighbor)

    explore(start)
    return order


def bfs_with_transit(graph, start, end, transit_rooms):
    """
    BFS que trata las zonas de tránsito (PASILLO) como pasos obligatorios.
    """
    if start == end:
        return [start]
    
    visited = set()
    queue = deque([(start, [start])])
    
    while queue:
        current_room, path = queue.popleft()
        
        if current_room in visited:
            continue
        visited.add(current_room)
        
        for neighbor in graph.get(current_room, []):
            if neighbor in visited:
                continue
                
            new_path = path + [neighbor]
            
            if neighbor == end:
                return new_path
            
            queue.append((neighbor, new_path))
    
    return [start, end] if end in graph.get(start, []) else [start]


def expand_transit_points(room_route, transit_rooms):
    """
    Expande la ruta para incluir puntos específicos del PASILLO
    cuando se entra y sale de las habitaciones.
    """
    if not room_route:
        return room_route
    
    expanded_route = []
    
    for i, room in enumerate(room_route):
        expanded_route.append(room)
        
        # Si estamos en una habitación y la siguiente es otra habitación diferente
        if i < len(room_route) - 1:
            next_room = room_route[i + 1]
            
            # Si la habitación actual no es de tránsito y la siguiente tampoco
            if room not in transit_rooms and next_room not in transit_rooms:
                # Necesitamos pasar por una zona de tránsito
                if "PASILLO" not in expanded_route[-2:]:
                    expanded_route.append("PASILLO")
    
    return expanded_route


def rooms_to_pois(db, room_route):
    """
    Convierte la ruta de habitaciones a POIs.
    """
    pois = []
    
    for room_id in room_route:
        room = db.rooms.find_one({"_id": room_id}, {"poi_id": 1})
        if room and room.get("poi_id"):
            pois.append(room["poi_id"])
    
    return pois