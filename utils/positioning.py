from typing import List, Dict, Optional

def estimate_room_from_sensors(
    sensors: List[Dict],
    sensor_room_map: Dict[str, str],
    last_room: Optional[str] = None
) -> Optional[str]:
    """
    Fallback inteligente para estimar habitación.
    Prioriza las habitaciones con señales muy fuertes.
    """

    # Filtrar sensores que conocemos y tienen RSSI
    known_sensors = [
        s for s in sensors
        if s.get("sensor_id") in sensor_room_map and "rssi" in s
    ]

    if not known_sensors:
        return last_room

    # 1. ¿Algún beacon está MUY cerca? (RSSI > -70)
    for s in known_sensors:
        if s["rssi"] > -70:
            room = sensor_room_map[s["sensor_id"]]
            print(f"   [Fallback] Beacon {s['sensor_id']} muy fuerte ({s['rssi']}) -> {room}")
            return room

    # 2. Agrupar por habitación y quedarse con el mejor RSSI
    room_best_rssi: Dict[str, float] = {}
    for s in known_sensors:
        room = sensor_room_map[s["sensor_id"]]
        rssi = s["rssi"]
        if room not in room_best_rssi or rssi > room_best_rssi[room]:
            room_best_rssi[room] = rssi

    # 3. Elegir la habitación con el mejor RSSI
    if room_best_rssi:
        best_room = max(room_best_rssi.items(), key=lambda x: x[1])[0]
        print(f"   [Fallback] Mejor RSSI por habitación: {room_best_rssi} -> {best_room}")
        return best_room

    return last_room