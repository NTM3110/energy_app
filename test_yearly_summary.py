import requests

# Port is 8001 based on run.py
BASE_URL = "http://localhost:8001"

def test_yearly_summary():
    print("Testing Yearly Summary API...")
    try:
        response = requests.get(f"{BASE_URL}/api/energy/yearly-summary", params={"year": 2025})
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Year: {data['year']}, Count: {data['count']}")
            for item in data['items'][:3]: # Show first 3 months
                print(f"  Month {item['month']}: BESS={item['bess_to_lmv_energy_kwh']}, RTS={item['rts_to_lmv_energy_kwh']}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")
    print("-" * 20)

if __name__ == "__main__":
    test_yearly_summary()
