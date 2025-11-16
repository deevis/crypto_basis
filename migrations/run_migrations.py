import os
import importlib.util
import sys

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from sqlalchemy import text
from db_config import engine

# Pattern for YYYYMMDDHHMMSS_description.py
MIGRATION_PATTERN = re.compile(r'^\d{14}_[a-z0-9_]+\.py$')

def get_applied_migrations():
    """Get list of migrations that have already been applied"""
    with engine.connect() as connection:
        try:
            result = connection.execute(text("SELECT migration_name FROM migrations ORDER BY id"))
            return {row[0] for row in result}
        except Exception:
            # Table might not exist yet
            return set()

def record_migration(migration_name):
    """Record that a migration has been applied"""
    with engine.connect() as connection:
        connection.execute(
            text("INSERT INTO migrations (migration_name) VALUES (:name)"),
            {"name": migration_name}
        )
        connection.commit()

def is_valid_migration_file(filename):
    """Check if the filename matches our migration file pattern"""
    if not MIGRATION_PATTERN.match(filename):
        return False
    
    # Extract and validate the timestamp portion (YYYYMMDDHHMMSS)
    try:
        timestamp = int(filename[:14])
        year = timestamp // 10000000000
        month = (timestamp // 100000000) % 100
        day = (timestamp // 1000000) % 100
        hour = (timestamp // 10000) % 100
        minute = (timestamp // 100) % 100
        second = timestamp % 100
        
        # Basic date/time validation
        return (2020 <= year <= 2100 and  # Reasonable year range
                1 <= month <= 12 and
                1 <= day <= 31 and
                0 <= hour <= 23 and
                0 <= minute <= 59 and
                0 <= second <= 59)
    except ValueError:
        return False

def run_migrations():
    """Run all pending migrations in order"""
    # Get list of applied migrations
    applied = get_applied_migrations()
    
    # Get all migration files
    migration_dir = os.path.dirname(os.path.abspath(__file__))
    migration_files = []
    
    for filename in os.listdir(migration_dir):
        if filename != 'run_migrations.py' and is_valid_migration_file(filename):
            migration_files.append(filename)
        elif filename.endswith('.py') and filename != 'run_migrations.py':
            print(f"Warning: Skipping invalid migration filename: {filename}")
    
    # Sort by filename to ensure correct order
    migration_files.sort()
    
    if not migration_files:
        print("No migrations found.")
        return
    
    print(f"Found {len(migration_files)} migrations")
    
    # Run pending migrations
    for filename in migration_files:
        if filename not in applied:
            print(f"Running migration: {filename}")
            
            # Import and run the migration
            module_path = os.path.join(migration_dir, filename)
            spec = importlib.util.spec_from_file_location(filename[:-3], module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            try:
                module.migrate()
                record_migration(filename)
                print(f"Successfully applied migration: {filename}")
            except Exception as e:
                print(f"Error applying migration {filename}: {e}")
                sys.exit(1)
        else:
            print(f"Skipping already applied migration: {filename}")

if __name__ == "__main__":
    run_migrations() 