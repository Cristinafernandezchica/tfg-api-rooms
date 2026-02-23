from typing import List, Dict, Optional
# No es definitivo, va a cambiar porque se va a intentar entrenar para detectar las habitaciones y punto dentro de la propia habitación
def estimate_room_from_sensors(
    sensors: List[Dict],
    sensor_room_map: Dict[str, str],
    min_sensors: int = 1
) -> Optional[str]:
    """
    Calcula la habitación más probable a partir de una lista de lecturas
    de sensores BLE.

    sensors: [
        {"sensor_id": "BEACON_SALON", "rssi": -67},
        {"sensor_id": "BEACON_HAB1", "rssi": -80},
        ...
    ]

    sensor_room_map:
        {"BEACON_SALON": "SALON", "BEACON_HAB1": "HAB1", ...}

    Devuelve el room_id más probable o None si no se puede estimar.
    """

    # Filtrar solo sensores conocidos (que estén mapeados a rooms)
    filtered = [
        s for s in sensors
        if s.get("sensor_id") in sensor_room_map and "rssi" in s
    ]

    if len(filtered) < min_sensors:
        return None

    # Agrupar por habitación y quedarnos con el mejor RSSI (más cercano a 0)
    room_best_rssi: Dict[str, float] = {}

    for s in filtered:
        room_id = sensor_room_map[s["sensor_id"]]
        rssi = s["rssi"]
        if room_id not in room_best_rssi:
            room_best_rssi[room_id] = rssi
        else:
            # Elegimos el RSSI "más fuerte" (numéricamente mayor, ej -60 > -80)
            room_best_rssi[room_id] = max(room_best_rssi[room_id], rssi)

    if not room_best_rssi:
        return None

    # Escoger la habitación con mejor RSSI
    best_room = max(room_best_rssi.items(), key=lambda x: x[1])[0]
    return best_room
