import csv
from datetime import datetime, timedelta

def create_specific_rte_profile(filename="meter_data.csv"):
    # Constants
    CAPACITY_KWH = 5000
    # Applying 92% RTE as two 96% one-way efficiency steps (0.96 * 0.96 ≈ 0.92)
    EFFICIENCY = 0.96 
    
    # Initial State
    total_import = 100000.0
    total_export = 50000.0
    soc_percent = 30.0
    soc_kwh = CAPACITY_KWH * (soc_percent / 100)
    
    start_time = datetime(2026, 4, 10, 9, 0, 0)
    
    # Define Targets
    # 1. 30% -> 90% in 7 steps (minutes)
    charge_needed_in_battery = CAPACITY_KWH * 0.60 # 3000 kWh
    step_charge_kwh = charge_needed_in_battery / 7
    
    # 2. 90% -> 60% in 8 steps (minutes)
    discharge_needed_from_battery = CAPACITY_KWH * 0.30 # 1500 kWh
    step_discharge_kwh = discharge_needed_from_battery / 8

    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "total_import_kwh", "total_export_kwh", "soc"])
        
        # --- Phase 1: 7 Minutes Charging (30% to 90%) ---
        for i in range(7):
            # Meter import must be HIGHER than battery gain
            actual_import = step_charge_kwh / EFFICIENCY
            total_import += actual_import
            soc_kwh += step_charge_kwh
            
            writer.writerow([
                (start_time + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
                round(total_import, 4),
                round(total_export, 4),
                round((soc_kwh / CAPACITY_KWH) * 100, 2)
            ])
            
        phase2_start = start_time + timedelta(minutes=7)

        # --- Phase 2: 8 Minutes Discharging (90% to 60%) ---
        for i in range(8):
            # Meter export will be LOWER than battery loss
            actual_export = step_discharge_kwh * EFFICIENCY
            total_export += actual_export
            soc_kwh -= step_discharge_kwh
            
            writer.writerow([
                (phase2_start + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
                round(total_import, 4),
                round(total_export, 4),
                round((soc_kwh / CAPACITY_KWH) * 100, 2)
            ])

create_specific_rte_profile()
print("CSV generated with 92% RTE. 7min Charge (30->90%), 8min Discharge (90->60%)")