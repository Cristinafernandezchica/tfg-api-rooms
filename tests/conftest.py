import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from db.mongo import get_db

@pytest.fixture
def app():
    """Crea una app de prueba con contexto"""
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['MONGO_URI'] = 'mongodb://fake:27017/test'
    app.config['USERS_API_BASE_URL'] = 'http://localhost:5002'
    return app

@pytest.fixture
def client(app):
    """Cliente de pruebas"""
    return app.test_client()

@pytest.fixture
def app_context(app):
    """Contexto de aplicación para pruebas que necesitan current_app"""
    with app.app_context():
        yield app

@pytest.fixture
def mock_db():
    """Mock de la base de datos MongoDB"""
    mock = MagicMock()
    
    # Colecciones simuladas
    mock.users_state = MagicMock()
    mock.rooms = MagicMock()
    mock.room_events = MagicMock()
    mock.routes = MagicMock()
    mock.user_routes = MagicMock()
    mock.room_zones = MagicMock()
    mock.pois = MagicMock()
    mock.training_sensor_data = MagicMock()
    
    return mock

@pytest.fixture
def mock_get_db(mock_db):
    """Mock de get_db()"""
    with patch('db.mongo.get_db', return_value=mock_db):
        with patch('blueprints.position.get_db', return_value=mock_db):
            with patch('blueprints.rooms.get_db', return_value=mock_db):
                with patch('blueprints.routes.get_db', return_value=mock_db):
                    with patch('blueprints.sensors.get_db', return_value=mock_db):
                        yield mock_db

@pytest.fixture
def sample_sensors():
    """Datos de sensores de ejemplo con RSSI suficientemente fuertes"""
    return [
        {"sensor_id": "BEACON_SALON", "rssi": -55},
        {"sensor_id": "BEACON_COCINA", "rssi": -65},
        {"sensor_id": "BEACON_HAB1", "rssi": -75}
    ]

@pytest.fixture
def sample_user_state():
    """Estado de usuario de ejemplo"""
    return {
        "user_id": "user123",
        "current_room": "SALON",
        "last_update": "2024-01-15T10:00:00Z",
        "confidence": 0.95,
        "last_event": "enter",
        "last_room_change": "2024-01-15T10:00:00Z",
        "confirmed_at": "2024-01-15T10:00:00Z"
    }