import pytest
from unittest.mock import patch, MagicMock

class TestIntegration:
    """Pruebas de integración entre componentes"""
    
    def test_flujo_completo_deteccion_y_ruta(self, client, mock_get_db, app_context):
        """
        Dado un usuario que entra al sistema, cuando se detecta su posición y se genera una ruta,
        entonces el sistema completa todo el flujo correctamente
        """
        db = mock_get_db
        user_id = "user_integration"
        
        db.rooms.find.return_value = [
            {"_id": "ENTRADA", "beacons": [{"id": "BEACON_ENTRADA"}]}
        ]
        db.rooms.find_one.return_value = {"_id": "ENTRADA", "is_transit": False}
        db.users_state.find_one.return_value = None
        db.pois.find_one.return_value = {"puid": "poi_test", "x": 10, "y": 20, "floor": 0}
        
        from blueprints.position import pending_detections, add_pending_detection
        pending_detections.clear()
        
        for i in range(3):
            add_pending_detection(user_id, "ENTRADA", 0.9, f"2024-01-15T10:00:0{i}Z")
        
        with patch('blueprints.position.get_confirmed_room', return_value="ENTRADA"):
            with patch('blueprints.position.apply_room_update') as mock_apply:
                mock_apply.return_value = ({"status": "ok", "room": "ENTRADA"}, 200)
                
                response = client.post('/sensors/update_position', json={
                    'user_id': user_id,
                    'sensors': [
                        {"sensor_id": "BEACON_ENTRADA", "rssi": -55},
                        {"sensor_id": "BEACON_SALON", "rssi": -65}
                    ]
                })
                
                assert response.status_code == 200
        
        db.users_state.find_one.return_value = {
            "user_id": user_id,
            "current_room": "ENTRADA"
        }
        
        with patch('blueprints.routes.build_room_graph') as mock_graph:
            mock_graph.return_value = (
                {"ENTRADA": ["PASILLO"], "PASILLO": ["ENTRADA", "SALON"], "SALON": ["PASILLO"]},
                {"PASILLO"}
            )
            with patch('blueprints.routes.rooms_to_pois', return_value=["poi1", "poi2"]):
                with patch('blueprints.routes.pois_with_coords', return_value=[]):
                    response = client.post('/routes/auto/bfs', json={'user_id': user_id})
                    assert response.status_code == 200
                    assert response.json['status'] == 'ok'

    def test_flujo_completo_asignacion_y_progreso_ruta(self, client, mock_get_db):
        """
        Dado un usuario con ruta asignada, cuando avanza por las habitaciones,
        entonces el sistema actualiza su progreso correctamente
        """
        db = mock_get_db
        
        route_id = "test_route_123"
        
        db.routes.find_one.return_value = {"_id": route_id, "name": "Ruta Test"}
        db.user_routes.update_one.return_value = None
        
        assign_response = client.post('/routes/assign', json={
            'user_id': 'user123',
            'route_id': route_id
        })
        assert assign_response.status_code == 200
        
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": route_id,
            "current_step": 0,
            "completed": False
        }
        db.routes.find_one.return_value = {
            "_id": route_id,
            "steps": [
                {"room_id": "ENTRADA", "poi_id": "poi1"},
                {"room_id": "SALON", "poi_id": "poi2"},
                {"room_id": "COCINA", "poi_id": "poi3"}
            ]
        }
        
        next_response = client.get('/routes/user/user123/next')
        assert next_response.status_code == 200
        assert next_response.json['next_room'] == 'ENTRADA'
        
        progress_response = client.post('/routes/progress', json={
            'user_id': 'user123',
            'room_id': 'ENTRADA'
        })
        assert progress_response.status_code == 200
        assert progress_response.json['current_step'] == 1
        
        db.user_routes.find_one.return_value = {
            "user_id": "user123",
            "route_id": route_id,
            "current_step": 1,
            "completed": False
        }
        
        next_response2 = client.get('/routes/user/user123/next')
        assert next_response2.status_code == 200
        assert next_response2.json['next_room'] == 'SALON'

    def test_flujo_completo_deteccion_con_zona(self, client, mock_get_db):
        """
        Dado un usuario en una habitación con zonas, cuando se detecta su posición,
        entonces el sistema identifica también la zona
        """
        db = mock_get_db
        
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}
        ]
        db.room_zones.find.return_value = [
            {"zone_id": "sofa", "name": "Zona Sofá"},
            {"zone_id": "mesa", "name": "Zona Mesa"}
        ]
        
        with patch('blueprints.sensors.heuristic_room_override') as mock_heuristic:
            mock_heuristic.return_value = "SALON"
            
            response = client.post('/sensors/detect_once', json={
                'user_id': 'user123',
                'sensors': [
                    {"sensor_id": "BEACON_SALON", "rssi": -55},
                    {"sensor_id": "BEACON_COCINA", "rssi": -65}
                ]
            })
            
            assert response.status_code == 200
            assert response.json['room'] is not None

            mock_heuristic.assert_called_once()