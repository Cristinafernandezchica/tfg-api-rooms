import os
import numpy as np
import pandas as pd
from pymongo import MongoClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")
client = MongoClient(MONGO_URI)
db = client.get_default_database()

print("📥 Leyendo datos de entrenamiento...")
data = list(db.training_sensor_data.find({}))

if not data:
    print("❌ No hay datos en training_sensor_data")
    exit()

# Extraer todos los sensor_id posibles
all_sensor_ids = sorted({
    s["sensor_id"]
    for row in data
    for s in row["sensors"]
})

print(f"Detectados {len(all_sensor_ids)} sensores únicos.")

def build_vector(sensors):
    sensor_map = {s["sensor_id"]: s["rssi"] for s in sensors}
    return [sensor_map.get(sid, -100) for sid in all_sensor_ids]

X = np.array([build_vector(row["sensors"]) for row in data])
y_room = np.array([row["room_id"] for row in data])
y_zone = np.array([row.get("zone_id") for row in data])

# -------------------------
# MODELO DE HABITACIÓN
# -------------------------
print("\n🏠 Entrenando modelo de habitación...")

X_train, X_test, y_train, y_test = train_test_split(
    X, y_room, test_size=0.2, random_state=42, stratify=y_room
)

room_model = RandomForestClassifier(n_estimators=200, random_state=42)
room_model.fit(X_train, y_train)

y_pred = room_model.predict(X_test)
print("\n📊 Resultados modelo habitación:")
print(classification_report(y_test, y_pred))

# 📁 CAMBIO AQUÍ: Guardar en carpeta scripts
joblib.dump(room_model, "scripts/room_model.pkl")
joblib.dump(all_sensor_ids, "scripts/sensor_ids.pkl")
print("💾 Guardado scripts/room_model.pkl y scripts/sensor_ids.pkl")

# -------------------------
# MODELO DE ZONAS (opcional)
# -------------------------
mask = [z is not None for z in y_zone]

if any(mask):
    print("\n📍 Entrenando modelo de zonas...")

    Xz = X[mask]
    yz = y_zone[mask]

    Xz_train, Xz_test, yz_train, yz_test = train_test_split(
        Xz, yz, test_size=0.2, random_state=42, stratify=yz
    )

    zone_model = RandomForestClassifier(n_estimators=200, random_state=42)
    zone_model.fit(Xz_train, yz_train)

    yz_pred = zone_model.predict(Xz_test)
    print("\n📊 Resultados modelo zonas:")
    print(classification_report(yz_test, yz_pred))

    # 📁 CAMBIO AQUÍ: Guardar en carpeta scripts
    joblib.dump(zone_model, "scripts/zone_model.pkl")
    print("💾 Guardado scripts/zone_model.pkl")
else:
    print("\n⚠️ No hay datos de zonas — no se entrena modelo de zonas.")