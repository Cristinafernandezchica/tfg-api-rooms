import pytest
from unittest.mock import patch, MagicMock

class TestRoomsEndpoints:
    """Pruebas de los endpoints de habitaciones"""
    
    # GET /rooms
    
    def test_list_rooms_retorna_lista_de_habitaciones(self, client, mock_get_db):
        """Dada una petición GET a /rooms, cuando existen habitaciones, entonces retorna lista con sus datos"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {
                "_id": "SALON",
                "name": "Salón",
                "poi_id": "poi_123",
                "current_occupancy": 3,
                "description": "Salón principal"
            },
            {
                "_id": "COCINA",
                "name": "Cocina",
                "poi_id": "poi_456",
                "current_occupancy": 1,
                "description": "Cocina equipada"
            }
        ]
        
        response = client.get('/rooms')
        
        assert response.status_code == 200
        rooms = response.json
        assert len(rooms) == 2
        assert rooms[0]['room_id'] == 'SALON'
        assert rooms[0]['current_occupancy'] == 3


    def test_list_rooms_excluye_habitaciones_transito(self, client, mock_get_db):
        """Dada una petición GET a /rooms, cuando existen habitaciones de tránsito, entonces las excluye del resultado"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "name": "Salón", "poi_id": "p1", "current_occupancy": 0, "description": ""}
        ]
        
        response = client.get('/rooms')
        
        assert response.status_code == 200
        call_args = db.rooms.find.call_args[0][0]
        assert call_args.get("is_transit") == {"$ne": True}

    def test_list_rooms_habitaciones_vacias_retorna_lista_vacia(self, client, mock_get_db):
        """Dada una petición GET a /rooms, cuando no existen habitaciones, entonces retorna lista vacía"""
        db = mock_get_db
        db.rooms.find.return_value = []
        
        response = client.get('/rooms')
        
        assert response.status_code == 200
        assert response.json == []

    # GET /rooms/occupancy
    
    def test_occupancy_retorna_ocupacion_de_todas_habitaciones(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy, cuando existen habitaciones, entonces retorna diccionario room_id -> ocupación"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "current_occupancy": 3},
            {"_id": "COCINA", "current_occupancy": 1},
            {"_id": "HAB1", "current_occupancy": 0}
        ]
        
        response = client.get('/rooms/occupancy')
        
        assert response.status_code == 200
        occupancy = response.json
        assert occupancy["SALON"] == 3
        assert occupancy["COCINA"] == 1
        assert occupancy["HAB1"] == 0

    def test_occupancy_sin_habitaciones_retorna_vacio(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy, cuando no hay habitaciones, entonces retorna diccionario vacío"""
        db = mock_get_db
        db.rooms.find.return_value = []
        
        response = client.get('/rooms/occupancy')
        
        assert response.status_code == 200
        assert response.json == {}

    # GET /rooms/room_events
    
    def test_get_room_events_retorna_todos_eventos(self, client, mock_get_db):
        """Dada una petición GET a /rooms/room_events, cuando existen eventos, entonces retorna lista completa"""
        db = mock_get_db
        db.room_events.find.return_value = [
            {"user_id": "u1", "room_id": "SALON", "event": "enter", "timestamp": "2024-01-15T10:00:00Z"},
            {"user_id": "u2", "room_id": "COCINA", "event": "exit", "timestamp": "2024-01-15T10:05:00Z"}
        ]
        
        response = client.get('/rooms/room_events')
        
        assert response.status_code == 200
        events = response.json
        assert len(events) == 2
        assert events[0]["event"] == "enter"

    def test_get_room_events_vacio_retorna_lista_vacia(self, client, mock_get_db):
        """Dada una petición GET a /rooms/room_events, cuando no hay eventos, entonces retorna lista vacía"""
        db = mock_get_db
        db.room_events.find.return_value = []
        
        response = client.get('/rooms/room_events')
        
        assert response.status_code == 200
        assert response.json == []

    # GET /rooms/occupancy/at
    
    def test_occupancy_at_calcula_ocupacion_en_momento_concreto(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy/at con room_id y timestamp, cuando existen eventos previos, entonces calcula ocupación correcta"""
        db = mock_get_db
        at_time = "2024-01-15T10:30:00"
        
        db.room_events.find.return_value = [
            {"event": "enter"},
            {"event": "enter"},
            {"event": "exit"},
            {"event": "enter"}
        ]
        
        response = client.get(f'/rooms/occupancy/at?room_id=SALON&at={at_time}')
        
        assert response.status_code == 200
        assert response.json["room_id"] == "SALON"
        assert response.json["occupancy"] == 2  # 3 enters - 1 exit = 2

    def test_occupancy_at_falta_room_id_retorna_error(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy/at sin room_id, cuando se procesa, entonces retorna error 400"""
        response = client.get('/rooms/occupancy/at?at=2024-01-15T10:00:00')
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_occupancy_at_falta_at_retorna_error(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy/at sin timestamp, cuando se procesa, entonces retorna error 400"""
        response = client.get('/rooms/occupancy/at?room_id=SALON')
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_occupancy_at_fecha_invalida_retorna_error(self, client, mock_get_db):
        """Dada una petición GET a /rooms/occupancy/at con timestamp inválido, cuando se procesa, entonces retorna error 400"""
        response = client.get('/rooms/occupancy/at?room_id=SALON&at=fecha-invalida')
        
        assert response.status_code == 400
        assert 'error' in response.json

    # GET /rooms/visits/current
    
    def test_visits_current_retorna_numero_de_visitas_por_habitacion(self, client, mock_get_db):
        """Dada una petición GET a /rooms/visits/current, cuando existen habitaciones, entonces retorna conteo de entradas por habitación"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "name": "Salón"},
            {"_id": "COCINA", "name": "Cocina"}
        ]
        
        def count_side_effect(filter_dict):
            if filter_dict["room_id"] == "SALON":
                return 5
            return 3
        
        db.room_events.count_documents.side_effect = count_side_effect
        
        response = client.get('/rooms/visits/current')
        
        assert response.status_code == 200
        visits = response.json
        assert visits["SALON"]["visits"] == 5
        assert visits["COCINA"]["visits"] == 3

    def test_visits_current_sin_habitaciones_retorna_vacio(self, client, mock_get_db):
        """Dada una petición GET a /rooms/visits/current, cuando no hay habitaciones, entonces retorna diccionario vacío"""
        db = mock_get_db
        db.rooms.find.return_value = []
        
        response = client.get('/rooms/visits/current')
        
        assert response.status_code == 200
        assert response.json == {}

    # GET /rooms/visits/at
    
    def test_visits_at_retorna_visitas_hasta_fecha(self, client, mock_get_db):
        """Dada una petición GET a /rooms/visits/at con fecha, cuando existen habitaciones, entonces retorna conteo de entradas hasta esa fecha"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "name": "Salón"}
        ]
        db.room_events.count_documents.return_value = 10
        
        response = client.get('/rooms/visits/at?date=2024-01-15')
        
        assert response.status_code == 200
        assert response.json["SALON"]["visits"] == 10

    def test_visits_at_falta_fecha_retorna_error(self, client, mock_get_db):
        """Dada una petición GET a /rooms/visits/at sin fecha, cuando se procesa, entonces retorna error 400"""
        response = client.get('/rooms/visits/at')
        
        assert response.status_code == 400
        assert 'error' in response.json

    # GET /rooms/<room_id>/zones
    
    def test_get_zones_retorna_zonas_de_habitacion(self, client, mock_get_db):
        """Dada una petición GET a /rooms/<room_id>/zones, cuando la habitación tiene zonas, entonces retorna la lista"""
        db = mock_get_db
        db.room_zones.find.return_value = [
            {"zone_id": "zona1", "name": "Zona 1", "description": "Descripción 1"},
            {"zone_id": "zona2", "name": "Zona 2", "description": "Descripción 2"}
        ]
        
        response = client.get('/rooms/SALON/zones')
        
        assert response.status_code == 200
        zones = response.json
        assert len(zones) == 2

    def test_get_zones_habitacion_sin_zonas_retorna_lista_vacia(self, client, mock_get_db):
        """Dada una petición GET a /rooms/<room_id>/zones, cuando la habitación no tiene zonas, entonces retorna lista vacía"""
        db = mock_get_db
        db.room_zones.find.return_value = []
        
        response = client.get('/rooms/SALON/zones')
        
        assert response.status_code == 200
        assert response.json == []

    # GET /rooms/admin/list
    
    def test_admin_list_rooms_retorna_todas_habitaciones_con_conexiones(self, client, mock_get_db):
        """Dada una petición GET a /rooms/admin/list, cuando existen habitaciones, entonces retorna datos completos incluyendo conexiones"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {
                "_id": "SALON",
                "name": "Salón",
                "description": "Principal",
                "current_occupancy": 2,
                "is_transit": False,
                "poi_id": "poi123",
                "connections": ["ENTRADA", "PASILLO"]
            }
        ]
        
        response = client.get('/rooms/admin/list')
        
        assert response.status_code == 200
        rooms = response.json
        assert rooms[0]["room_id"] == "SALON"
        assert rooms[0]["connections"] == ["ENTRADA", "PASILLO"]

    # GET /rooms/<room_id>
    
    def test_get_room_retorna_habitacion_existente(self, client, mock_get_db):
        """Dada una petición GET a /rooms/<room_id>, cuando la habitación existe, entonces retorna sus datos completos"""
        db = mock_get_db
        db.rooms.find_one.return_value = {
            "_id": "SALON",
            "name": "Salón",
            "description": "Salón principal",
            "current_occupancy": 2,
            "is_transit": False,
            "poi_id": "poi123",
            "connections": ["ENTRADA"]
        }
        
        response = client.get('/rooms/SALON')
        
        assert response.status_code == 200
        room = response.json
        assert room["_id"] == "SALON"
        assert room["name"] == "Salón"

    def test_get_room_no_existente_retorna_404(self, client, mock_get_db):
        """Dada una petición GET a /rooms/<room_id>, cuando la habitación no existe, entonces retorna error 404"""
        db = mock_get_db
        db.rooms.find_one.return_value = None
        
        response = client.get('/rooms/INEXISTENTE')
        
        assert response.status_code == 404
        assert 'error' in response.json

    # PUT /rooms/<room_id> 
    
    def test_update_room_actualiza_campos_permitidos(self, client, mock_get_db):
        """Dada una petición PUT a /rooms/<room_id> con datos válidos, cuando la habitación existe, entonces actualiza los campos permitidos"""
        db = mock_get_db
        db.rooms.find_one.return_value = {"_id": "SALON", "name": "Salón Antiguo"}
        
        response = client.put('/rooms/SALON', json={
            "name": "Gran Salón",
            "description": "Descripción actualizada",
            "poi_id": "nuevo_poi",
            "is_transit": False,
            "campo_no_permitido": "ignorado"
        })
        
        assert response.status_code == 200
        # Verificar que solo se actualizaron campos permitidos
        update_call = db.rooms.update_one.call_args[0][1]
        assert "name" in update_call["$set"]
        assert "description" in update_call["$set"]
        assert "poi_id" in update_call["$set"]
        assert "campo_no_permitido" not in update_call["$set"]

    def test_update_room_sin_datos_retorna_error(self, client, mock_get_db):
        """Dada una petición PUT a /rooms/<room_id> sin datos, cuando se procesa, entonces retorna error 400"""
        db = mock_get_db
        db.rooms.find_one.return_value = {"_id": "SALON"}
        
        response = client.put('/rooms/SALON', json={})
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_update_room_no_existente_retorna_404(self, client, mock_get_db):
        """Dada una petición PUT a /rooms/<room_id>, cuando la habitación no existe, entonces retorna error 404"""
        db = mock_get_db
        db.rooms.find_one.return_value = None
        
        response = client.put('/rooms/INEXISTENTE', json={"name": "Nuevo nombre"})
        
        assert response.status_code == 404
        assert 'error' in response.json