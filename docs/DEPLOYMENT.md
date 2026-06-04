# Deployment Guide - Store Intelligence System

This document outlines how to run, deploy, and connect the Store Intelligence System locally and in the cloud.

---

## 1. Local Development Execution

To run the FastAPI backend server locally on your host machine:

1. **Activate the Virtual Environment**:
   ```bash
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # macOS/Linux (Bash/Zsh):
   source .venv/bin/activate
   ```
2. **Start the API Server**:
   ```bash
   PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
3. **Access the Dashboard**:
   Open `http://localhost:8000/` in your browser. The live glassmorphic dashboard will load and stream simulated/live events directly from your local server.

---

## 2. Local Deployment using Docker Compose

To deploy the API and SQLite database inside a containerized setup locally:

1. **Start the Container Service**:
   ```bash
   docker compose up --build -d
   ```
2. **Access the Dashboard**:
   Open `http://localhost:8000/` in your browser.
3. **Stop the Service**:
   ```bash
   docker compose down
   ```

---

## 3. Render Cloud Deployment (Free Tier)

Since the project is already pushed to GitHub, you can deploy the containerized application on Render for free.

### Step 1: Create a Render Web Service
1. Log in to [Render](https://render.com/).
2. Click **New +** and select **Web Service**.
3. Connect your GitHub repository.

### Step 2: Configure Deployment Settings
* **Name**: `store-intelligence` (or any name you prefer)
* **Region**: Select the region closest to you
* **Branch**: `main`
* **Runtime**: `Docker` (Render automatically detects the `Dockerfile` at the root of the project)
* **Plan Type**: `Free`

### Step 3: Add Environment Variables (Optional)
If you want to use a different database in the future, navigate to the **Environment** tab on Render and add:
* `DATABASE_URL`: `your_database_connection_string` (Defaults to local SQLite `sqlite:///./store.db` if not set)

### Step 4: Deploy
1. Click **Deploy Web Service**.
2. Render will build the Docker image and deploy it.
3. Once the build finishes, open the provided URL (e.g. `https://store-intelligence.onrender.com/`). The glassmorphic dashboard will load immediately at the root (`/`).

> [!NOTE]
> Render's free tier services spin down after 15 minutes of inactivity. The first request after a spin-down may take ~50 seconds to respond. The database is initialized and populated with POS transactions and event data on startup automatically.

---

## 4. Connecting the Computer Vision Pipeline to the Deployed API

The local Computer Vision tracking pipeline (`pipeline/run.py`) processes video feeds locally and streams behavioral events to the API.

To route events to your deployed cloud backend:

1. **Locate your Deployed URL**: E.g., `https://store-intelligence.onrender.com`
2. **Run the Pipeline with the Target URL**:
   In `pipeline/run.py`, the events are posted to the ingestion endpoint. You can run the pipeline by specifying the remote API URL using an environment variable or command-line parameters (if supported by your setup), or by setting the URL directly when executing the script.
   
   If running locally:
   ```bash
   # Set API host variable if your pipeline script supports it:
   $env:API_SERVER_URL="https://store-intelligence.onrender.com"  # Windows PowerShell
   # Or run directly on standard setups:
   python pipeline/run.py --store STORE_BLR_002
   ```
   *Note: Ensure the local machine has network access to the Render URL.*
