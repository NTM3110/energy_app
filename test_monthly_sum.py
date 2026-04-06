import requests

# Port is 8001 based on run.py
BASE_URL = "http://localhost:8001"

def test_monthly_sum():
    # Use POST with JSON body as per user's preference
    test_params_list = [
        {"year": 2025, "month": 1, "meter_id": 1},
        {"year": 2025, "month": 2, "meter_id": 1},
        {"year": 2026, "month": 2, "meter_id": 12}, # Similar to user's screenshot
    ]
    
    for body in test_params_list:
        print(f"Testing with body: {body}")
        try:
            # Use /api prefix based on main.py
            response = requests.post(f"{BASE_URL}/api/energy/monthly-sum", json=body)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                print(f"Response: {response.json()}")
            else:
                print(f"Error: {response.text}")
        except Exception as e:
            print(f"Request failed: {e}")
        print("-" * 20)

if __name__ == "__main__":
    test_monthly_sum()
