# cleanup_training_data_improved.py
import pymongo
from pymongo import MongoClient
from collections import defaultdict

# --- CONFIGURACIÓN ---
MONGO_URI = "mongodb://localhost:27017/indoor_db"
DB_NAME = "indoor_db"
COLLECTION_NAME = "training_sensor_data"

# --- DEFINICIÓN DE SENSORES ESPERADOS POR HABITACIÓN ---
# NO es un filtro estricto, sino una guía de qué sensores deberían estar presentes
EXPECTED_SENSORS = {
    "ENTRADA": {"BEACON_SALON", "BEACON_COCINA", "BEACON_HAB1"},
    "SALON": {"BEACON_SALON", "BEACON_COCINA", "BEACON_HAB1"},
    "COCINA": {"BEACON_COCINA", "BEACON_SALON", "BEACON_HAB1"},
    "HAB1": {"BEACON_HAB1", "BEACON_SALON", "BEACON_COCINA"},
    "BAN2": {"BEACON_BANO2", "BEACON_HAB2", "BEACON_HAB3"},
    "HAB2": {"BEACON_HAB2", "BEACON_HAB3", "BEACON_BANO2"},
    "HAB3": {"BEACON_HAB3", "BEACON_HAB2", "BEACON_BANO2"}
}

# Sensores que son RUIDO para cada habitación (deberían estar AUSENTES)
NOISE_SENSORS = {
    "ENTRADA": {"BEACON_BANO2", "BEACON_HAB2", "BEACON_HAB3"},
    "SALON": {"BEACON_BANO2", "BEACON_HAB2", "BEACON_HAB3"},
    "COCINA": {"BEACON_HAB2", "BEACON_HAB3"},  # BAN2 NO es ruido para COCINA (puede ayudar)
    "HAB1": {"BEACON_HAB2", "BEACON_HAB3"},
    "BAN2": {"BEACON_SALON", "BEACON_COCINA", "BEACON_HAB1"},
    "HAB2": {"BEACON_SALON", "BEACON_COCINA", "BEACON_HAB1"},
    "HAB3": {"BEACON_SALON", "BEACON_COCINA", "BEACON_HAB1"}
}

MIN_SENSORS = 2
MAX_WEAK_SIGNALS = 1  # Máximo de señales débiles permitidas (rssi < -85)

def is_weak_signal(rssi):
    """Define qué es una señal débil"""
    return rssi < -85

def analyze_sample(sample):
    """Analiza una muestra y devuelve diagnóstico"""
    room_id = sample.get("room_id")
    sensors = sample.get("sensors", [])
    
    # Agrupar por tipo de sensor
    sensor_dict = {s["sensor_id"]: s["rssi"] for s in sensors}
    present_sensors = set(sensor_dict.keys())
    
    # 1. Verificar si faltan sensores esperados
    expected = EXPECTED_SENSORS.get(room_id, set())
    missing_expected = expected - present_sensors
    
    # 2. Verificar presencia de sensores ruidosos
    noise = NOISE_SENSORS.get(room_id, set())
    present_noise = present_sensors & noise
    
    # 3. Verificar señales débiles
    weak_signals = [s for s in sensors if is_weak_signal(s["rssi"])]
    
    return {
        "present": present_sensors,
        "missing_expected": missing_expected,
        "present_noise": present_noise,
        "weak_signals_count": len(weak_signals),
        "total_sensors": len(sensors)
    }

def main():
    print("🔧 Conectando a MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    
    # Estadísticas
    stats = defaultdict(int)
    samples_to_delete = []
    samples_to_keep = []
    
    print("📊 Analizando muestras...")
    all_samples = list(collection.find({}))
    
    for sample in all_samples:
        room_id = sample.get("room_id")
        sample_id = sample["_id"]
        
        # Habitaciones no definidas
        if room_id not in EXPECTED_SENSORS:
            stats[f"unknown_room_{room_id}"] += 1
            samples_to_delete.append(sample_id)
            continue
        
        analysis = analyze_sample(sample)
        
        # CRITERIOS PARA ELIMINAR:
        
        # 1. Demasiadas señales débiles
        if analysis["weak_signals_count"] > MAX_WEAK_SIGNALS:
            stats["too_many_weak_signals"] += 1
            samples_to_delete.append(sample_id)
            continue
        
        # 2. Faltan sensores críticos (para habitaciones con beacon propio)
        critical_rooms = {"SALON", "HAB1", "HAB2", "HAB3", "BAN2"}
        if room_id in critical_rooms:
            # Para estas habitaciones, DEBE estar presente su beacon principal
            main_beacon = {
                "SALON": {"BEACON_SALON1", "BEACON_SALON2"},
                "HAB1": {"BEACON_HAB1"},
                "HAB2": {"BEACON_HAB2"},
                "HAB3": {"BEACON_HAB3"},
                "BAN2": {"BEACON_BANO2"}
            }.get(room_id, set())
            
            if main_beacon and not (main_beacon & analysis["present"]):
                stats[f"missing_main_beacon_{room_id}"] += 1
                samples_to_delete.append(sample_id)
                continue
        
        # 3. Demasiados sensores ruidosos (excepto para COCINA)
        if room_id != "COCINA" and len(analysis["present_noise"]) > 2:
            stats[f"too_much_noise_{room_id}"] += 1
            samples_to_delete.append(sample_id)
            continue
        
        # 4. Para COCINA: caso especial - señales de BAN2 son útiles, no ruido
        if room_id == "COCINA":
            # Si tiene BEACON_BANO2 con señal fuerte, es buena señal
            ban2_signal = next((s for s in sample["sensors"] if s["sensor_id"] == "BEACON_BANO2"), None)
            if ban2_signal and ban2_signal["rssi"] > -80:
                stats["cocina_with_strong_ban2"] += 1
                # Esto es BUENO, no la eliminamos
        
        # Si pasa todos los filtros, la conservamos
        samples_to_keep.append(sample_id)
        stats["kept"] += 1
    
    # Mostrar diagnóstico por habitación
    print("\n📈 DIAGNÓSTICO POR HABITACIÓN:")
    room_counts = defaultdict(int)
    for sample in all_samples:
        room_counts[sample.get("room_id")] += 1
    
    for room, count in sorted(room_counts.items()):
        deleted = sum(1 for sid in samples_to_delete 
                     if collection.find_one({"_id": sid}).get("room_id") == room)
        print(f"  {room}: {count} muestras totales, {deleted} a eliminar, {count-deleted} a conservar")
    
    print(f"\n📊 COCINA - Análisis especial:")
    cocina_samples = [s for s in all_samples if s.get("room_id") == "COCINA"]
    if cocina_samples:
        ban2_present = 0
        for s in cocina_samples:
            if any(sen["sensor_id"] == "BEACON_BANO2" for sen in s["sensors"]):
                ban2_present += 1
        print(f"  Muestras con BEACON_BANO2: {ban2_present}/{len(cocina_samples)}")
        
        if ban2_present < len(cocina_samples) * 0.3:
            print("  ⚠️ Pocas muestras tienen señal de BAN2. ¡Esto dificulta la detección de COCINA!")
            print("  Sugerencia: Recolecta más muestras en COCINA capturando también BEACON_BANO2")
    
    # Preguntar antes de eliminar
    print(f"\n⚠️ Se eliminarán {len(samples_to_delete)} muestras")
    response = input("¿Continuar? (s/n): ")
    
    if response.lower() == 's':
        if samples_to_delete:
            result = collection.delete_many({"_id": {"$in": samples_to_delete}})
            print(f"✅ Eliminadas {result.deleted_count} muestras")
        
        print("\n--- RESUMEN ---")
        for key, value in stats.items():
            print(f"{key}: {value}")
    else:
        print("Operación cancelada")
    
    client.close()

if __name__ == "__main__":
    main()