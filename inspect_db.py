
from sqlalchemy import create_engine, inspect

DATABASE_URL = "postgresql+psycopg2://postgres:admin@localhost:5432/energy_demo"
engine = create_engine(DATABASE_URL)

def inspect_db():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tables: {tables}")
    
    for table in tables:
        print(f"\nTable: {table}")
        columns = inspector.get_columns(table)
        for column in columns:
            print(f"  - {column['name']} ({column['type']})")

if __name__ == "__main__":
    try:
        inspect_db()
    except Exception as e:
        print(f"Error: {e}")
