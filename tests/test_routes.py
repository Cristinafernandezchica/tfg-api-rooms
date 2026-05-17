import pytest
from unittest.mock import patch, MagicMock, PropertyMock

class TestRoutesEndpoints:
    """Pruebas de los endpoints de generación de rutas"""
        
    def test_build_room_graph_construye_grafo_correctamente(self, mock_get_db):
        """Dada una lista de habitaciones con conexiones, cuando se construye el grafo, entonces crea estructura de adyacencia"""
        from blueprints.routes import build_room_graph
        
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "connections": ["ENTRADA", "PASILLO"], "is_transit": False},
            {"_id": "ENTRADA", "connections": ["SALON"], "is_transit": False},
            {"_id": "PASILLO", "connections": ["SALON", "COCINA"], "is_transit": True}
        ]
        
        graph, transit_rooms = build_room_graph(db)
        
        assert "SALON" in graph
        assert graph["SALON"] == ["ENTRADA", "PASILLO"]
        assert "PASILLO" in transit_rooms
        assert "ENTRADA" not in transit_rooms

    def test_bfs_recorre_grafo_en_orden_correcto(self, mock_get_db):
        """Dado un grafo y un nodo inicio, cuando se ejecuta BFS, entonces visita nodos por niveles"""
        from blueprints.routes import bfs
        
        graph = {
            "A": ["B", "C"],
            "B": ["A", "D"],
            "C": ["A", "D"],
            "D": ["B", "C"]
        }
        
        order = bfs(graph, "A")
        
        assert order[0] == "A"
        assert order.index("B") < order.index("D") or order.index("C") < order.index("D")

    def test_dfs_recorre_grafo_profundidad(self, mock_get_db):
        """Dado un grafo y un nodo inicio, cuando se ejecuta DFS, entonces visita en profundidad primero"""
        from blueprints.routes import dfs
        
        graph = {
            "A": ["B", "C"],
            "B": ["A", "D"],
            "C": ["A", "D"],
            "D": ["B", "C"]
        }
        
        order = dfs(graph, "A")
        
        assert order[0] == "A"

    def test_bfs_with_transit_encuentra_camino_con_pasillo_obligatorio(self, mock_get_db):
        """Dado un grafo con zonas de tránsito, cuando se busca ruta entre dos habitaciones, 
           entonces incluye las zonas de tránsito necesarias"""
        from blueprints.routes import bfs_with_transit
        
        graph = {
            "ENTRADA": ["PASILLO"],
            "PASILLO": ["ENTRADA", "SALON", "COCINA"],
            "SALON": ["PASILLO"],
            "COCINA": ["PASILLO"]
        }
        transit_rooms = {"PASILLO"}
        
        path = bfs_with_transit(graph, "ENTRADA", "COCINA", transit_rooms)
        
        assert path == ["ENTRADA", "PASILLO", "COCINA"] or path == ["ENTRADA", "PASILLO", "COCINA"]

    def test_bfs_with_transit_mismo_origen_destino(self, mock_get_db):
        """Dado un origen y destino iguales, cuando se busca ruta, entonces retorna lista con un solo elemento"""
        from blueprints.routes import bfs_with_transit
        
        path = bfs_with_transit({}, "SALON", "SALON", set())
        
        assert path == ["SALON"]

    def test_expand_transit_points_agrega_pasillo_cuando_es_necesario(self, mock_get_db):
        """Dada una ruta que salta entre habitaciones sin pasillo, cuando se expande, entonces inserta PASILLO entre ellas"""
        from blueprints.routes import expand_transit_points
        
        room_route = ["ENTRADA", "SALON", "COCINA"]
        transit_rooms = {"PASILLO"}
        
        expanded = expand_transit_points(room_route, transit_rooms)
        
        # Debe insertar PASILLO entre SALON y COCINA
        assert "PASILLO" in expanded

    def test_rooms_to_pois_convierte_habitaciones_a_pois(self, mock_get_db):
        """Dada una lista de habitaciones, cuando se convierten a POIs, entonces retorna los IDs correspondientes"""
        from blueprints.routes import rooms_to_pois
        
        db = mock_get_db
        
        # Usar return_value con side_effect para devolver diferentes valores
        db.rooms.find_one.side_effect = [
            {"poi_id": "poi_SALON"},
            {"poi_id": "poi_COCINA"},
            {"poi_id": "poi_HAB1"}
        ]
        
        pois = rooms_to_pois(db, ["SALON", "COCINA", "HAB1"])
        
        assert pois == ["poi_SALON", "poi_COCINA", "poi_HAB1"]
        assert db.rooms.find_one.call_count == 3

    #  POST /routes/auto/<algorithm> 
    
    def test_create_auto_route_con_bfs_retorna_ruta_desde_posicion_confirmada(self, client, mock_get_db, sample_user_state):
        """Dada una petición POST a /routes/auto/bfs con usuario con posición, cuando se genera ruta, entonces retorna camino desde su posición actual"""
        db = mock_get_db
        db.users_state.find_one.return_value = sample_user_state
        
        # Mock del grafo
        db.rooms.find.side_effect = [
            [
                {"_id": "SALON", "connections": ["PASILLO"], "is_transit": False},
                {"_id": "ENTRADA", "connections": ["PASILLO"], "is_transit": False},
                {"_id": "PASILLO", "connections": ["SALON", "ENTRADA"], "is_transit": True}
            ],
            [ 
                {"_id": "SALON"},
                {"_id": "ENTRADA"}
            ]
        ]
        
        db.rooms.find_one.return_value = {"poi_id": "poi_test"}
        db.routes.insert_one.return_value = None
        db.pois.find_one.return_value = {"puid": "poi_test", "x": 10, "y": 20, "floor": 0}
        
        response = client.post('/routes/auto/bfs', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'ok'
        assert data['algorithm'] == 'bfs'
        assert data['start_room'] == 'SALON'
        assert 'rooms' in data
        assert 'poi_ids' in data

    def test_create_auto_route_con_force_start_true(self, client, mock_get_db):
        """Dada una petición POST a /routes/auto/bfs con force_start=True, cuando se genera ruta, entonces comienza desde ENTRADA"""
        db = mock_get_db
        
        db.rooms.find.side_effect = [
            [{"_id": "ENTRADA", "connections": ["PASILLO"], "is_transit": False}],
            [{"_id": "ENTRADA"}, {"_id": "SALON"}]
        ]
        db.rooms.find_one.return_value = {"poi_id": "poi_test"}
        db.pois.find_one.return_value = {"puid": "poi_test", "x": 10, "y": 20, "floor": 0}
        
        response = client.post('/routes/auto/bfs', json={
            'user_id': 'user123',
            'force_start': True
        })
        
        assert response.status_code == 200
        assert response.json['start_room'] == 'ENTRADA'

    def test_create_auto_route_usuario_sin_posicion_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /routes/auto/bfs con usuario sin posición confirmada, cuando se procesa, entonces retorna error 404"""
        db = mock_get_db
        db.users_state.find_one.return_value = None
        
        response = client.post('/routes/auto/bfs', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 404
        assert 'error' in response.json

    def test_create_auto_route_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /routes/auto/bfs sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.post('/routes/auto/bfs', json={})
        
        assert response.status_code == 400
        assert 'error' in response.json

    #  GET /routes/<route_id> 
    
    def test_get_route_retorna_ruta_existente(self, client, mock_get_db):
        """Dada una petición GET a /routes/<route_id>, cuando la ruta existe, entonces retorna sus datos"""
        db = mock_get_db
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "name": "Ruta de prueba",
            "description": "Descripción",
            "steps": [{"room_id": "SALON", "poi_id": "poi1"}],
            "created_at": "2024-01-15T10:00:00Z"
        }
        
        response = client.get('/routes/route_123')
        
        assert response.status_code == 200
        data = response.json
        assert data['route_id'] == 'route_123'
        assert data['name'] == 'Ruta de prueba'

    def test_get_route_no_existente_retorna_404(self, client, mock_get_db):
        """Dada una petición GET a /routes/<route_id>, cuando la ruta no existe, entonces retorna error 404"""
        db = mock_get_db
        db.routes.find_one.return_value = None
        
        response = client.get('/routes/inexistente')
        
        assert response.status_code == 404
        assert 'error' in response.json

    #  POST /routes/assign 
    
    def test_assign_route_asigna_ruta_a_usuario(self, client, mock_get_db):
        """Dada una petición POST a /routes/assign con user_id y route_id válidos, cuando la ruta existe, entonces asigna al usuario"""
        db = mock_get_db
        db.routes.find_one.return_value = {"_id": "route_123", "name": "Ruta"}
        
        response = client.post('/routes/assign', json={
            'user_id': 'user123',
            'route_id': 'route_123'
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'ok'
        db.user_routes.update_one.assert_called_once()

    def test_assign_route_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /routes/assign sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.post('/routes/assign', json={
            'route_id': 'route_123'
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_assign_route_ruta_no_existente_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /routes/assign, cuando la ruta no existe, entonces retorna error 404"""
        db = mock_get_db
        db.routes.find_one.return_value = None
        
        response = client.post('/routes/assign', json={
            'user_id': 'user123',
            'route_id': 'inexistente'
        })
        
        assert response.status_code == 404
        assert 'error' in response.json

    #  GET /routes/user/<user_id> 
    
    def test_get_user_route_retorna_ruta_asignada(self, client, mock_get_db):
        """Dada una petición GET a /routes/user/<user_id>, cuando el usuario tiene ruta asignada, entonces retorna la ruta y el progreso"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 2,
            "completed": False,
            "assigned_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:05:00Z"
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "name": "Ruta",
            "steps": [{"room_id": "r1"}, {"room_id": "r2"}, {"room_id": "r3"}]
        }
        
        response = client.get('/routes/user/user123')
        
        assert response.status_code == 200
        data = response.json
        assert data['user_route']['current_step'] == 2
        assert data['user_route']['completed'] is False
        assert len(data['route']['steps']) == 3

    def test_get_user_route_sin_ruta_retorna_404(self, client, mock_get_db):
        """Dada una petición GET a /routes/user/<user_id>, cuando el usuario no tiene ruta asignada, entonces retorna error 404"""
        db = mock_get_db
        db.user_routes.find_one.return_value = None
        
        response = client.get('/routes/user/user123')
        
        assert response.status_code == 404
        assert 'error' in response.json

    #  POST /routes/progress 
    
    def test_update_progress_avanza_paso_correcto(self, client, mock_get_db):
        """Dada una petición POST a /routes/progress cuando el usuario llega a la habitación esperada, entonces avanza al siguiente paso"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 0
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "steps": [
                {"room_id": "SALON", "poi_id": "poi1"},
                {"room_id": "COCINA", "poi_id": "poi2"}
            ]
        }
        
        response = client.post('/routes/progress', json={
            'user_id': 'user123',
            'room_id': 'SALON'
        })
        
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'ok'
        assert data['current_step'] == 1
        assert data['completed'] is False
        
        update_call = db.user_routes.update_one.call_args[0][1]
        assert update_call["$set"]["current_step"] == 1

    def test_update_progress_completa_ruta_al_ultimo_paso(self, client, mock_get_db):
        """Dada una petición POST a /routes/progress cuando el usuario completa el último paso, entonces marca la ruta como completada"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 1
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "steps": [
                {"room_id": "SALON", "poi_id": "poi1"},
                {"room_id": "COCINA", "poi_id": "poi2"}
            ]
        }
        
        response = client.post('/routes/progress', json={
            'user_id': 'user123',
            'room_id': 'COCINA'
        })
        
        assert response.status_code == 200
        data = response.json
        assert data['completed'] is True
        
        update_call = db.user_routes.update_one.call_args[0][1]
        assert update_call["$set"]["completed"] is True

    def test_update_progress_habitacion_incorrecta_no_avanza(self, client, mock_get_db):
        """Dada una petición POST a /routes/progress cuando el usuario llega a habitación equivocada, entonces retorna mismatch sin avanzar"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 0
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "steps": [{"room_id": "SALON", "poi_id": "poi1"}]
        }
        
        response = client.post('/routes/progress', json={
            'user_id': 'user123',
            'room_id': 'COCINA'
        })
        
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'mismatch'
        assert data['expected_room'] == 'SALON'
        assert data['reached_room'] == 'COCINA'
        
        db.user_routes.update_one.assert_not_called()

    #  GET /routes 
    
    def test_list_routes_retorna_todas_rutas(self, client, mock_get_db):
        """Dada una petición GET a /routes, cuando existen rutas, entonces retorna la lista"""
        db = mock_get_db
        db.routes.find.return_value = [
            {"_id": "r1", "name": "Ruta 1", "created_at": "2024-01-15T10:00:00Z", "steps": []},
            {"_id": "r2", "name": "Ruta 2", "created_at": "2024-01-15T11:00:00Z", "steps": []}
        ]
        
        response = client.get('/routes')
        
        assert response.status_code == 200
        routes = response.json
        assert len(routes) == 2


    #  DELETE /routes/<route_id> 
    
    def test_delete_route_elimina_ruta_existente(self, client, mock_get_db):
        """Dada una petición DELETE a /routes/<route_id>, cuando la ruta existe, entonces la elimina"""
        db = mock_get_db
        db.routes.delete_one.return_value.deleted_count = 1
        
        response = client.delete('/routes/route_123')
        
        assert response.status_code == 200
        assert response.json['status'] == 'deleted'

    def test_delete_route_no_existente_retorna_404(self, client, mock_get_db):
        """Dada una petición DELETE a /routes/<route_id>, cuando la ruta no existe, entonces retorna error 404"""
        db = mock_get_db
        db.routes.delete_one.return_value.deleted_count = 0
        
        response = client.delete('/routes/inexistente')
        
        assert response.status_code == 404
        assert 'error' in response.json

    #  POST /routes/reset_user 
    
    def test_reset_user_route_elimina_ruta_asignada(self, client, mock_get_db):
        """Dada una petición POST a /routes/reset_user, cuando el usuario tiene ruta, entonces elimina la asignación"""
        db = mock_get_db
        
        response = client.post('/routes/reset_user', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'reset'
        db.user_routes.delete_one.assert_called_with({"user_id": "user123"})

    #  GET /routes/user/<user_id>/next 
    
    def test_get_next_step_retorna_siguiente_estancia(self, client, mock_get_db):
        """Dada una petición GET a /routes/user/<user_id>/next, cuando hay ruta activa, entonces retorna la siguiente habitación"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 0
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "steps": [
                {"room_id": "SALON", "poi_id": "poi1"},
                {"room_id": "COCINA", "poi_id": "poi2"}
            ]
        }
        
        response = client.get('/routes/user/user123/next')
        
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'ok'
        assert data['next_room'] == 'SALON'
        assert data['next_poi'] == 'poi1'

    def test_get_next_step_ruta_completada_retorna_completed(self, client, mock_get_db):
        """Dada una petición GET a /routes/user/<user_id>/next, cuando la ruta está completada, entonces retorna estado completed"""
        db = mock_get_db
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": "route_123",
            "current_step": 2
        }
        db.routes.find_one.return_value = {
            "_id": "route_123",
            "steps": [{"room_id": "SALON", "poi_id": "poi1"}]
        }
        
        response = client.get('/routes/user/user123/next')
        
        assert response.status_code == 200
        assert response.json['status'] == 'completed'

    # ---------------------------------------------

    def test_pois_with_coords_filtra_pois_sin_coordenadas(self, mock_get_db):
        """Verifica que pois_with_coords filtra POIs sin coordenadas"""
        from blueprints.routes import pois_with_coords
        
        db = mock_get_db
        
        def find_one_side_effect(filter_dict):
            if filter_dict["puid"] == "poi_con_coords":
                return {"puid": "poi_con_coords", "x": 10, "y": 20, "floor": 1}
            return None
        
        db.pois.find_one.side_effect = find_one_side_effect
        
        result = pois_with_coords(db, ["poi_con_coords", "poi_sin_coords"])
        
        assert len(result) == 1
        assert result[0]["puid"] == "poi_con_coords"

    def test_create_auto_route_con_algorithmo_dfs(self, client, mock_get_db, sample_user_state):
        """Prueba generación de ruta con algoritmo DFS"""
        db = mock_get_db
        db.users_state.find_one.return_value = sample_user_state
        
        db.rooms.find.side_effect = [
            [
                {"_id": "SALON", "connections": ["PASILLO"], "is_transit": False},
                {"_id": "ENTRADA", "connections": ["PASILLO"], "is_transit": False},
                {"_id": "PASILLO", "connections": ["SALON", "ENTRADA"], "is_transit": True}
            ],
            [{"_id": "SALON"}, {"_id": "ENTRADA"}]
        ]
        
        db.rooms.find_one.return_value = {"poi_id": "poi_test"}
        db.routes.insert_one.return_value = None
        db.pois.find_one.return_value = {"puid": "poi_test", "x": 10, "y": 20, "floor": 0}
        
        response = client.post('/routes/auto/dfs', json={'user_id': 'user123'})
        
        assert response.status_code == 200
        assert response.json['algorithm'] == 'dfs'

    def test_delete_route_elimina_ruta_existente(self, client, mock_get_db):
        """Prueba eliminación de ruta existente"""
        db = mock_get_db
        db.routes.delete_one.return_value.deleted_count = 1
        
        response = client.delete('/routes/route_123')
        
        assert response.status_code == 200
        assert response.json['status'] == 'deleted'

    def test_bfs_with_transit_sin_camino(self, mock_get_db):
        """Prueba BFS con tránsito cuando no hay camino"""
        from blueprints.routes import bfs_with_transit
        
        graph = {
            "A": ["B"],
            "B": ["A"],
            "C": ["D"],
            "D": ["C"]
        }
        transit_rooms = set()
        
        path = bfs_with_transit(graph, "A", "C", transit_rooms)
        
        # No hay conexión entre A y C
        assert path == ["A"]

    def test_expand_transit_points_ruta_vacia(self, mock_get_db):
        """Prueba expand_transit_points con ruta vacía"""
        from blueprints.routes import expand_transit_points
        
        result = expand_transit_points([], {"PASILLO"})
        
        assert result == []

    def test_expand_transit_points_sin_transito_necesario(self, mock_get_db):
        """Prueba expand_transit_points cuando no se necesita insertar tránsito"""
        from blueprints.routes import expand_transit_points
        
        room_route = ["ENTRADA", "PASILLO", "SALON"]
        transit_rooms = {"PASILLO"}
        
        expanded = expand_transit_points(room_route, transit_rooms)
        
        # No debe insertar PASILLO adicional
        assert expanded == room_route

    def test_rooms_to_pois_con_habitacion_sin_poi(self, mock_get_db):
        """Prueba rooms_to_pois cuando una habitación no tiene POI"""
        from blueprints.routes import rooms_to_pois
        
        db = mock_get_db
        
        db.rooms.find_one.side_effect = [
            {"poi_id": "poi1"},
            None,  # Habitación sin POI
            {"poi_id": "poi3"}
        ]
        
        pois = rooms_to_pois(db, ["HAB1", "HAB2", "HAB3"])
        
        # Solo debe incluir las que tienen POI
        assert pois == ["poi1", "poi3"]