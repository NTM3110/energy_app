import sys
import os

# Add the project root to sys.path
sys.path.append('/home/shou/Documents/ATEnergy/MaxiMeter/Projects/energy_app')

from schema.meter import AddMeterRequestBody
from pydantic import ValidationError

def test_add_meter_request_body():
    print("Testing AddMeterRequestBody with role and source_id missing...")
    data = {
        "serial_number": 12345678,
        "username": "testuser",
        "password": "testpassword",
        "owner_id": 1,
        "type": "EDMI",
        "model": "Mk10E"
    }
    
    try:
        body = AddMeterRequestBody(**data)
        print("Success! AddMeterRequestBody created without role and source_id.")
        print(f"Role: {body.role}")
        print(f"Source ID: {body.source_id}")
    except ValidationError as e:
        print(f"Failure! Validation error: {e}")
        exit(1)

if __name__ == "__main__":
    test_add_meter_request_body()
