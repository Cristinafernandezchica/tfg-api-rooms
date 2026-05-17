import logging

import requests
from flask import Blueprint, current_app, request, jsonify
from db.mongo import get_db
from utils.time_utils import now_iso
from collections import defaultdict, deque
from collections import Counter
import time
from datetime import datetime
import threading


position_bp = Blueprint("position", __name__)


# Guardamos en memoria las últimas 3 detecciones para cada usuario, 
# junto con su última posición confirmada.
# Esto es para el sistema de confirmación, en el que solo se acepta un cambio de 
# habitación cuando 2 de las últimas 3 detecciones apuntan al mismo sitio.
pending_detections = defaultdict(lambda: deque(maxlen=3))

# Cacheamos en memoria la última posición confirmada de cada usuario para evitar consultar repetidas y frecuentes a la BD.
# Esta se actualiza cada vez que se confirma un cambio de habitación en apply_room_update. 
confirmed_positions = {}


current_occupancy_memory = defaultdict(int)

user_heartbeat = {}
HEARTBEAT_TIMEOUT_SECONDS = 60  # 1 minuto sin actividad = usuario desconectado
CLEANUP_INTERVAL_SECONDS = 30  # Limpiar usuarios inactivos cada 30 segundos
_cleanup_thread_started = False


# Encargada de añadir una nueva detección al buffer pending_detections 
# El deque del buffer tiene maxlen=3, por lo que si hay 3 entrada, 
# la más antigua se descarta al insertar la nueva.
def add_pending_detection(user_id, detected_room, confidence, timestamp):
    pending_detections[user_id].append({
        "room":       detected_room,
        "confidence": confidence,
        "timestamp":  timestamp
    })
    current_list = [d["room"] for d in pending_detections[user_id]]
    logging.debug(f"[Detección] {user_id} -> {detected_room} " 
                  f"(confianza: {confidence}) - Historial: {current_list}")

# Para decidir si las últimas detecciones son suficientemente consistente 
# como para confirmar el cambio de habitación. Son 3 casos:
#  Caso 1: Si las 3 últimas habitaciones son la misma --> Se confirma la habitación.
#  Caso 2: Si 2 de las 3 últimas son la misma --> Se confirma por mayoría.
#  Caso 3: Si no coincide ninguna --> Se limpia el buffer y devolvermos None.
def get_confirmed_room(user_id):
    detections = list(pending_detections.get(user_id, []))

    # Si no hay suficientes detecciones (3), no se confirma nada
    if len(detections) < 3:
        return None

    last_three = detections[-3:]
    rooms = [d["room"] for d in last_three]

    # Caso 1
    if len(set(rooms)) == 1:
        return rooms[0]

    # Caso 2
    counter = Counter(rooms)
    most_common = counter.most_common(1)[0]
    if most_common[1] >= 2:
        logging.debug(f"[Confirmación por mayoría] {user_id} -> {most_common[0]} (2/3 coinciden)")
        return most_common[0]

    # Caso 3
    clear_pending_detections(user_id)
    return None

# Vaciamos el buffer de detecciones pendientes de un usuario. Se llama cuando:
def clear_pending_detections(user_id):
    logging.debug(f"   [DEBUG] Limpiando detecciones pendientes para {user_id}")    
    print(f"   [DEBUG] Limpiando detecciones pendientes para {user_id}")
    pending_detections[user_id].clear()


# CÁLCULO DE OCUPACIÓN

# Se definen zonas de tránsito ya que no son una estancia real, si no que las conecta
def is_transit_room(db, room_id):
    """Verifica si una habitación es zona de tránsito (no cuenta para ocupación)"""
    room = db.rooms.find_one({"_id": room_id}, {"is_transit": 1})
    return room and room.get("is_transit", False)


'''
@position_bp.route("/recalculate_occupancy", methods=["POST"])
def recalc_occupancy():
    """Endpoint administrativo para recalcular toda la ocupación desde cero"""
    db = get_db()
    
    # Resetear todas las ocupaciones a 0
    db.rooms.update_many({}, {"$set": {"current_occupancy": 0}})
    current_occupancy_memory.clear()
    
    # Obtener usuarios activos (con heartbeat reciente)
    now = datetime.now().isoformat()
    current_time = datetime.fromisoformat(now)
    active_users = []
    
    for user_id, last_seen_str in user_heartbeat.items():
        try:
            last_seen = datetime.fromisoformat(last_seen_str)
            if (current_time - last_seen).total_seconds() <= HEARTBEAT_TIMEOUT_SECONDS:
                active_users.append(user_id)
        except Exception as e:
            logging.error(f"Error parsing heartbeat for {user_id}: {e}")
    
    # Recalcular solo para usuarios activos
    if active_users:
        users = db.users_state.find({
            "user_id": {"$in": active_users}
        }, {"current_room": 1, "user_id": 1})
        
        for user in users:
            room = user.get("current_room")
            user_id = user.get("user_id")
            if room and not is_transit_room(db, room):
                current_occupancy_memory[room] += 1
    
    # Actualizar BD
    for room_id, count in current_occupancy_memory.items():
        db.rooms.update_one({"_id": room_id}, {"$set": {"current_occupancy": count}})
    
    return jsonify({
        "status": "recalculated", 
        "occupancy": dict(current_occupancy_memory),
        "active_users": len(active_users)
    }), 200
'''

# Aquí se entra tras pasar el filtro de 3 detecciones. Se actualiza el estado del usuario,
# registramos los eventos de entrada/salida y recalculamos la ocupación de las habitaciones.
# Se pueden dar 4 casos:
#  Caso 1: Zona de trásito (PASILLO) --> Solo se actualiza la posición del usuario
#  Caso 2: Usuario nuevo --> Se registra su estado y "enter" en la habitación correspondiente
#  Caso 3: Continua en misma habitación --> Solo se actualiza timestamp ("stay")
#  Caso 4: Cambio habitación --> Se registra "exit" de la anterior y "enter" en la nueva,
#          además de acutalizar el estado del usuario y recalcular la ocupación.
def apply_room_update(db, user_id, detected_room, confidence, timestamp):
    update_user_heartbeat(user_id, timestamp)
    users_state = db.users_state
    rooms       = db.rooms
    room_events = db.room_events

    # La habitación existe
    room = rooms.find_one({"_id": detected_room})
    if not room:
        return {"error": f"room {detected_room} not found"}, 404

    # Caso 1: Zona de tránsito
    if room.get("is_transit", False):
        users_state.update_one(
            {"user_id": user_id},
            {"$set": {
                "current_room":     detected_room,
                "last_update":      timestamp,
                "confidence":       confidence,
                "last_event":       "transit",
                "last_room_change": timestamp
            }},
            upsert=True
        )
        return {
            "status":  "ok",
            "event":   "transit",
            "room":    detected_room,
            "message": "Zona de tránsito - No se registra ocupación"
        }, 200

    user_state   = users_state.find_one({"user_id": user_id})
    current_room = user_state["current_room"] if user_state else None

    # Caso 2: Usuario nuevo
    if not user_state:
        logging.info(f"Usuario nuevo {user_id} -> {detected_room}")
        users_state.insert_one({
            "user_id":          user_id,
            "current_room":     detected_room,
            "last_update":      timestamp,
            "confidence":       confidence,
            "last_event":       "enter",
            "last_room_change": timestamp,
            "confirmed_at":     timestamp
        })
        room_events.insert_one({
            "user_id":    user_id,
            "room_id":    detected_room,
            "event":      "enter",
            "timestamp":  timestamp,
            "confidence": confidence,
            "confirmed":  True
        })
        
        # Actualizar ocupación incrementalmente
        if not is_transit_room(db, detected_room):
            current_occupancy_memory[detected_room] += 1
            db.rooms.update_one(
                {"_id": detected_room},
                {"$inc": {"current_occupancy": 1}}
            )
        
        check_low_occupancy_and_notify(db, user_id, detected_room) # Actualmente no se manda ninguna notificación, pensado para funcionalidad futura
        confirmed_positions[user_id] = detected_room
        return {"status": "ok", "event": "enter", "room": detected_room}, 200

    # Caso 3: Permanece en la misma habitación
    if current_room == detected_room:
        print(f" Permanencia en {detected_room}")
        users_state.update_one(
            {"user_id": user_id},
            {"$set": {
                "last_update": timestamp,
                "last_event":  "stay",
                "confidence":  confidence
            }}
        )
        confirmed_positions[user_id] = detected_room
        return {"status": "ok", "event": "stay", "room": detected_room}, 200
    
    # Caso 4: Cambio de habitación
    logging.info(f"Usuario {user_id} cambió de {current_room} a {detected_room}")
    print(f"Cambio confirmado: {current_room} -> {detected_room}")

    # 1. Usuario sale de la habitación anterior
    if current_room and not is_transit_room(db, current_room):
        current_occupancy_memory[current_room] -= 1
        db.rooms.update_one(
            {"_id": current_room},
            {"$inc": {"current_occupancy": -1}}
        )

    # 2. Usuario entra a la nueva habitación
    if not is_transit_room(db, detected_room):
        current_occupancy_memory[detected_room] += 1
        db.rooms.update_one(
            {"_id": detected_room},
            {"$inc": {"current_occupancy": 1}}
        )
    
    room_events.insert_one({
        "user_id":    user_id,
        "room_id":    current_room,
        "event":      "exit",
        "timestamp":  timestamp,
        "confidence": confidence,
        "confirmed":  True
    })
    room_events.insert_one({
        "user_id":    user_id,
        "room_id":    detected_room,
        "event":      "enter",
        "timestamp":  timestamp,
        "confidence": confidence,
        "confirmed":  True
    })
    users_state.update_one(
        {"user_id": user_id},
        {"$set": {
            "current_room":     detected_room,
            "last_update":      timestamp,
            "confidence":       confidence,
            "last_event":       "enter",
            "last_room_change": timestamp,
            "confirmed_at":     timestamp
        }}
    )
    # recalculate_occupancy(db)
    check_low_occupancy_and_notify(db, user_id, detected_room)
    confirmed_positions[user_id] = detected_room
    return {
        "status": "ok",
        "event":  "room_changed",
        "from":   current_room,
        "to":     detected_room
    }, 200



# Para actualizar la posición sin pasar por el sistema de confirmación de habitación. 
# Para pruebas o en caso de que se nos mande la habitación externamente ya confirmada. 
# ACTUALMENTE EN DESHUSO, diseñado para pruebas anteriores
@position_bp.route("/update", methods=["POST"])
def update_position():
    db   = get_db()
    data = request.get_json() or {}

    user_id       = data.get("user_id")
    detected_room = data.get("detected_room")
    confidence    = data.get("confidence", None)
    timestamp     = data.get("timestamp", now_iso())

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


# Da la última habitación confirmada de un usuario
# Primero mira en memoria, si no está, va a BD y actualiza la caché
# ACTUALMENTE EN DESHUSO
@position_bp.route("/confirmed_position/<user_id>", methods=["GET"])
def get_confirmed_position(user_id):
    db = get_db()

    if user_id in confirmed_positions:
        return jsonify({
            "has_position": True,
            "room":         confirmed_positions[user_id],
            "cached":       True
        }), 200

    user_state = db.users_state.find_one({"user_id": user_id})
    if user_state:
        confirmed_positions[user_id] = user_state["current_room"]
        return jsonify({
            "has_position": True,
            "room":         user_state["current_room"],
            "cached":       False
        }), 200

    return jsonify({"has_position": False, "room": None}), 200


# Para forzar la posición de un usuario a ENTRADA, sin pasar por el sistema de confirmación.
# ACTUALMENTE EN DESHUSO, diseñado para pruebas anteriores
@position_bp.route("/force_start", methods=["POST"])
def force_start_from_entrada():
    db   = get_db()
    data = request.get_json() or {}

    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    timestamp = now_iso()

    # Paso 1: limpiamos el buffer de detecciones
    clear_pending_detections(user_id)

    users_state = db.users_state
    room_events = db.room_events

    user_state   = users_state.find_one({"user_id": user_id})
    current_room = user_state.get("current_room") if user_state else None

    # Paso 2: si venía de otra habitación, registrar su salida
    if current_room and current_room != "ENTRADA":
        room_events.insert_one({
            "user_id":    user_id,
            "room_id":    current_room,
            "event":      "exit",
            "timestamp":  timestamp,
            "confidence": 1.0,
            "confirmed":  True,
            "forced":     True
        })

    # Paso 3: registrar entrada a ENTRADA
    room_events.insert_one({
        "user_id":    user_id,
        "room_id":    "ENTRADA",
        "event":      "enter",
        "timestamp":  timestamp,
        "confidence": 1.0,
        "confirmed":  True,
        "forced":     True
    })

    # Paso 4: actualizar el estado del usuario en BD
    users_state.update_one(
        {"user_id": user_id},
        {"$set": {
            "current_room":     "ENTRADA",
            "last_update":      timestamp,
            "confidence":       1.0,
            "last_event":       "enter",
            "last_room_change": timestamp,
            "confirmed_at":     timestamp
        }},
        upsert=True
    )

    # Paso 5: recalcular ocupación desde room_events (de todas las habitaciones)
    # recalculate_occupancy(db)
    if current_room and current_room != "ENTRADA":
        current_occupancy_memory[current_room] -= 1
        db.rooms.update_one({"_id": current_room}, {"$inc": {"current_occupancy": -1}})
    
    current_occupancy_memory["ENTRADA"] += 1
    db.rooms.update_one({"_id": "ENTRADA"}, {"$inc": {"current_occupancy": 1}})

    confirmed_positions[user_id] = "ENTRADA"
    return jsonify({
        "status":  "ok",
        "message": "Posición forzada a ENTRADA",
        "room":    "ENTRADA"
    }), 200


# Comprobar si la ocupación de una habitación ha bajado el umbral configurado 
# por el usuario, si es así, enviar una alerta. 
# Se llama cada vez que se confirma un cambio de posición.
# Está implmentada para futuras funcionalidades, no se está haciendo uso real de ella
def check_low_occupancy_and_notify(db, user_id, room_id):
    """
    Comprueba si la ocupación de una habitación ha bajado del umbral
    configurado por el usuario y, si es así, envía una alerta.

    Pasos:
      1. Lee la ocupación actual de la habitación desde BD.
      2. Consulta los umbrales del usuario en la API externa.
      3. Si la ocupación está por debajo del umbral del usuario para
         esa habitación, hace un POST de alerta a la API externa.

    Los errores de red se silencian (except pass) para que un fallo
    en la API de usuarios no interrumpa el flujo de posicionamiento.
    """
    room = db.rooms.find_one({"_id": room_id}, {"current_occupancy": 1})
    if not room:
        return

    occupancy = room.get("current_occupancy", 0)
    base_url  = current_app.config["USERS_API_BASE_URL"]

    try:
        resp = requests.get(
            f"{base_url}/internal/users/{user_id}/thresholds",
            timeout=3
        )
    except Exception:
        return

    if resp.status_code != 200:
        return

    thresholds      = resp.json() or {}
    threshold_value = thresholds.get(room_id)
    if threshold_value is None:
        return

    # Aquí llamamos a la API de usuarios
    # TODO: Está por terminar esta oarte
    if occupancy < threshold_value:
        try:
            requests.post(
                f"{base_url}/internal/low_occupancy_alert",
                json={
                    "user_id":   user_id,
                    "room_id":   room_id,
                    "occupancy": occupancy
                },
                timeout=3
            )
        except Exception:
            pass

# Para consultar la posición actual de un usuario junto con el estado del 
# proceso de confirmación. Se puden dar varios casos:
#  Caso 1: Posición confirmada, sin cambio en curso
#  Caso 2: Posición confirmada, pero con detecciones de otrta habitación (el cambio está en proceso)
#  Caso 3: Sin estado confirmado pero con detecciones acumulándose
#  Caso 4: Sin posición y sin detecciones
'''
@position_bp.route("/position_status/<user_id>", methods=["GET"])
def get_position_status(user_id):
    db = get_db()

    user_state            = db.users_state.find_one({"user_id": user_id})
    pending_detections_list = list(pending_detections.get(user_id, []))
    pending_count         = len(pending_detections_list)

    if user_state:
        current_room = user_state.get("current_room")
        confirmed_at = user_state.get("confirmed_at")

        # Caso 2
        if pending_count > 0:
            latest_pending = pending_detections_list[-1]
            if latest_pending["room"] != current_room:
                return jsonify({
                    "has_position":  True,
                    "room":          current_room,
                    "pending_room":  latest_pending["room"],
                    "pending_count": pending_count,
                    "confirmed":     True,
                    "last_update":   user_state.get("last_update"),
                    "confirmed_at":  confirmed_at
                }), 200

        # Caso 1
        return jsonify({
            "has_position":  True,
            "room":          current_room,
            "pending_count": 0,
            "confirmed":     True,
            "last_update":   user_state.get("last_update"),
            "confirmed_at":  confirmed_at
        }), 200

    # Caso 3
    if pending_count > 0:
        latest_pending = pending_detections_list[-1]
        return jsonify({
            "has_position":  False,
            "pending_room":  latest_pending["room"],
            "pending_count": pending_count,
            "confirmed":     False
        }), 200

    # Caso 4
    return jsonify({
        "has_position":  False,
        "pending_count": 0,
        "confirmed":     False
    }), 200
'''



def cleanup_inactive_users(db):
    """Elimina usuarios que no han tenido actividad reciente"""
    now = datetime.now().isoformat()
    current_time = datetime.fromisoformat(now)
    inactive_users = []
    
    for user_id, last_seen_str in user_heartbeat.items():
        last_seen = datetime.fromisoformat(last_seen_str)
        if (current_time - last_seen).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS:
            inactive_users.append(user_id)
    
    for user_id in inactive_users:
        # Obtener la habitación actual del usuario
        user_state = db.users_state.find_one({"user_id": user_id})
        if user_state:
            current_room = user_state.get("current_room")
            if current_room and not is_transit_room(db, current_room):
                # Registrar salida automática
                timestamp = now_iso()
                db.room_events.insert_one({
                    "user_id": user_id,
                    "room_id": current_room,
                    "event": "exit",
                    "timestamp": timestamp,
                    "confidence": 1.0,
                    "confirmed": True,
                    "auto_exit": True
                })
                
                # Actualizar ocupación
                current_occupancy_memory[current_room] -= 1
                db.rooms.update_one(
                    {"_id": current_room},
                    {"$inc": {"current_occupancy": -1}}
                )
            
            # Eliminar estado del usuario
            db.users_state.delete_one({"user_id": user_id})
        
        # Limpiar heartbeat y caché
        del user_heartbeat[user_id]
        if user_id in confirmed_positions:
            del confirmed_positions[user_id]
        if user_id in pending_detections:
            clear_pending_detections(user_id)
        
        logging.info(f"Usuario {user_id} eliminado por inactividad")


def update_user_heartbeat(user_id, timestamp):
    """Actualiza el último momento de actividad del usuario"""
    user_heartbeat[user_id] = timestamp


@position_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    """Endpoint para que la app envíe señales de vida"""
    db = get_db()
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    timestamp = now_iso()
    update_user_heartbeat(user_id, timestamp)
    
    return jsonify({"status": "ok"}), 200


def start_cleanup_thread(db):
    """Inicia un hilo que limpia usuarios inactivos periódicamente"""
    global _cleanup_thread_started
    
    if _cleanup_thread_started:
        return
    
    def cleanup_loop():
        while True:
            time.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                cleanup_inactive_users(db)
            except Exception as e:
                logging.error(f"Error en limpieza de usuarios: {e}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    _cleanup_thread_started = True
    logging.info("Hilo de limpieza de usuarios iniciado")