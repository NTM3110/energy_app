from app.db import engine, Base
import model.models

print("Dropping all tables...")
Base.metadata.drop_all(engine)
print("Recreating all tables...")
Base.metadata.create_all(engine)
print("Done. Ready for run.py demo.")
