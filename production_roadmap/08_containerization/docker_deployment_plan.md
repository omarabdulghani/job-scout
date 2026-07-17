# 08 - Infrastructure: Containerization Plan (Docker)

## 1. The Core Vulnerability: "It works on my machine"
Currently, the application runs directly on your Windows OS. The app requires Python 3.12, Playwright binaries, specific browser engine versions, and local SQLite access. 

**Why this is dangerous:**
If you want to run this app on a cloud server (like an AWS EC2 instance or DigitalOcean Droplet) to scrape jobs 24/7, or if a friend wants to run it on a Macbook, they will have to spend hours setting up the environment. If their OS has conflicting Python paths or missing C++ redistributables, the app will crash.

## 2. The Implementation Plan for the Fix
*When executing this fix, isolate it on a feature branch (`feature/08-containerization`).*

### Step 1: Write the Dockerfile
We will create a `Dockerfile` at the root of the project. This defines an isolated Linux environment (a container) that packages the app, Python, and the Playwright browser binaries into a single, portable box.
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "serve_dashboard.py"]
```

### Step 2: Write the Docker Compose Configuration
To manage the local volumes (so your SQLite database and `.env` file persist even if the container restarts), we will create a `docker-compose.yml` file. This allows mapping your local `data/` folder inside the container.

### Step 3: Streamline the Startup Process
We will replace the complex Python installation instructions in the `README.md` with a single, universally recognized command:
`docker-compose up -d`

## 3. Verification & Safeguards
We will build the container locally using `docker build`. We will verify that the internal Python process can successfully spawn Playwright inside the isolated Linux container, connect to the mapped SQLite database on the host machine, and serve the dashboard on `localhost:8000`.
