import io
import json
import os
import typing

import requests
from datetime import datetime
import matplotlib.pyplot as plt
from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Union
from enum import Enum

from fastapi.responses import StreamingResponse
from matplotlib.ticker import ScalarFormatter


# Define Enums for validation
class PProducts(str, Enum):
    NEQUICK_ALG = "NEQUICK.ALG"
    TADM_ALG = "TADM.ALG"

class Measurements(str, Enum):
    FREQUENCY = "frequency"
    EDENSITY = "edensity"

description = """
Electron Density Profile and Frequency Profile at specified locations on the European grid (lat = 34 ÷ 60, lon = -5 ÷ 40) provided by the TaD-3D and NeQuick models.
"""

tags_metadata = [
        {
            "name": "Run Workflow",
            "description": "Run the workflow to get the electron density and frequency data for a given timestamp, latitude, longitude, products, and measurements"
        },
        {
            "name": "Plot Data",
            "description": "Plot the electron density and frequency data"
        }
    ]

# Get the full path to the directory containing the FastAPI script
script_dir = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title='ION ED Workflow',
    description=description,
    version="1.0.0",
    openapi_tags=tags_metadata,
    root_path="/wf-ion-ed"
    )

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    # allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def call_api(timestamp, lat, lon, products=["NEQUICK.ALG", "TADM.ALG"], measurements=["frequency", "edensity"]):
    products = "&".join([f"products={product}" for product in products])
    measurements = "&".join([f"measurements={measurement}" for measurement in measurements])
    url = f"https://electron.space.noa.gr/dias/api/v2/dias_db/odc_edensity?date={timestamp}&lat={lat}&lon={lon}&{products}&{measurements}"
    headers = {
        "accept": "application/json"
    }
    print(f"Calling API with URL: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        data = response.json()
        if "grid_params" not in data or "model_data" not in data:
            return {"error": data}
        ssn = data["grid_params"]["SolCycle"]["ssn"]
        f10_7 = data["grid_params"]["SolCycle"]["f10_7"]
        kp = data["grid_params"]["Kp"]["kp"]
        plot_data = data["model_data"]["vprofile"]
        if "TADM.ALG" in products:
            # Check plot_data["TADM.ALG"]["theight"], which is an array list of integers, only keep the value <= 1000
            plot_data["TADM.ALG"]["theight"] = [height for height in plot_data["TADM.ALG"]["theight"] if height <= 1000]
            adjust_data_size = len(plot_data["TADM.ALG"]["theight"])
            # Now, adjust the "frequency", "edensity" data in plot_data["TADM.ALG"]  to match the size of "theight"
            if "frequency" in measurements:
                plot_data["TADM.ALG"]["frequency"] = plot_data["TADM.ALG"]["frequency"][:adjust_data_size]
            if "edensity" in measurements:
                plot_data["TADM.ALG"]["edensity"] = plot_data["TADM.ALG"]["edensity"][:adjust_data_size]
        # Now construct the output json data
        output_data = {
            "timestamp": timestamp,
            "location": [lat, lon],
            "ssn": ssn,
            "f10_7": f10_7,
            "kp": kp,
            "products": products,
            "measurements": measurements,
            "plot_data": plot_data
        }
        return output_data
    except Exception as e:
        print(f"Error calling API: {e}")
        return {"error": str(e)}

@app.get("/run_workflow", tags=["Run Workflow"])
async def run_workflow(
    date: datetime = Query(..., title="Timestamp", description="Timestamp in ISO format, e.g., 2025-02-01T10:45:00"),
    lat: float = Query(..., ge=34.0, le=60.0, title="Lat", description="Latitude, between 34 and 60"),
    lon: float = Query(..., ge=-5.0, le=40.0, title="Lon" , description="Longitude, between -5 and 40"),
    products: typing.List[PProducts] = Query(..., title="Products", description="Select one or more products to retrieve data for", require = True),
    measurements: typing.List[Measurements] = Query(..., title="Measurements", description="Select one or more measurements to retrieve data for",  require = True),
):
    # Convert the products and measurements to a list of strings
    products = [product.value for product in products]
    measurements = [measurement.value for measurement in measurements]
    data = call_api(date, lat, lon, products=products, measurements=measurements)
    return data

# Define the new `plot_data` API
@app.post("/plot_data", tags=["Plot Data"])
async def run_workflow(
    date: datetime = Query(..., title="Timestamp", description="Timestamp in ISO format, e.g., 2025-02-01T10:45:00"),
    lat: float = Query(..., ge=34.0, le=60.0, title="Lat", description="Latitude, between 34 and 60"),
    lon: float = Query(..., ge=-5.0, le=40.0, title="Lon" , description="Longitude, between -5 and 40"),
    products: typing.List[PProducts] = Query(..., title="Products", description="Select one or more products to retrieve data for", require = True),
    measurements: typing.List[Measurements] = Query(..., title="Measurements", description="Select one or more measurements to retrieve data for",  require = True),
):
    # Convert the products and measurements to a list of strings
    products = [product.value for product in products]
    measurements = [measurement.value for measurement in measurements]
    data = call_api(date, lat, lon, products=products, measurements=measurements)
    if "error" in data:
        return data
    else:
        ssn = data["ssn"]
        f10_7 = data["f10_7"]
        kp = data["kp"]
        print(f"SSN: {ssn}, F10.7: {f10_7}, Kp: {kp}")
        plot_data = data["plot_data"]
        # Check how many measurements need to be plotted
        if len(measurements) == 2:
            fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
            ax1 = axes[0]
            ax2 = axes[1]
            if "edensity" in measurements:
                # edensity vs theight, compare NEQUICK.ALG and TADM.ALG
                if "NEQUICK.ALG" in plot_data:
                    ax1.plot([x / 1e6 for x in plot_data["NEQUICK.ALG"]["edensity"]], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax1.plot([x / 1e6 for x in plot_data["TADM.ALG"]["edensity"]], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')

                # Set axis starting from 0 for both x and y
                ax1.set_xlim(left=0)
                ax1.set_ylim(bottom=0)
                ax1.set_xlabel("Electron Density (el/cm^3)")
                ax1.set_ylabel("Height (km)")
                ax1.set_title(f'Electron Density vs Height - {", ".join(products)}')
                ax1.legend()
                ax1.grid()
                ax1.ticklabel_format(style='plain', axis='x')

            if "frequency" in measurements:
                # frequency vs theight, compare NEQUICK.ALG and TADM.ALG

                if "NEQUICK.ALG" in plot_data:
                    ax2.plot(plot_data["NEQUICK.ALG"]["frequency"], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax2.plot(plot_data["TADM.ALG"]["frequency"], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')

                # Set axis starting from 0 for both x and y
                ax2.set_xlim(left=0)
                ax2.set_ylim(bottom=0)
                ax2.set_xlabel("Frequency (MHz)")
                ax2.set_ylabel("Height (km)")
                ax2.set_title(f'Frequency vs Height - {", ".join(products)}')
                ax2.legend()
                ax2.grid()

            fig.text(0.5, 0.01, f"{date}, [Lat: {lat},Lon: {lon}], ssn: {ssn}, f10.7: {f10_7}, kp: {kp}", wrap=True, horizontalalignment='center', fontsize=12)

            plt.tight_layout(rect=[0, 0.05, 1, 1])

            img_io = io.BytesIO()
            fig.savefig(img_io, format='png', bbox_inches='tight')
            img_io.seek(0)
        else:
            fig, ax = plt.subplots(1, 1, figsize=(7, 6))
            if "edensity" in measurements:
                # edensity vs theight, compare NEQUICK.ALG and TADM.ALG
                if "NEQUICK.ALG" in plot_data:
                    ax.plot([x / 1e6 for x in plot_data["NEQUICK.ALG"]["edensity"]], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax.plot([x / 1e6 for x in plot_data["TADM.ALG"]["edensity"]], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')

                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)
                ax.set_xlabel("Electron Density (el/cm^3)")
                ax.set_ylabel("Height (km)")
                ax.set_title(f'Electron Density vs Height - {", ".join(products)}')
                ax.legend()
                ax.grid()
                ax.ticklabel_format(style='plain', axis='x')

            if "frequency" in measurements:
                # frequency vs theight, compare NEQUICK.ALG and TADM.ALG

                if "NEQUICK.ALG" in plot_data:
                    ax.plot(plot_data["NEQUICK.ALG"]["frequency"], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax.plot(plot_data["TADM.ALG"]["frequency"], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')

                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)
                ax.set_xlabel("Frequency (MHz)")
                ax.set_ylabel("Height (km)")
                ax.set_title(f'Frequency vs Height - {", ".join(products)}')
                ax.legend()
                ax.grid()

            fig.text(0.5, 0.01, f"{date}, [Lat: {lat},Lon: {lon}], ssn: {ssn}, f10.7: {f10_7}, kp: {kp}", wrap=True, horizontalalignment='center', fontsize=12)

            plt.tight_layout(rect=[0, 0.05, 1, 1])

            img_io = io.BytesIO()
            fig.savefig(img_io, format='png', bbox_inches='tight')
            img_io.seek(0)

        return StreamingResponse(img_io, media_type="image/png")