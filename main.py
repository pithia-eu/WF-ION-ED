import io
import json
import os
import typing

import requests
from datetime import datetime
import matplotlib.pyplot as plt
from PIL.ImageOps import scale
from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Union
from enum import Enum

from fastapi.responses import StreamingResponse
from matplotlib import ticker
from matplotlib.ticker import ScalarFormatter


# Define Enums for validation
class PProducts(str, Enum):
    NEQUICK_ALG = "NEQUICK.ALG"
    TADM_ALG = "TADM.ALG"
    NEDM2020_ALG = "NEDM2020.ALG"

class Measurements(str, Enum):
    FREQUENCY = "frequency"
    EDENSITY = "edensity"

description = """
Electron Density Profile and Frequency Profile at specified locations on the European grid (lat = 34 ÷ 60, lon = -5 ÷ 40) provided by the TaD-3D, NeQuick and NEDM2020 models.
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

async def call_api(timestamp, lat, lon, products=["NEQUICK.ALG", "TADM.ALG", "NEDM2020.ALG"], measurements=["frequency", "edensity"]):
    default_products = ["NEQUICK.ALG", "TADM.ALG"]
    default_products_str = "&".join([f"products={product}" for product in default_products])
    products = "&".join([f"products={product}" for product in products])
    measurements = "&".join([f"measurements={measurement}" for measurement in measurements])
    url = f"https://electron.space.noa.gr/dias/api/v2/dias_db/odc_edensity?date={timestamp}&lat={lat}&lon={lon}&{default_products_str}&{measurements}"
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
        else:
            # If TADM.ALG is not in the products, and TADM.ALG is in the plot_data, remove it
            if "TADM.ALG" in plot_data:
                del plot_data["TADM.ALG"]
        if "NEQUICK.ALG" not in products:
            # If NEQUICK.ALG is not in the products, and NEQUICK.ALG is in the plot_data, remove it
            if "NEQUICK.ALG" in plot_data:
                del plot_data["NEQUICK.ALG"]
        if "NEDM2020.ALG" in products:
            f10p7_sfu = f10_7
            date = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            # Call the DLR API to get the electron density data
            dlr_data = await get_dlr_data(f10p7_sfu, lat, lon, date)
            # Add the dlr_data to the plot_data
            plot_data["NEDM2020.ALG"] = dlr_data["NEDM2020.ALG"]
            # Check whether user need the frequency and edensity data from measurements
            if "frequency" not in measurements:
                # If frequency is not in the measurements, remove it from the plot_data["NEDM2020.ALG"]
                del plot_data["NEDM2020.ALG"]["frequency"]
            if "edensity" not in measurements:
                # If edensity is not in the measurements, remove it from the plot_data["NEDM2020.ALG"]
                del plot_data["NEDM2020.ALG"]["edensity"]

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
    data = await call_api(date, lat, lon, products=products, measurements=measurements)
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
    data = await call_api(date, lat, lon, products=products, measurements=measurements)
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
                if "NEDM2020.ALG" in plot_data:
                    ax1.plot([x / 1e6 for x in plot_data["NEDM2020.ALG"]["edensity"]], plot_data["NEDM2020.ALG"]["theight"], label="NEDM2020.ALG", linestyle='-', marker='o')

                # Set axis starting from 0 for both x and y
                ax1.set_xlim(left=0)
                ax1.set_ylim(bottom=0)
                ax1.set_xlabel("Electron Density (el/cm^3)")
                ax1.set_ylabel("Height (km)")
                ax1.set_title(f'Electron Density vs Height - {", ".join(products)}')
                ax1.legend()
                ax1.grid()
                # ax1.ticklabel_format(style='plain', axis='x')
                # Format x-axis ticks to show values as multiples of 1e6
                # ax1.xaxis.set_major_locator(ticker.MultipleLocator(0.25e6))
                ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x}×10⁶"))

            if "frequency" in measurements:
                # frequency vs theight, compare NEQUICK.ALG and TADM.ALG

                if "NEQUICK.ALG" in plot_data:
                    ax2.plot(plot_data["NEQUICK.ALG"]["frequency"], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax2.plot(plot_data["TADM.ALG"]["frequency"], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')
                if "NEDM2020.ALG" in plot_data:
                    ax2.plot(plot_data["NEDM2020.ALG"]["frequency"], plot_data["NEDM2020.ALG"]["theight"], label="NEDM2020.ALG", linestyle='-', marker='o')
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
                if "NEDM2020.ALG" in plot_data:
                    ax.plot([x / 1e6 for x  in plot_data["NEDM2020.ALG"]["edensity"]], plot_data["NEDM2020.ALG"]["theight"], label="NEDM2020.ALG", linestyle='-', marker='o')
                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)
                ax.set_xlabel("Electron Density (el/cm^3)")
                ax.set_ylabel("Height (km)")
                ax.set_title(f'Electron Density vs Height - {", ".join(products)}')
                ax.legend()
                ax.grid()
                # ax.ticklabel_format(style='plain', axis='x')
                # Format x-axis ticks to show values as multiples of 1e6
                # ax.xaxis.set_major_locator(ticker.MultipleLocator(0.25e6))
                ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x}×10⁶"))

            if "frequency" in measurements:
                # frequency vs theight, compare NEQUICK.ALG and TADM.ALG

                if "NEQUICK.ALG" in plot_data:
                    ax.plot(plot_data["NEQUICK.ALG"]["frequency"], plot_data["NEQUICK.ALG"]["theight"], label="NEQUICK.ALG", linestyle='-', marker='o')
                if "TADM.ALG" in plot_data:
                    ax.plot(plot_data["TADM.ALG"]["frequency"], plot_data["TADM.ALG"]["theight"], label="TADM.ALG", linestyle='-', marker='o')
                if "NEDM2020.ALG" in plot_data:
                    ax.plot(plot_data["NEDM2020.ALG"]["frequency"], plot_data["NEDM2020.ALG"]["theight"], label="NEDM2020.ALG", linestyle='-', marker='o')

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


# Function to get the DLR data
# Endpoint: https://impc.dlr.de/services/models/api/v1/nedm
# Method: Post
# Headers: application/json
# Payload Example:
# {
#   "f10p7_sfu": 100,
#   "receiver": {
#     "alt_km": 0,
#     "lat_deg": 50,
#     "lon_deg": 15
#   },
#   "satellite": {
#     "alt_km": 20000,
#     "lat_deg": 50,
#     "lon_deg": 15
#   },
#   "time": "2024-06-26T14:00:00.000Z"
# }
async def get_dlr_data(f10p7_sfu: float, lat_deg: float, lon_deg: float, time: str):
    url = "https://impc.dlr.de/services/models/api/v1/nedm"
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "f10p7_sfu": f10p7_sfu,
        "receiver": {
            "alt_km": 0,
            "lat_deg": lat_deg,
            "lon_deg": lon_deg
        },
        "satellite": {
            "alt_km": 20000,
            "lat_deg": lat_deg,
            "lon_deg": lon_deg
        },
        "time": time
    }
    response = requests.post(url, headers=headers, json=payload)
    # Convert the data to JSON, and extract the "features" field, for each feature, extract the "geometry.coordinates[2]" and "properties.electron_density_10^12/m^3"
    dlr_json = response.json()
    if "features" not in dlr_json:
        return {"error": "No features found in the response"}
    features = dlr_json["features"]
    if len(features) == 0:
        return {"error": "No features found in the response"}
    # Extract the coordinates and electron density
    density_data = {
        "NEDM2020.ALG":{
            "theight": [],
            "frequency": [],
            "edensity": []
        }
    }
    for feature in features:
        coordinates = feature["geometry"]["coordinates"]
        electron_density = feature["properties"]["electron_density_10^12/m^3"]
        # Round the coordinates to integer values
        height = round(coordinates[2])
        # Only keep the height <= 1000
        if height <= 1000 and height >= 100:
            density_data["NEDM2020.ALG"]["theight"].append(height)
            density_data["NEDM2020.ALG"]["edensity"].append(electron_density*1e6)
            # frequency = 8.9803 * sqrt(edensity)
            density_data["NEDM2020.ALG"]["frequency"].append(8.9803 * (electron_density ** 0.5))
    return density_data

# Hidden endpoint for DLR data
@app.get("/dlr_data", tags=["Run Workflow"], include_in_schema=False)
async def run_dlr_data(
    date: datetime = Query(..., title="Timestamp", description="Timestamp in ISO format, e.g., 2025-02-01T10:45:00"),
    lat: float = Query(..., ge=34.0, le=60.0, title="Lat", description="Latitude, between 34 and 60"),
    lon: float = Query(..., ge=-5.0, le=40.0, title="Lon" , description="Longitude, between -5 and 40"),
):
    # Convert the products and measurements to a list of strings
    f10p7_sfu = 100
    # Convert date from 2025-02-01T10:45:00 to 2025-02-01T10:45:00.000Z
    date = date.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    data = await get_dlr_data(f10p7_sfu, lat, lon, date)
    return data