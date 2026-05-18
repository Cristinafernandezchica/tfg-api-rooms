# API para gestión de habitaciones - IndoorPilot

## Manual de instalación

### Requisitos previos

- Python 3.8 o superior
- MongoDB (local o remoto, en remoto tiene menos complicaciones)
- pip (gestor de paquetes de Python)

### Instalación Paso a Paso

#### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd <nombre-del-proyecto>
```

#### 2. Crear y activar entorno virtual

```bash
python -m venv venv
venv\Scripts\activate
```

#### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

#### 4. Configurar variables de entorno

Crea un archivo ``.env`` en la raíz del proyecto.

```bash
MONGO_URI=mongodb://localhost:27017/indoor_db
USERS_API_BASE_URL=http://localhost:5002
```

Notas:

- Cambia MONGO_URI por su correspondiente dirección de conexión.

#### 5. Inicializar la base de datos

Debemos poblar las estancias y zonas:

```bash
python scripts/seed_rooms.py
python scripts/seed_zones.py
```

#### 6. Entrenar modelo ML (opcional)
Ya viene un modelo de entrenamiento configurado, además de que el entrenamiento se puede hacer desde la apliación que hace uso de la API.

```bash
python scripts/train_models.py
```

#### 7. Iniciar la API

```bash
python app.py
```

La API se iniciará en ``http://localhost:5001``.