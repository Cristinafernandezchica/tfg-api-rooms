import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")

def seed_zones():
    client = MongoClient(MONGO_URI)
    db = client.get_default_database()

    zones = [
        # SALÓN
        {
            "room_id": "SALON",
            "zone_id": "ventana",
            "name": "Zona ventana",
            "description": "Ventana de aluminio con vistas al patio interior comunitario."
        },
        {
            "room_id": "SALON",
            "zone_id": "mesa_comedor",
            "name": "Zona mesa comedor",
            "description": "En esta zona se encuentra la mesa de comedor, cuadrada, con superficie de cristal y patas de madera."
        },
        {
            "room_id": "SALON",
            "zone_id": "sofa",
            "name": "Zona sofá",
            "description": "Área del sofá y mesa de salón tipo camilla. En frente, se encuentra el televisor sobre una estantería tipo mueble-bar de madera."
        },

        # HABITACIÓN 1
        {
            "room_id": "HAB1",
            "zone_id": "cama",
            "name": "Zona cama y armario",
            "description": "Cama individual junto a la pared derecha. Esta se encuentra en alto. A los pies de la cama se encuentra el armario de la habitación."
        },
        {
            "room_id": "HAB1",
            "zone_id": "escritorio",
            "name": "Zona escritorio",
            "description": "Escritorio individual con silla reclinable ergonómica. A la izquierda, ventana interior hacia el patio interior."
        },

        # HABITACIÓN 2
        {
            "room_id": "HAB2",
            "zone_id": "cama",
            "name": "Zona cama",
            "description": "Cama individual situada al fondo de la habitación. A la izquierda de la cama se encuentra el armario de la habitación."
        },
        {
            "room_id": "HAB2",
            "zone_id": "escritorio",
            "name": "Zona escritorio",
            "description": "Escritorio con silla reclinable ergonómica. En el escritorio encontramos un monitor de 27 pulgadas sujeto por un soporte que la mantiene en alto y permite moverla libremente. De frente, se encuentra una ventana con vistas al exterior."
        },

        # HABITACIÓN 3
        {
            "room_id": "HAB3",
            "zone_id": "cama",
            "name": "Zona cama",
            "description": "Cama doble en el centro de la habitación. A los pies, se encuentra el armario de la habitación, este está empotrado."
        },
        {
            "room_id": "HAB3",
            "zone_id": "balcon",
            "name": "Zona balcón",
            "description": "Balcón con vistas al exterior. En el encontramos plantas de decoración."
        },

        # COCINA
        {
            "room_id": "COCINA",
            "zone_id": "encimera",
            "name": "Zona encimera",
            "description": "Encimera de la cocina, de color blanca con detalles en color oscuro."
        },
        {
            "room_id": "COCINA",
            "zone_id": "vitro_fregadero",
            "name": "Zona vitro y fregadero",
            "description": "Zona de la encimera con vitrocerámica instalada, junto a ella se encuentra el fregadero."
        },
        {
            "room_id": "COCINA",
            "zone_id": "alacena",
            "name": "Zona alacena",
            "description": "Zona de la alacena, esta cuaenta con una estantería de madera con estantes que cubren todo el alto del espacio."
        },

        # PASILLO
        {
            "room_id": "PASILLO",
            "zone_id": "centro",
            "name": "Zona central",
            "description": "Centro del pasillo. Al fondo podemos ver un cuadro con decoración marina y un zapatero de madera."
        },

        # ENTRADA
        {
            "room_id": "ENTRADA",
            "zone_id": "centro",
            "name": "Zona central",
            "description": "La puerta de entrada a la vivienda es metálica. Nada más entrar, encontramos un armario empotrado con puertas de espejo."
        },

        # BAÑO 1 
        {
            "room_id": "BAN1",
            "zone_id": "ducha",
            "name": "Zona ducha",
            "description": "Plato de ducha antideslizante,con mampara de doble hoja. En frente, una ventana que da a un patio interior con tendedero."
        },
        {
            "room_id": "BAN1",
            "zone_id": "lavamanos",
            "name": "Zona lavamanos",
            "description": "De frente, un lavamanos con mueble tipo cajonera y un espejo de tamaño mediano. A la izquierda, el inodoro marca Roca."
        },
        # BAÑO 2 
        {
            "room_id": "BAN2",
            "zone_id": "ducha",
            "name": "Zona ducha",
            "description": "Plato de ducha antideslizante, con mampara de doble hoja. En frente, una ventana que da a un patio interior con tendedero."
        },
        {
            "room_id": "BAN2",
            "zone_id": "lavamanos",
            "name": "Zona lavamanos",
            "description": "De frente, un lavamanos con mueble tipo cajonera y un espejo de tamaño mediano. A la derecha, el inodoro marca Roca."
        }
    ]

    for zone in zones:
        existing = db.room_zones.find_one({
            "room_id": zone["room_id"],
            "zone_id": zone["zone_id"]
        })

        if existing:
            print(f"Zona {zone['room_id']} - {zone['zone_id']} ya existe, saltando...")
        else:
            db.room_zones.insert_one(zone)
            print(f"Zona {zone['room_id']} - {zone['zone_id']} insertada.")

    client.close()


if __name__ == "__main__":
    seed_zones()
