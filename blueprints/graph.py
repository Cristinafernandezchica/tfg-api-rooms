def build_room_graph(db):
    rooms = list(db.rooms.find({}, {"_id": 1, "connections": 1}))
    graph = {}

    for room in rooms:
        room_id = room["_id"]
        graph[room_id] = room.get("connections", [])

    return graph


def bfs(graph, start):
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


def rooms_to_pois(db, room_route):
    pois = []
    for room_id in room_route:
        room = db.rooms.find_one({"_id": room_id}, {"poi_id": 1})
        if room:
            pois.append(room["poi_id"])
    return pois
