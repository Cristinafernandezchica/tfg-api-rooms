import os

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/indoor_db")
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"
