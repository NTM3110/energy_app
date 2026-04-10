from fastapi import FastAPI
import pandas as pd

app = FastAPI()

# Load the data into memory for fast access
df = pd.read_csv("../meter_data.csv")
# Global index to track our "current" line
current_row_index = 0

@app.get("/meter-stream")
async def get_latest_data():
    global current_row_index
    
    # Get the row at the current index
    row = df.iloc[current_row_index].to_dict()
    
    # Increment the index for the next call (1-second interval simulation)
    # This ensures every call gets the "next" minute of data
    current_row_index = (current_row_index + 1) % len(df)
    
    return {
        "status": "success",
        "data": row,
        "simulated_step": current_row_index
    }

@app.get("/reset")
async def reset_simulation():
    global current_row_index
    current_row_index = 0
    return {"status": "success", "message": "Simulation reset to the beginning of the day."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)