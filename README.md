# A.R.C. Vision — Automated Recognition and Clustering

A.R.C. Vision is an automated event photograph sorting and identity clustering system that organizes event photographs into person-based groups using facial recognition, ArcFace identity embeddings, DBSCAN clustering, and an interactive web dashboard.

The project supports three deployment options:

1. **Docker Hub** — download and run the published Docker image.
2. **Build from Source** — build and run the application locally using Docker.
3. **Standalone Desktop Application** — launch the application directly on supported macOS and Windows systems.

---

# 1. Docker Hub Deployment

This section explains how to download and run the published A.R.C. Vision Docker image.

## 1.1 Prerequisites

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure that Docker is running before proceeding.

The published `latest` Docker image supports Windows, Linux, and macOS computers.

## 1.2 Docker Hub Repository

The published Docker image is available at:

**Docker Hub:** https://hub.docker.com/r/kkumaarr/arc-vision

**Image name:** `kkumaarr/arc-vision:latest`

## 1.3 Download the Docker Image

Open Terminal on macOS or a terminal or Command Prompt on Windows and execute:

```bash
docker pull kkumaarr/arc-vision:latest
```

This command downloads the published image and its packaged application dependencies from Docker Hub.

## 1.4 Run the Application

After downloading the image, execute:

```bash
docker run -d \
  --name arc-vision \
  -p 8000:8000 \
  kkumaarr/arc-vision:latest
```

This starts the application in the background and maps port `8000` inside the container to port `8000` on the host computer.

## 1.5 Access the Dashboard

Open a web browser and navigate to:

**http://localhost:8000**

The A.R.C. Vision dashboard should load.

During the initial startup, the application may need to download or initialize the InsightFace `buffalo_l` recognition model. An internet connection may be required if the model is not already available locally.

## 1.6 Verify the Application

Check the container status:

```bash
docker ps
```

Check the API health endpoint:

```bash
curl http://localhost:8000/api/health
```

View the application logs:

```bash
docker logs -f arc-vision
```

Press `Ctrl + C` to exit the log display without stopping the container.

## 1.7 Stop, Restart, or Remove the Container

Stop the application:

```bash
docker stop arc-vision
```

Start the stopped container again:

```bash
docker start arc-vision
```

Remove the container:

```bash
docker rm -f arc-vision
```

Removing the container does not remove the downloaded image. However, files stored only inside the container may be lost when the container is removed.

**Important:** For persistent input photographs, processed results, and recognition models, configure host-directory mounts as described in Section 2.5.

---

# 2. Build and Run from Source

This section describes how to obtain the project from GitHub and build the Docker image locally.

## 2.1 Prerequisites

Install the following:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/downloads/) (optional if downloading the repository as a ZIP file)

Start Docker Desktop and wait until Docker is running.

## 2.2 Download the Project

**Option A — Clone using Git**

Open a terminal and execute:

```bash
git clone https://github.com/Technologia-Capstone/ARC-Vision-Dockerized.git
cd ARC-Vision-Dockerized
```

**Option B — Download as a ZIP file**

1. Open the [GitHub repository](https://github.com/Technologia-Capstone/ARC-Vision-Dockerized).
2. Select **Code → Download ZIP**.
3. Extract the downloaded archive.
4. Open a terminal in the extracted project directory.

Ensure that the project root contains `Dockerfile`, `compose.yaml`, and the `Source Code` directory.

## 2.3 Build the Docker Image

From the project root, run:

```bash
docker build -t arc-vision:latest .
```

This command builds the Docker image using the project's Dockerfile.

The first build may take several minutes or longer, depending on internet speed and dependency installation. Subsequent builds may be faster when Docker can reuse cached layers.

## 2.4 Start the Application

Start the application using Docker Compose:

```bash
docker compose up --build -d
```

Docker Compose builds the image when needed and starts the configured application service in the background.

The supplied `compose.yaml` configures the service, port mapping, and host-directory mounts.

## 2.5 Persistent Data Storage

The Docker Compose configuration mounts the following host directories into the container:

| Host directory | Container directory | Purpose |
|---|---|---|
| `Source Code/Back End/input/` | `/app/input/` | Input photographs |
| `Source Code/Back End/output/` | `/app/output/` | Processed photographs and generated results |
| `Source Code/Back End/.models/` | `/app/.models/` | Cached recognition models |

These mounts allow the corresponding files to persist outside the container when it is stopped or rebuilt.

**Important:** Do not delete these directories if their contents are needed. Avoid using `docker compose down -v` unless you understand the consequences.

## 2.6 Access the Dashboard

Open a web browser and visit:

**http://localhost:8000**

## 2.7 Monitor the Application

Check the service status:

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

Press `Ctrl + C` to exit the log display without stopping the service.

## 2.8 Stop or Restart the Application

Stop and remove the Compose containers:

```bash
docker compose down
```

Start the application again:

```bash
docker compose up -d
```

Restart the application:

```bash
docker compose restart
```

These commands do not normally delete files stored in the host directories mapped in Section 2.5.

---

# 3. Standalone Desktop Application

A.R.C. Vision also provides desktop launchers for supported macOS and Windows environments.

Open the `app` directory in the downloaded project.

## 3.1 macOS

Launch:

```text
app/A.R.C. Vision.app
```

The application opens in a dedicated desktop window using Cocoa WKWebView.

## 3.2 Windows

Use either of the following launchers:

- `A.R.C. Vision.bat` — recommended launcher.
- `A.R.C. Vision (Silent).vbs` — launches without a visible console window.

The Windows launcher is designed to use its bundled Python runtime, dependencies, and recognition models.

## 3.3 Initial Startup

Allow additional time during the first launch for the local runtime to initialize and for the InsightFace `buffalo_l` models to load. Startup time varies depending on the computer and whether model downloads or initialization are required.

---

# 4. Running Automated Tests

To run the Python test suite in a compatible Python environment, open a terminal and execute:

```bash
cd "Source Code/Back End"
python -m unittest discover tests
```

The test suite includes tests covering areas such as scale benchmarks, confidence evaluations, cluster merging, duplicate resolution, and manual photo management.

The number of tests may change as the project evolves.

---

# 5. Key Features

## 5.1 Multi-Modal Recognition Engine

- ArcFace facial identity embeddings with 512 dimensions using InsightFace `buffalo_l`.
- MTCNN face detection through `facenet-pytorch`.
- Clothing-color histogram extraction from the torso region.
- Spatial bounding-box geometry integration.
- Weighted feature fusion: 85% facial features, 10% clothing color, and 5% spatial geometry.

## 5.2 Three-Tier Face Cluster Explorer

- **Tier 1 — Events:** Overview of uploaded event folders, processing status, and photograph counts.
- **Tier 2 — Person Clusters:** Circular avatar grid with face counts and hover previews.
- **Tier 3 — Photo Gallery:** Full-resolution gallery with interactive lightbox previews.

## 5.3 Intelligent Cluster Merging

- Combine detected clusters into a single person folder.
- Choose whether to retain duplicate photographs or deduplicate them by original filename.

## 5.4 Manual Photo Management

- Add photographs from existing clusters or a device to multiple clusters.
- Delete selected photographs without affecting other copies.
- Move photographs between clusters.

## 5.5 Multi-Cluster Flagging and Restoration

- Persistent origin tracking through `flag_origins.json`.
- Flagging moves images to the `Unknown/` folder.
- Unflagging restores copies to their previous origin clusters.

## 5.6 Asynchronous ZIP Export

- Background ZIP packaging.
- Live progress indicators and images-per-second reporting.
- Automatic pruning of temporary export archives.

## 5.7 Performance and Scalability

Designed for event-photography workloads, with reported benchmarks of up to 3,000 photographs and 25 GB per event batch. Actual performance depends on hardware, photograph characteristics, and available resources.

---

# 6. Project Structure

```text
ARC-Vision-Dockerized/
├── Dockerfile
├── compose.yaml
├── README.md
├── PROJECT_STRUCTURE.md
├── Source Code/
│   ├── Back End/
│   │   ├── requirements.txt
│   │   └── ...
│   └── Front End/
│       └── ...
└── app/
    └── Desktop application launchers
```

- `Dockerfile` — defines the Docker image and its runtime environment.
- `compose.yaml` — configures the Docker service, ports, and persistent directories.
- `PROJECT_STRUCTURE.md` — documents the project's structure.
- `Source Code/Back End/` — backend, recognition pipeline, and tests.
- `Source Code/Front End/` — HTML, CSS, JavaScript, and media assets.
- `app/` — desktop application launchers for supported operating systems.

---

# 7. Troubleshooting

## Docker Desktop Is Not Running

Open Docker Desktop and wait until it finishes starting.

## Port 8000 Is Already in Use

Stop the other application using port `8000` or change the host-side port mapping.

For example, `-p 8080:8000` makes the dashboard available at `http://localhost:8080`.

## The Dashboard Does Not Open

Check the container status and logs:

```bash
docker ps -a
docker logs --tail=100 arc-vision
```

For Docker Compose deployments:

```bash
docker compose ps
docker compose logs --tail=100 arc-vision
```

## The First Startup Takes Longer Than Expected

The application may be initializing its runtime or downloading the recognition model. Check the logs and allow additional time for the initial setup.

## The Docker Image Cannot Be Downloaded

Confirm that Docker Desktop is running and that the computer has an internet connection. Then retry:

```bash
docker pull kkumaarr/arc-vision:latest
```

---

# 8. Project Links

- **GitHub Repository:** https://github.com/Technologia-Capstone/ARC-Vision-Dockerized
- **Docker Hub Repository:** https://hub.docker.com/r/kkumaarr/arc-vision
- **Published Docker Image:** `kkumaarr/arc-vision:latest`

To download the published image:

```bash
docker pull kkumaarr/arc-vision:latest
```
