import os

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"
    USERS_API_BASE_URL = os.getenv("USERS_API_BASE_URL", "http://localhost:5002")
