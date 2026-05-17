import os
import numpy as np
from pymongo import MongoClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.utils import resample
import joblib

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")
client = MongoClient(MONGO_URI)
db = client.get_default_database()

print("Leyendo datos de entrenamiento...")
data = list(db.training_sensor_data.find({}))

if not data:
    print("No hay datos")
    exit()

VALID_ROOMS = ["ENTRADA", "SALON", "COCINA", "HAB1", "HAB2", "HAB3", "BAN2"]

# Normalizamos rssi a -100 si viene a None el valor del sensor
def normalize_rssi(rssi):
    if rssi is None:
        return -100
    return max(-100, min(-40, int(rssi)))

# Nos quedamos solo con muestras que tengan mínimo 2 sensores,
# descartando aquellas con señales débiles
def is_valid_sample(row):
    sensors = row.get("sensors", [])
    if len(sensors) < 2:
        return False
    if all(s.get("rssi", -100) < -95 for s in sensors):
        return False
    return True

data = [row for row in data if row["room_id"] in VALID_ROOMS]


if not data:
    print("No quedan datos válidos")
    exit()

all_sensor_ids = sorted({
    s["sensor_id"]
    for row in data
    for s in row["sensors"]
})

print(f"Detectados {len(all_sensor_ids)} sensores únicos.")

# Convertimos cada muestra en un vector donde cada sensor tiene su posición, 
# poniendo su valore de rssi normalizado o -100 si no está presente
def build_vector(sensors):
    sensor_map = {
        s["sensor_id"]: normalize_rssi(s["rssi"])
        for s in sensors
    }
    return [sensor_map.get(sid, -100) for sid in all_sensor_ids]

X = np.array([build_vector(r["sensors"]) for r in data])
y_room = np.array([r["room_id"] for r in data])
y_zone = np.array([r.get("zone_id") for r in data])

# Se balancea el número de muestras por habitación para evitar sesgos en el modelo, 
# replicando aleatoriamente muestras de las estancias con menos muestras
def balance_classes(X, y):
    classes = np.unique(y)
    max_count = max((y == c).sum() for c in classes)
    Xb, yb = [], []
    for c in classes:
        Xc = X[y == c]
        yc = y[y == c]
        Xr, yr = resample(Xc, yc, replace=True, n_samples=max_count, random_state=42)
        Xb.append(Xr)
        yb.append(yr)
    return np.vstack(Xb), np.concatenate(yb)

print("\nEntrenando modelo de habitación...")

X_train, X_test, y_train, y_test = train_test_split(
    X, y_room, test_size=0.2, random_state=42, stratify=y_room
)

X_train_bal, y_train_bal = balance_classes(X_train, y_train)

room_model = RandomForestClassifier(
    n_estimators=300,
    random_state=42,
    n_jobs=-1
)
room_model.fit(X_train_bal, y_train_bal)

print(classification_report(y_test, room_model.predict(X_test)))

os.makedirs("scripts", exist_ok=True)
joblib.dump(room_model, "scripts/room_model.pkl")
joblib.dump(all_sensor_ids, "scripts/sensor_ids.pkl")

print("Guardado modelo de habitación")


# MODELOS DE ZONAS POR HABITACIÓN 
# (se está usando a la hora de entrenar, pero la división de 
# las estancias en zonas no tiene valor final en el proyecto, 
# pensado para futuras mejoras)

print("\nEntrenando modelos de zonas por habitación...")

for room in VALID_ROOMS:
    rows = [r for r in data if r["room_id"] == room and r.get("zone_id")]

    if len(rows) < 5:
        print(f"No hay suficientes muestras para {room}, saltando...")
        continue

    Xr = np.array([build_vector(r["sensors"]) for r in rows])
    yr = np.array([r["zone_id"] for r in rows])

    X_train, X_test, y_train, y_test = train_test_split(
        Xr, yr, test_size=0.2, random_state=42, stratify=yr
    )

    model = RandomForestClassifier(
        n_estimators=300, # Usamos 300 árboles
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    print(f"\nResultados zonas {room}:")
    print(classification_report(y_test, model.predict(X_test)))

    joblib.dump(model, f"scripts/zone_model_{room}.pkl")
    print(f"Guardado scripts/zone_model_{room}.pkl")
