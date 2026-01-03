import os
from pymongo import MongoClient
from dotenv import load_dotenv 

load_dotenv() 

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")

def seed_rooms():
    client = MongoClient(MONGO_URI)
    db = client.get_default_database()

    rooms = [
        {
            "_id": "ENTRADA",
            "name": "Entrada",
            "poi_id": "poi_57fd1fd2-fc14-47fd-b6df-e2f8589a3e7f",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["SALON"]
        },
        {
            "_id": "SALON",
            "name": "Salón",
            "poi_id": "poi_5ab33651-9e9f-444e-8023-c57dce5d276d",
            "has_beacon": True,
            "beacons": [
                {
                    "id": "BEACON_SALON",
                    "uuid": "DF-7E-1C-79-43-E9-44-FF-88-6F-1D-1F-7D-A6-A0-01",
                    "major": 10007,
                    "minor": 4921
                }
            ],
            "current_occupancy": 0,
            "connections": ["ENTRADA", "PASILLO"]
        },
        {
            "_id": "COCINA",
            "name": "Cocina",
            "poi_id": "poi_fbc620c5-0578-43e1-b04b-9d9a93239d7d",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "HAB1",
            "name": "Habitación 1",
            "poi_id": "poi_b9f47ce4-59d2-4015-b923-e0d3fab646ea",
            "has_beacon": True,
            "beacons": [
                {
                    "id": "BEACON_HAB1",
                    "uuid": "DF-7E-1C-79-43-E9-44-FF-88-6F-1D-1F-7D-A6-A0-02",
                    "major": 10007,
                    "minor": 4812
                }
            ],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "BAN1",
            "name": "Baño 1",
            "poi_id": "poi_40f8c046-cb76-4dbb-900d-bd1d8590cd50",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "BAN2",
            "name": "Baño 2",
            "poi_id": "poi_70b24188-a590-4beb-b003-5aa9e7b44b95",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "HAB2",
            "name": "Habitación 2",
            "poi_id": "poi_bedbfa50-eeca-40a4-8562-78799e66c2b3",
            "has_beacon": True,
            "beacons": [
                {
                    "id": "BEACON_HAB2",
                    "uuid": "DF-7E-1C-79-43-E9-44-FF-88-6F-1D-1F-7D-A6-A0-03",
                    "major": 10007,
                    "minor": 4871
                }
            ],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "HAB3",
            "name": "Habitación 3",
            "poi_id": "poi_f93ff721-4606-45dc-9fcc-bf1d1d00b920",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["PASILLO"]
        },
        {
            "_id": "PASILLO",
            "name": "Pasillo",
            "poi_id": "poi_089e6886-f194-4c5c-9e49-43b3c18a43e9",
            "has_beacon": False,
            "beacons": [],
            "current_occupancy": 0,
            "connections": ["SALON", "COCINA", "HAB1", "BAN1", "BAN2", "HAB2", "HAB3"]
        }
    ]

    for room in rooms:
        existing = db.rooms.find_one({"_id": room["_id"]})
        if existing:
            print(f"Room {room['_id']} ya existe, saltando...")
        else:
            db.rooms.insert_one(room)
            print(f"Room {room['_id']} insertada.")

    client.close()

if __name__ == "__main__":
    seed_rooms()
