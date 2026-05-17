import pytest
from unittest.mock import patch, MagicMock, call
from collections import deque, defaultdict

class TestSensorsEndpoints:
    """Pruebas de los endpoints de detección por sensores"""
        
    def test_build_sensor_room_map_construye_mapa_correctamente(self, mock_get_db):
        """Dada una lista de habitaciones con beacons, cuando se construye el mapa, entonces asocia cada beacon a su habitación"""
        from blueprints.sensors import build_sensor_room_map
        
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "B1"}, {"id": "B2"}]},
            {"_id": "COCINA", "beacons": [{"id": "B3"}]}
        ]
        
        mapping = build_sensor_room_map(db)
        
        assert mapping["B1"] == "SALON"
        assert mapping["B2"] == "SALON"
        assert mapping["B3"] == "COCINA"

    def test_normalize_rssi_limita_entre_menos_100_y_menos_40(self, mock_get_db):
        """Dado un valor RSSI, cuando se normaliza, entonces se limita entre -100 y -40"""
        from blueprints.sensors import normalize_rssi
        
        assert normalize_rssi(-30) == -40
        assert normalize_rssi(-50) == -50
        assert normalize_rssi(-120) == -100
        assert normalize_rssi(None) == -100

    def test_heuristic_confidence_calcula_confianza_segun_rssi_y_cantidad(self, mock_get_db):
        """Dada una lista de sensores, cuando se calcula la confianza, entonces considera número de sensores y mejor RSSI"""
        from blueprints.sensors import heuristic_confidence
        
        sensors = [
            {"sensor_id": "B1", "rssi": -50},
            {"sensor_id": "B2", "rssi": -55},
            {"sensor_id": "B3", "rssi": -60}
        ]
        
        confidence = heuristic_confidence(sensors)

        assert 0.7 <= confidence <= 0.72

    def test_heuristic_confidence_sensores_vacios_retorna_cero(self, mock_get_db):
        """Dada una lista vacía de sensores, cuando se calcula la confianza, entonces retorna 0"""
        from blueprints.sensors import heuristic_confidence
        
        assert heuristic_confidence([]) == 0.0

    
    def test_heuristic_room_override_habitacion_fuerte_devuelve_habitacion(self, mock_get_db):
        """Dados sensores con señal muy fuerte de una habitación, cuando se aplica heurística, 
           entonces retorna esa habitación"""
        from blueprints.sensors import heuristic_room_override
        
        sensors = [
            {"sensor_id": "BEACON_HAB1", "rssi": -60}
        ]
        
        result = heuristic_room_override(sensors)
        assert result == "HAB1"

    def test_heuristic_room_override_cocina_con_hab1_debil_retorna_cocina(self, mock_get_db):
        """Dados sensores de cocina fuerte y HAB1 débil, cuando se aplica heurística, entonces retorna COCINA"""
        from blueprints.sensors import heuristic_room_override
        
        sensors = [
            {"sensor_id": "BEACON_COCINA", "rssi": -70},
            {"sensor_id": "BEACON_HAB1", "rssi": -80}
        ]
        
        result = heuristic_room_override(sensors)
        assert result == "COCINA"

    def test_heuristic_room_override_sin_patron_retorna_none(self, mock_get_db):
        """Dados sensores sin patrón claro, cuando se aplica heurística, entonces retorna None"""
        from blueprints.sensors import heuristic_room_override
        
        sensors = [
            {"sensor_id": "BEACON_SALON", "rssi": -85},
            {"sensor_id": "BEACON_COCINA", "rssi": -82}
        ]
        
        result = heuristic_room_override(sensors)
        assert result is None

    #  POST /sensors/update_position 
    
    def test_update_position_insuficientes_beacons_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /sensors/update_position con menos de 2 beacons útiles, cuando se procesa, entonces retorna error"""
        response = client.post('/sensors/update_position', json={
            'user_id': 'user123',
            'sensors': [{"sensor_id": "B1", "rssi": -60}]
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'insufficient_beacons'

    def test_update_position_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /sensors/update_position sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.post('/sensors/update_position', json={
            'sensors': [{"sensor_id": "B1", "rssi": -60}, {"sensor_id": "B2", "rssi": -55}]
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_update_position_con_heuristica_detecta_habitacion(self, client, mock_get_db):
        """Dada una petición con sensores con RSSI fuerte, añade detección pendiente"""
        from blueprints.position import pending_detections, clear_pending_detections
        
        db = mock_get_db
        
        pending_detections.clear()
        
        db.rooms.find.return_value = [
            {"_id": "HAB1", "beacons": [{"id": "BEACON_HAB1"}]}
        ]
        
        response = client.post('/sensors/update_position', json={
            'user_id': 'user123',
            'sensors': [
                {"sensor_id": "BEACON_HAB1", "rssi": -60},
                {"sensor_id": "BEACON_SALON", "rssi": -65}
            ]
        })
        
        assert response.status_code == 200
        assert response.json['status'] in ['pending', 'confirmed']
        if response.json['status'] == 'confirmed':
            assert response.json['room'] == 'HAB1'
        else:
            assert response.json['pending_count'] == 1

    def test_update_position_con_confirmacion_actualiza_estado(self, client, mock_get_db):
        """Dadas 3 detecciones consistentes, cuando se confirma, entonces actualiza el estado del usuario"""
        from blueprints.position import pending_detections, add_pending_detection
        
        db = mock_get_db
        pending_detections.clear()
        
        user_id = "user123"
        add_pending_detection(user_id, "SALON", 0.9, "2024-01-15T10:00:00Z")
        add_pending_detection(user_id, "SALON", 0.85, "2024-01-15T10:00:05Z")
        
        db.rooms.find.side_effect = [
            [{"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}],
            [{"_id": "SALON"}, {"_id": "COCINA"}],
        ]
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        db.users_state.find_one.return_value = None
        
        response = client.post('/sensors/update_position', json={
            'user_id': user_id,
            'sensors': [
                {"sensor_id": "BEACON_SALON", "rssi": -55},
                {"sensor_id": "BEACON_COCINA", "rssi": -80}
            ]
        })
        
        # Con 3 detecciones iguales, debe confirmar
        assert response.status_code == 200
        assert response.json['status'] == 'confirmed'
        assert response.json['room'] == 'SALON'

    #  POST /sensors/detect_once 
    
    def test_detect_once_retorna_deteccion_inmediata(self, client, mock_get_db):
        """Dada una petición a detect_once, retorna detección sin sistema de confirmación"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "HAB1", "beacons": [{"id": "BEACON_HAB1"}]}
        ]
        db.room_zones.find.return_value = []
        
        response = client.post('/sensors/detect_once', json={
            'user_id': 'user123',
            'sensors': [
                {"sensor_id": "BEACON_HAB1", "rssi": -60},
                {"sensor_id": "BEACON_SALON", "rssi": -70}
            ]
        })
        
        assert response.status_code == 200
        assert 'room' in response.json
        assert response.json['room'] is not None

    def test_detect_once_sensores_insuficientes_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /sensors/detect_once con pocos sensores, cuando se procesa, entonces retorna error"""
        response = client.post('/sensors/detect_once', json={
            'user_id': 'user123',
            'sensors': [{"sensor_id": "B1", "rssi": -60}]
        })
        
        assert response.status_code == 200
        assert response.json.get('error') == 'not_enough_beacons'

    #  POST /sensors/training_data 
    
    def test_save_training_data_guarda_muestra_valida(self, client, mock_get_db):
        """Dada una petición POST a /sensors/training_data con datos válidos, cuando se procesa, entonces guarda en la colección"""
        db = mock_get_db
        
        response = client.post('/sensors/training_data', json={
            'user_id': 'user123',
            'room_id': 'SALON',
            'zone_id': 'sofa',
            'sensors': [
                {"sensor_id": "B1", "rssi": -55},
                {"sensor_id": "B2", "rssi": -60}
            ]
        })
        
        assert response.status_code == 200
        assert response.json['status'] == 'ok'
        db.training_sensor_data.insert_one.assert_called_once()

    def test_save_training_data_muestra_con_pocos_sensores_se_descarta(self, client, mock_get_db):
        """Dada una petición POST a /sensors/training_data con menos de 2 sensores, cuando se procesa, entonces retorna error"""
        response = client.post('/sensors/training_data', json={
            'user_id': 'user123',
            'room_id': 'SALON',
            'sensors': [{"sensor_id": "B1", "rssi": -55}]
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_save_training_data_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición POST a /sensors/training_data sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.post('/sensors/training_data', json={
            'room_id': 'SALON',
            'sensors': [{"sensor_id": "B1", "rssi": -55}, {"sensor_id": "B2", "rssi": -60}]
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    
    @patch('subprocess.run')
    def test_train_models_api_ejecuta_script(self, mock_subprocess, client, mock_get_db):
        """Dada una petición POST a /sensors/ml/train, cuando se procesa, entonces ejecuta el script de entrenamiento"""
        mock_subprocess.return_value = MagicMock()
        
        response = client.post('/sensors/ml/train')
        
        assert response.status_code == 200
        assert response.json['status'] == 'training_completed'
        mock_subprocess.assert_called_once()

    def test_reset_training_elimina_datos_entrenamiento(self, client, mock_get_db):
        """Dada una petición POST a /sensors/ml/reset_training, cuando se procesa, entonces elimina todos los datos de entrenamiento"""
        db = mock_get_db
        
        response = client.post('/sensors/ml/reset_training')
        
        assert response.status_code == 200
        assert response.json['status'] == 'reset_ok'
        db.training_sensor_data.delete_many.assert_called_once_with({})

    def test_training_status_retorna_estadisticas_muestras(self, client, mock_get_db):
        """Dada una petición GET a /sensors/ml/status, cuando hay datos, entonces retorna estadísticas por habitación"""
        db = mock_get_db
        db.training_sensor_data.find.return_value = [
            {"room_id": "SALON", "zone_id": "sofa"},
            {"room_id": "SALON", "zone_id": "mesa"},
            {"room_id": "COCINA", "zone_id": "centro"}
        ]
        
        response = client.get('/sensors/ml/status')
        
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'ok'
        assert data['total_samples'] == 3
        assert 'SALON' in data['samples_by_room']

    def test_reload_models_recarga_modelos(self, client, mock_get_db):
        """Dada una petición POST a /sensors/ml/reload_models, cuando se procesa, entonces recarga los modelos ML"""
        with patch('blueprints.sensors.load_models') as mock_load:
            response = client.post('/sensors/ml/reload_models')
            
            assert response.status_code == 200
            assert response.json['status'] == 'models_reloaded'
            mock_load.assert_called_once()

    #  GET /sensors/get_confirmed_position 
    
    def test_get_confirmed_position_usuario_con_posicion(self, client, mock_get_db, sample_user_state):
        """Dada una petición GET a /sensors/get_confirmed_position con user_id, cuando el usuario tiene posición, entonces la retorna"""
        db = mock_get_db
        db.users_state.find_one.return_value = sample_user_state
        
        response = client.get('/sensors/get_confirmed_position?user_id=user123')
        
        assert response.status_code == 200
        data = response.json
        assert data['has_position'] is True
        assert data['room'] == 'SALON'

    def test_get_confirmed_position_usuario_sin_posicion(self, client, mock_get_db):
        """Dada una petición GET a /sensors/get_confirmed_position con user_id, cuando el usuario no tiene posición, entonces retorna has_position=False"""
        db = mock_get_db
        db.users_state.find_one.return_value = None
        
        response = client.get('/sensors/get_confirmed_position?user_id=user123')
        
        assert response.status_code == 200
        assert response.json['has_position'] is False

    def test_get_confirmed_position_sin_user_id_retorna_error(self, client, mock_get_db):
        """Dada una petición GET a /sensors/get_confirmed_position sin user_id, cuando se procesa, entonces retorna error 400"""
        response = client.get('/sensors/get_confirmed_position')
        
        assert response.status_code == 400
        assert 'error' in response.json


    def test_build_feature_vector_from_sensors_construye_vector(self, mock_get_db):
        """Verifica que build_feature_vector_from_sensors construye el vector correctamente"""
        from blueprints.sensors import build_feature_vector_from_sensors, get_sensor_ids
        from unittest.mock import patch
        
        sensors = [
            {"sensor_id": "B1", "rssi": -55},
            {"sensor_id": "B2", "rssi": -60}
        ]
        
        with patch('blueprints.sensors.get_sensor_ids', return_value=["B1", "B2", "B3"]):
            vector = build_feature_vector_from_sensors(sensors)
        
        assert len(vector) == 3
        assert vector[0] == -55
        assert vector[1] == -60
        assert vector[2] == -100 

    def test_smooth_label_respeta_deteccion_fuerte(self, mock_get_db):
        """Verifica que smooth_label respeta la nueva detección si es diferente"""
        from blueprints.sensors import smooth_label, ROOM_HISTORY_SIZE
        
        history = []
        
        result = smooth_label(history, "SALON")
        assert result == "SALON"
        
        result = smooth_label(history, "SALON")
        assert result == "SALON"
        
        result = smooth_label(history, "COCINA")
        assert result == "COCINA"

    def test_predict_zone_con_modelo_no_existente_retorna_none(self, mock_get_db):
        """Verifica que predict_zone retorna None si el modelo no existe"""
        from blueprints.sensors import predict_zone
        
        with patch('os.path.exists', return_value=False):
            result = predict_zone([0, 0, 0], "SALON")
            assert result is None

    def test_update_position_con_fallback_ml(self, client, mock_get_db):
        """Prueba update_position cuando la heurística retorna None y usa ML"""
        db = mock_get_db
        from blueprints.position import pending_detections
        
        pending_detections.clear()
        
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}
        ]
        
        with patch('blueprints.sensors.heuristic_room_override', return_value=None):
            with patch('blueprints.sensors.predict_room', return_value="SALON"):
                with patch('blueprints.sensors.get_db', return_value=db):
                    response = client.post('/sensors/update_position', json={
                        'user_id': 'user123',
                        'sensors': [
                            {"sensor_id": "BEACON_SALON", "rssi": -65},
                            {"sensor_id": "BEACON_COCINA", "rssi": -70}
                        ]
                    })
                    
                    assert response.status_code == 200
                    assert response.json['status'] in ['pending', 'confirmed']

    def test_detect_once_con_ml_fallback(self, client, mock_get_db):
        """Prueba detect_once cuando la heurística retorna None y usa ML"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}
        ]
        db.room_zones.find.return_value = []
        
        with patch('blueprints.sensors.heuristic_room_override', return_value=None):
            with patch('blueprints.sensors.predict_room', return_value="SALON"):
                response = client.post('/sensors/detect_once', json={
                    'user_id': 'user123',
                    'sensors': [
                        {"sensor_id": "BEACON_SALON", "rssi": -65},
                        {"sensor_id": "BEACON_COCINA", "rssi": -70}
                    ]
                })
                
                assert response.status_code == 200
                assert response.json['room'] == 'SALON'

    def test_detect_once_con_error_ml(self, client, mock_get_db):
        """Prueba detect_once cuando ML lanza excepción y usa fallback"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}
        ]
        db.room_zones.find.return_value = []
        
        with patch('blueprints.sensors.heuristic_room_override', return_value=None):
            with patch('blueprints.sensors.predict_room', side_effect=Exception("ML Error")):
                with patch('blueprints.sensors.estimate_room_from_sensors', return_value="SALON"):
                    response = client.post('/sensors/detect_once', json={
                        'user_id': 'user123',
                        'sensors': [
                            {"sensor_id": "BEACON_SALON", "rssi": -65},
                            {"sensor_id": "BEACON_COCINA", "rssi": -70}
                        ]
                    })
                    
                    assert response.status_code == 200
                    assert response.json['room'] is not None

    def test_detect_once_con_deteccion_zona(self, client, mock_get_db):
        """Prueba detect_once con detección de zona específica"""
        db = mock_get_db
        db.rooms.find.return_value = [
            {"_id": "SALON", "beacons": [{"id": "BEACON_SALON"}]}
        ]
        db.room_zones.find.return_value = [
            {"zone_id": "zona1"},
            {"zone_id": "zona2"}
        ]
        
        with patch('blueprints.sensors.predict_zone', return_value="zona1"):
            with patch('blueprints.sensors.heuristic_room_override', return_value="SALON"):
                response = client.post('/sensors/detect_once', json={
                    'user_id': 'user123',
                    'sensors': [
                        {"sensor_id": "BEACON_SALON", "rssi": -55},
                        {"sensor_id": "BEACON_COCINA", "rssi": -70}
                    ]
                })
                
                assert response.status_code == 200
                assert response.json['zone'] == 'zona1'

    def test_save_training_data_con_sensores_debiles_se_descarta(self, client, mock_get_db):
        """Verifica que muestras con señales débiles se descartan"""
        response = client.post('/sensors/training_data', json={
            'user_id': 'user123',
            'room_id': 'SALON',
            'sensors': [
                {"sensor_id": "B1", "rssi": -100},
                {"sensor_id": "B2", "rssi": -100}
            ]
        })
        
        assert response.status_code == 400
        assert 'error' in response.json

    def test_update_position_con_deteccion_fallida(self, client, mock_get_db):
        """Verifica que update_position maneja el caso de detección fallida"""
        db = mock_get_db
        from blueprints.position import pending_detections
        
        pending_detections.clear()
        
        db.rooms.find.return_value = []
        db.rooms.find_one.return_value = {"_id": "SALON", "is_transit": False}
        
        with patch('blueprints.sensors.heuristic_room_override', return_value=None):
            with patch('blueprints.sensors.predict_room', return_value=None):
                with patch('blueprints.sensors.estimate_room_from_sensors', return_value=None):
                    response = client.post('/sensors/update_position', json={
                        'user_id': 'user123',
                        'sensors': [
                            {"sensor_id": "BEACON_SALON", "rssi": -65},
                            {"sensor_id": "BEACON_COCINA", "rssi": -70}
                        ]
                    })
                    
                    assert response.status_code == 400
                    assert 'error' in response.json