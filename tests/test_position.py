import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime
from collections import deque, defaultdict

class TestPositionSystem:
    """Pruebas del sistema de posicionamiento con confirmación de 3 detecciones"""
        
    def test_add_pending_detection_mantiene_maxlen_tres(self, mock_get_db):
        """Dado un usuario y detecciones consecutivas, cuando se añaden más de 3, entonces se mantienen solo las 3 últimas"""
        from blueprints.position import add_pending_detection, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        for i in range(4):
            add_pending_detection(user_id, f"ROOM_{i}", 0.9, f"2024-01-15T10:00:{i:02d}Z")
        
        assert len(pending_detections[user_id]) == 3
        
        rooms = [d["room"] for d in pending_detections[user_id]]
        assert "ROOM_0" not in rooms
        assert "ROOM_1" in rooms
        assert "ROOM_2" in rooms
        assert "ROOM_3" in rooms

    def test_get_confirmed_room_tres_coincidencias_confirma_habitacion(self, mock_get_db):
        """Dadas tres detecciones de la misma habitación, cuando se verifica confirmación, entonces devuelve esa habitación"""
        from blueprints.position import add_pending_detection, get_confirmed_room, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "SALON", 0.85, "2024-01-15T10:00:05Z")
        add_pending_detection(user_id, "SALON", 0.95, "2024-01-15T10:00:10Z")
        
        confirmed = get_confirmed_room(user_id)
        assert confirmed == "SALON"

    def test_get_confirmed_room_dos_coincidencias_mayoria_confirma(self, mock_get_db):
        """Dadas tres detecciones con dos iguales y una distinta, cuando se verifica confirmación, entonces devuelve la habitación mayoritaria"""
        from blueprints.position import add_pending_detection, get_confirmed_room, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "COCINA", 0.8, "2024-01-15T10:00:05Z")
        add_pending_detection(user_id, "SALON", 0.95, "2024-01-15T10:00:10Z")
        
        confirmed = get_confirmed_room(user_id)
        assert confirmed == "SALON"

    def test_get_confirmed_room_todas_distintas_limpia_buffer(self, mock_get_db):
        """Dadas tres detecciones todas diferentes, cuando se verifica confirmación, entonces limpia el buffer y devuelve None"""
        from blueprints.position import add_pending_detection, get_confirmed_room, pending_detections, clear_pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "COCINA", 0.8, "2024-01-15T10:00:05Z")
        add_pending_detection(user_id, "HAB1", 0.85, "2024-01-15T10:00:10Z")
        
        confirmed = get_confirmed_room(user_id)
        assert confirmed is None
        assert len(pending_detections.get(user_id, [])) == 0

    def test_get_confirmed_room_detecciones_insuficientes_retorna_none(self, mock_get_db):
        """Dadas menos de tres detecciones, cuando se verifica confirmación, entonces devuelve None sin confirmar"""
        from blueprints.position import add_pending_detection, get_confirmed_room, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "SALON", 0.85, "2024-01-15T10:00:05Z")
        
        confirmed = get_confirmed_room(user_id)
        assert confirmed is None

    #  apply_room_update 
    
    def test_apply_room_update_usuario_nuevo_registra_entrada(self, app_context, mock_get_db):
        """Dado un usuario nuevo en habitación no tránsito, cuando se aplica actualización, entonces registra entrada y actualiza ocupación"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "new_user"
        detected_room = "SALON"
        confidence = 0.95
        timestamp = "2024-01-15T10:00:00Z"
        
        db.users_state.find_one.return_value = None
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        db.room_zones.find.return_value = []
        
        with patch('blueprints.position.check_low_occupancy_and_notify') as mock_check:
            result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        db.users_state.insert_one.assert_called_once()
        db.room_events.insert_one.assert_called_once()
        event = db.room_events.insert_one.call_args[0][0]
        assert event["event"] == "enter"
        assert event["room_id"] == "SALON"
        assert result["status"] == "ok"
        assert result["event"] == "enter"

    def test_apply_room_update_zona_transito_no_actualiza_ocupacion(self, mock_get_db):
        """Dado un usuario en zona de tránsito (PASILLO), cuando se aplica actualización, entonces no modifica la ocupación"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "user123"
        detected_room = "PASILLO"
        confidence = 0.95
        timestamp = "2024-01-15T10:00:00Z"
        
        db.users_state.find_one.return_value = None
        db.rooms.find_one.return_value = {"_id": "PASILLO", "is_transit": True}
        
        result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        # Verificar que no se actualizó ocupación
        db.rooms.update_one.assert_not_called()
        db.room_events.insert_one.assert_not_called()
        assert result["status"] == "ok"
        assert result["event"] == "transit"

    def test_apply_room_update_misma_habitacion_registra_stay(self, mock_get_db, sample_user_state):
        """Dado un usuario que permanece en la misma habitación, cuando se aplica actualización, entonces registra stay sin cambiar ocupación"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "user123"
        detected_room = "SALON"
        confidence = 0.95
        timestamp = "2024-01-15T10:05:00Z"
        
        db.users_state.find_one.return_value = sample_user_state
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        
        result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        # Verificar actualización con evento stay
        db.users_state.update_one.assert_called_once()
        update_call = db.users_state.update_one.call_args[0][1]
        assert update_call["$set"]["last_event"] == "stay"
        # Verificar que no se insertó evento ni se modificó ocupación
        db.room_events.insert_one.assert_not_called()
        db.rooms.update_one.assert_not_called()
        assert result["event"] == "stay"

    def test_apply_room_update_cambio_habitacion_registra_exit_y_enter(self, app_context, mock_get_db, sample_user_state):
        """Dado un usuario que cambia de habitación, cuando se aplica actualización, entonces registra exit de la anterior y enter de la nueva"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "user123"
        detected_room = "COCINA"
        confidence = 0.95
        timestamp = "2024-01-15T10:05:00Z"
        
        sample_user_state["current_room"] = "SALON"
        db.users_state.find_one.return_value = sample_user_state
        
        # Usar return_value en lugar de side_effect para evitar StopIteration
        db.rooms.find_one.return_value = {"_id": "COCINA", "is_transit": False}
        
        with patch('blueprints.position.is_transit_room', return_value=False):
            with patch('blueprints.position.check_low_occupancy_and_notify') as mock_check:
                result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        assert db.room_events.insert_one.call_count == 2
        calls = db.room_events.insert_one.call_args_list
        exit_event = calls[0][0][0]
        enter_event = calls[1][0][0]
        assert exit_event["event"] == "exit"
        assert exit_event["room_id"] == "SALON"
        assert enter_event["event"] == "enter"
        assert enter_event["room_id"] == "COCINA"
        
        assert result["event"] == "room_changed"

    def test_apply_room_update_habitacion_no_existe_retorna_error(self, mock_get_db):
        """Dada una habitación que no existe en la base de datos, cuando se aplica actualización, entonces retorna error 404"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "user123"
        detected_room = "HABITACION_INEXISTENTE"
        confidence = 0.95
        timestamp = "2024-01-15T10:00:00Z"
        
        db.rooms.find_one.return_value = None
        
        result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        assert "error" in result
        assert status == 404


    def test_update_user_heartbeat_actualiza_timestamp(self, mock_get_db):
        """Dado un usuario existente, cuando se actualiza su heartbeat, entonces se guarda el nuevo timestamp"""
        from blueprints.position import update_user_heartbeat, user_heartbeat
        
        user_heartbeat.clear()
        user_id = "user123"
        timestamp = "2024-01-15T10:00:00Z"
        
        update_user_heartbeat(user_id, timestamp)
        
        assert user_heartbeat[user_id] == timestamp

    def test_heartbeat_endpoint_actualiza_actividad(self, client, mock_get_db):
        """Dada una petición POST a /position/heartbeat, cuando se envía un user_id válido, entonces actualiza el timestamp del usuario"""
        from blueprints.position import user_heartbeat
        
        user_heartbeat.clear()
        
        response = client.post('/position/heartbeat', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'ok'
        assert 'user123' in user_heartbeat

    def test_heartbeat_endpoint_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /position/heartbeat sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.post('/position/heartbeat', json={})
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_is_transit_room_identifica_correctamente(self, mock_get_db):
        """Dada una habitación, cuando se verifica si es tránsito, entonces retorna True si is_transit=True"""
        from blueprints.position import is_transit_room
        
        db = mock_get_db
        db.rooms.find_one.return_value = {"_id": "PASILLO", "is_transit": True}
        
        assert is_transit_room(db, "PASILLO") is True

    def test_is_transit_room_retorna_false_si_no_transito(self, mock_get_db):
        """Dada una habitación normal, cuando se verifica si es tránsito, entonces retorna False"""
        from blueprints.position import is_transit_room
        
        db = mock_get_db
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        
        assert is_transit_room(db, "SALON") is False

    # --------------------------------
    def test_clear_pending_detections_limpia_buffer_usuario(self, mock_get_db):
        """Dado un usuario con detecciones pendientes, cuando se limpia, entonces el buffer queda vacío"""
        from blueprints.position import add_pending_detection, clear_pending_detections, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "SALON", 0.85, "2024-01-15T10:00:05Z")
        
        assert len(pending_detections[user_id]) == 2
        
        clear_pending_detections(user_id)
        
        assert len(pending_detections.get(user_id, [])) == 0

    def test_get_confirmed_room_limpia_buffer_cuando_no_coincide(self, mock_get_db):
        """Dadas detecciones inconsistentes, cuando se verifica, entonces limpia el buffer"""
        from blueprints.position import add_pending_detection, get_confirmed_room, pending_detections
        
        pending_detections.clear()
        user_id = "user123"
        
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "COCINA", 0.85, "2024-01-15T10:00:05Z")
        add_pending_detection(user_id, "HAB1", 0.80, "2024-01-15T10:00:10Z")
        
        confirmed = get_confirmed_room(user_id)
        
        assert confirmed is None
        assert len(pending_detections.get(user_id, [])) == 0

    def test_apply_room_update_usuario_nuevo_con_check_low_occupancy(self, app_context, mock_get_db):
        """Verifica que check_low_occupancy_and_notify sea llamado"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "new_user"
        detected_room = "SALON"
        confidence = 0.95
        timestamp = "2024-01-15T10:00:00Z"
        
        db.users_state.find_one.return_value = None
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        db.room_zones.find.return_value = []
        
        with patch('blueprints.position.check_low_occupancy_and_notify') as mock_check:
            result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        mock_check.assert_called_once()
        assert result["status"] == "ok"

    def test_apply_room_update_cambio_habitacion_sin_transito(self, app_context, mock_get_db, sample_user_state):
        """Cambio de habitación verificando que is_transit_room se llama correctamente"""
        from blueprints.position import apply_room_update
        
        db = mock_get_db
        user_id = "user123"
        detected_room = "COCINA"
        confidence = 0.95
        timestamp = "2024-01-15T10:05:00Z"
        
        sample_user_state["current_room"] = "SALON"
        db.users_state.find_one.return_value = sample_user_state
        
        db.rooms.find_one.return_value = {"_id": "COCINA", "is_transit": False}
        
        with patch('blueprints.position.is_transit_room', return_value=False):
            with patch('blueprints.position.check_low_occupancy_and_notify') as mock_check:
                result, status = apply_room_update(db, user_id, detected_room, confidence, timestamp)
        
        assert result["event"] == "room_changed"
        assert db.rooms.update_one.call_count == 2

    def test_check_low_occupancy_and_notify_maneja_errores(self, app_context, mock_get_db):
        """Verifica que check_low_occupancy_and_notify maneja errores de red silenciosamente"""
        from blueprints.position import check_low_occupancy_and_notify
        
        db = mock_get_db
        db.rooms.find_one.return_value = {"_id": "SALON", "current_occupancy": 5}
        
        with patch('blueprints.position.requests.get') as mock_get:
            mock_get.side_effect = Exception("Network error")
            # No debe lanzar excepción
            check_low_occupancy_and_notify(db, "user123", "SALON")

    def test_cleanup_inactive_users_elimina_usuarios_inactivos(self, mock_get_db):
        """Verifica que cleanup_inactive_users elimina usuarios sin heartbeat reciente"""
        from blueprints.position import cleanup_inactive_users, user_heartbeat, confirmed_positions, pending_detections
        from datetime import datetime, timezone, timedelta
        
        db = mock_get_db
        user_heartbeat.clear()
        confirmed_positions.clear()
        pending_detections.clear()
        
        now = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        old_time = now - timedelta(days=14)
        new_time = now - timedelta(seconds=30)
        
        timestamp_old = old_time.isoformat()
        timestamp_new = new_time.isoformat()
        
        user_heartbeat["user_old"] = timestamp_old
        user_heartbeat["user_new"] = timestamp_new
        confirmed_positions["user_old"] = "SALON"
        
        db.users_state.find_one.return_value = {"current_room": "SALON"}
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        
        with patch('blueprints.position.datetime') as mock_datetime:
            mock_datetime.now.return_value = now
            
            def fromisoformat_side_effect(date_string):
                return datetime.fromisoformat(date_string)
            mock_datetime.fromisoformat.side_effect = fromisoformat_side_effect
            
            with patch('blueprints.position.HEARTBEAT_TIMEOUT_SECONDS', 60):
                with patch('blueprints.position.now_iso', return_value=now.isoformat()):
                    cleanup_inactive_users(db)
        
        assert "user_old" not in user_heartbeat, "Usuario inactivo debería ser eliminado"
        assert "user_new" in user_heartbeat, "Usuario activo debería permanecer"

    def test_position_bp_force_start_endpoint(self, client, mock_get_db):
        """Prueba el endpoint /position/force_start (aunque esté en desuso)"""
        db = mock_get_db
        db.users_state.find_one.return_value = None
        db.rooms.find_one.return_value = {"_id": "ENTRADA", "is_transit": False}
        
        response = client.post('/position/force_start', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'ok'

    def test_position_bp_update_endpoint(self, client, mock_get_db):
        """Prueba el endpoint /position/update"""
        db = mock_get_db
        db.users_state.find_one.return_value = None
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        db.room_zones.find.return_value = []
        
        with patch('blueprints.position.check_low_occupancy_and_notify'):
            response = client.post('/position/update', json={
                'user_id': 'user123',
                'detected_room': 'SALON',
                'confidence': 0.95
            })
        
        assert response.status_code == 200

    def test_position_bp_update_endpoint_faltan_datos(self, client, mock_get_db):
        """Prueba el endpoint /position/update con datos faltantes"""
        response = client.post('/position/update', json={
            'user_id': 'user123'
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_start_cleanup_thread_inicia_hilo(self, mock_get_db):
        """Verifica que start_cleanup_thread inicia el hilo de limpieza"""
        import blueprints.position as position_module
        from blueprints.position import start_cleanup_thread

        position_module._cleanup_thread_started = False

        db = mock_get_db
        start_cleanup_thread(db)

        assert position_module._cleanup_thread_started is True
    