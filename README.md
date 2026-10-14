# A.R.C. Vision — Automated Recognition and Clustering

**A.R.C. Vision** is an automated event photo sorting and identity clustering system. It organizes event photographs into person-based groups using multi-modal face recognition, ArcFace identity embeddings, DBSCAN clustering, and an interactive web dashboard.

This project supports two ways to run the application:

1. **GitHub and Docker** — build and run the containerized application.
2. **Running Locally** — launch the standalone desktop application on macOS or Windows.

---

# 1. GitHub and Docker

This section explains how to obtain the project from GitHub and run it using Docker.

## 1.1 Requirements

Install the following:

* [Docker Desktop](https://www.docker.com/products/docker-desktop/)
* [Git](https://git-scm.com/downloads/) (optional if downloading the project as a ZIP file)

Start Docker Desktop and wait until Docker is running.

## 1.2 Download the Project

**Option A — Clone using Git**

Open a terminal and run:

```bash
git clone YOUR_REPOSITORY_URL
```

Replace `YOUR_REPOSITORY_URL` with the URL of the GitHub repository.

Navigate into the downloaded project folder:

```bash
cd PhotoClust_Docker
```

The folder name may differ if you cloned a repository with another name.

**Option B — Download as a ZIP file**

1. Open the project repository on GitHub.
2. Click **Code → Download ZIP**.
3. Extract the ZIP file.
4. Open a terminal in the extracted project folder.

Make sure the folder contains both `Dockerfile` and `compose.yaml` before continuing.

## 1.3 Build the Docker Image

A Docker image packages the application environment and its dependencies.

Run the following command from the project root:

```bash
docker build -t arc-vision:latest .
```

Command explanation:

* `docker build` builds the image.
* `-t arc-vision:latest` assigns the image the name `arc-vision` and tag `latest`.
* `.` specifies the current directory as the build context.

The first build may take several minutes while Docker downloads the base image and installs dependencies.

## 1.4 Start the Application

Run:

```bash
docker compose up --build -d
```

This command builds the image when needed and starts the application in the background.

The project uses `compose.yaml` to configure the container, port mapping, and persistent storage directories.

## 1.5 Open A.R.C. Vision

Once the container has started, open your browser and visit:

**http://localhost:8000**

The application dashboard should load.

On the first startup, the system may need to download or initialize its InsightFace recognition model. An internet connection may be required if the model is not already cached.

## 1.6 Verify the Application

Check the container status:

```bash
docker compose ps
```

Check the API health endpoint:

```bash
curl http://localhost:8000/api/health
```

View application logs:

```bash
docker compose logs -f arc-vision
```

Press `Ctrl + C` to exit the log display. This does not stop the application.

## 1.7 Stop or Restart the Application

**Stop the application:**

```bash
docker compose down
```

**Start it again later:**

```bash
docker compose up -d
```

**Restart the application:**

```bash
docker compose restart
```

## 1.8 Docker Image and Container Names

| Item                   | Name                | Description                                          |
| ---------------------- | ------------------- | ---------------------------------------------------- |
| Project folder         | `PhotoClust_Docker` | The project directory on your computer               |
| Docker image           | `arc-vision:latest` | The packaged application image                       |
| Docker Compose service | `arc-vision`        | The application service configured in `compose.yaml` |

## 1.9 Data Storage

The following directories are mounted from your computer into the container:

* `Source Code/Back End/input/` — input photos.
* `Source Code/Back End/output/` — processed photos and generated results.
* `Source Code/Back End/.models/` — cached recognition models.

These directories allow data to persist when the container is stopped or rebuilt.

**Important:** Do not delete these folders if you need their contents. Avoid `docker compose down -v` unless you understand the consequences.

## 1.10 Troubleshooting

**Docker is not running**

Open Docker Desktop and wait for it to finish starting.

**Port 8000 is already in use**

Stop the other application using port 8000 or update the port mapping in `compose.yaml`.

**The dashboard does not open**

Check the container status and logs:

```bash
docker compose ps
docker compose logs --tail=100 arc-vision
```

**The first startup takes a long time**

The application may be downloading or initializing the recognition model. Allow additional time for the initial setup.

---

# 2. Running Locally

This section describes how to launch A.R.C. Vision directly on your computer without using Docker.

## 2.1 Standalone Desktop Application Launchers

Open the `app` folder.

### macOS

Double-click:

```text
app/A.R.C. Vision.app
```

* **Native Desktop Window:** Opens in a dedicated Cocoa WKWebView desktop window.
* **Automatic Startup:** Launches the application through its bundled launcher.

### Windows

Open the `app` folder and double-click either launcher:

* `A.R.C. Vision.bat` — recommended Windows application launcher.
* `A.R.C. Vision (Silent).vbs` — launches without a visible console window.

The Windows application is designed to use its bundled Python runtime, dependencies, and recognition models.

## 2.2 Cold-Start Note

**Initial launch:** Allow approximately 5–10 seconds for the application to initialize its local runtime and load the InsightFace `buffalo_l` models. Startup time may vary depending on the computer and whether initialization or model downloads are required.

## 2.3 Running Automated Tests

To run the Python test suite in a compatible Python environment, open a terminal and execute:

```bash
cd "Source Code/Back End"
python -m unittest discover tests
```

The existing test suite covers areas including scale benchmarks, confidence evaluations, cluster merging, duplicate resolution, and manual photo management.

The number of tests may change as the project evolves.

---

# Key Features

## 1. Multi-Modal Recognition Engine

* Pretrained ArcFace 512-dimensional facial identity embeddings using InsightFace `buffalo_l`.
* Clothing-color histogram feature extraction from the torso region.
* Spatial bounding-box geometry integration.
* Weighted multi-modal fusion: 85% facial features, 10% clothing color, and 5% spatial geometry.

## 2. Three-Tier Face Cluster Explorer

* **Tier 1 — Events:** Overview of uploaded event folders, processing status, and photo counts.
* **Tier 2 — Person Clusters:** Circular avatar grid with face counts and hover previews.
* **Tier 3 — Photo Gallery:** Full-resolution gallery with interactive lightbox previews.

## 3. Intelligent Cluster Merging

* Combine detected clusters into a single person folder.
* Choose between keeping duplicates and deduplicating by original filename.

## 4. Manual Photo Management

* Add photos from existing clusters or a device to multiple clusters.
* Delete selected photos without affecting other copies.
* Move photos between clusters.

## 5. Multi-Cluster Flagging and Restoration

* Persistent origin tracking using `flag_origins.json`.
* Flagging moves images to the `Unknown/` folder.
* Unflagging restores copies to their previous origin clusters.

## 6. Real-Time Asynchronous ZIP Export

* Background ZIP packaging.
* Live progress indicators and images-per-second reporting.
* Automatic pruning of temporary export archives.

## 7. High-Performance Architecture

Designed and tested for event-photo workloads, including reported scale benchmarks of up to 3,000 photos and 25 GB per event batch.

---

# Project Structure

* `Dockerfile` — defines how the Docker image is built.
* `compose.yaml` — configures the Docker service, ports, and persistent directories.
* `.dockerignore` — excludes unnecessary files from the Docker build context.
* `.gitignore` — excludes files that should not be uploaded to Git.
* `Source Code/Back End/` — backend, recognition pipeline, and tests.
* `Source Code/Front End/` — HTML, CSS, JavaScript, and media assets.
* `app/` — desktop launchers for supported operating systems.
