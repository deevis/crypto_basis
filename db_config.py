from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Get database configuration from environment variables
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

# Construct database URL
DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)
    
def transactions_populated():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT COUNT(*) FROM transactions"))
        count = result.scalar_one()
        print(f"Transactions table has {count} rows")
        return count > 0

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 