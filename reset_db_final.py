# reset_db_final.py
import os
import sys
from app import app, db
from models import *

print("=" * 50)
print("FORCE DATABASE RESET")
print("=" * 50)

with app.app_context():
    # Get database path
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    print(f"Database URI: {db_uri}")
    
    # Extract path for SQLite
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        print(f"Database path: {db_path}")
        
        # Delete the database file if it exists
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                print(f"✅ Deleted existing database: {db_path}")
            except Exception as e:
                print(f"❌ Error deleting database: {e}")
        else:
            print("No existing database file found.")
    
    # Drop all tables
    print("Dropping all tables...")
    db.drop_all()
    print("✅ Tables dropped")
    
    # Create all tables
    print("Creating all tables with new schema...")
    db.create_all()
    print("✅ Tables created")
    
    # Verify appointment table columns
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('appointment')]
    print(f"\nAppointment table columns: {columns}")
    
    if 'service_id' in columns:
        print("✅ service_id column exists!")
    else:
        print("❌ service_id column MISSING!")
        print("Attempting to add column manually...")
        try:
            from sqlalchemy import text
            db.session.execute(text('ALTER TABLE appointment ADD COLUMN service_id INTEGER REFERENCES services(id)'))
            db.session.commit()
            print("✅ Column added manually!")
        except Exception as e:
            print(f"❌ Failed to add column: {e}")
    
    # Add default services
    print("\nAdding default services...")
    if Service.query.count() == 0:
        default_services = [
            Service(name='Haircut', duration=45, description='Professional haircut service', price=45.00),
            Service(name='Hair Coloring', duration=120, description='Full hair coloring', price=120.00),
            Service(name='Hair Treatment', duration=60, description='Deep conditioning treatment', price=80.00),
            Service(name='Styling', duration=45, description='Blow dry and styling', price=50.00),
            Service(name='Perm', duration=150, description='Professional perming service', price=200.00),
            Service(name='Highlights', duration=120, description='Foil highlights', price=150.00),
            Service(name="Men's Cut", duration=30, description="Quick men's haircut", price=35.00),
            Service(name="Children's Cut", duration=30, description='Haircut for children under 12', price=30.00),
        ]
        
        for service in default_services:
            db.session.add(service)
        
        db.session.commit()
        print(f"✅ Added {len(default_services)} default services")
    else:
        print("Services already exist")
    
    # Add default salon settings
    if not SalonSettings.query.first():
        settings = SalonSettings()
        db.session.add(settings)
        db.session.commit()
        print("✅ Added default salon settings")
    
    print("\n" + "=" * 50)
    print("✅ DATABASE RESET COMPLETE!")
    print("=" * 50)
    print("\nYou can now restart your Flask app with: python app.py")