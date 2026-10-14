/*
 * Native macOS launcher binary source for A.R.C. Vision.
 * Resolves application bundle paths, sets system environment paths, and bootstraps desktop_app.py.
 * Handles working directory configuration, input/output directory verification, and process execution.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <sys/stat.h>
#include <limits.h>

int main(int argc, char* argv[]) {
    char exePath[PATH_MAX];
    uint32_t size = sizeof(exePath);
    if (_NSGetExecutablePath(exePath, &size) != 0) {
        return 1;
    }

    char resolvedExe[PATH_MAX];
    if (!realpath(exePath, resolvedExe)) {
        strncpy(resolvedExe, exePath, PATH_MAX);
    }

    // Find the .app bundle directory
    char appDir[PATH_MAX];
    strncpy(appDir, resolvedExe, PATH_MAX);
    char* contentsPos = strstr(appDir, "/Contents/MacOS");
    if (contentsPos) {
        *contentsPos = '\0';
    }

    // Strip the .app name to get containing folder
    char containerDir[PATH_MAX];
    strncpy(containerDir, appDir, PATH_MAX);
    char* lastSlash = strrchr(containerDir, '/');
    if (lastSlash) {
        *lastSlash = '\0';
    }

    // Find Source Code/Back End
    char backendDir[PATH_MAX];
    struct stat st;

    // Check 1: containerDir/Source Code/Back End
    snprintf(backendDir, sizeof(backendDir), "%s/Source Code/Back End", containerDir);
    if (stat(backendDir, &st) != 0 || !S_ISDIR(st.st_mode)) {
        // Check 2: containerDir/../Source Code/Back End (when app is in app/ subfolder)
        snprintf(backendDir, sizeof(backendDir), "%s/../Source Code/Back End", containerDir);
        if (stat(backendDir, &st) != 0 || !S_ISDIR(st.st_mode)) {
            // Check 3: fallback
            snprintf(backendDir, sizeof(backendDir), "%s", containerDir);
        }
    }

    char canonicalBackend[PATH_MAX];
    if (realpath(backendDir, canonicalBackend)) {
        strncpy(backendDir, canonicalBackend, PATH_MAX);
    }

    // Resolve python executable in backendDir/.venv/bin/python
    char pythonExe[PATH_MAX];
    snprintf(pythonExe, sizeof(pythonExe), "%s/.venv/bin/python", backendDir);
    if (stat(pythonExe, &st) != 0) {
        strncpy(pythonExe, "/usr/bin/python3", sizeof(pythonExe));
    }

    // Resolve desktop_app.py
    char scriptPath[PATH_MAX];
    snprintf(scriptPath, sizeof(scriptPath), "%s/desktop_app.py", backendDir);

    // Set PATH
    const char* currentPath = getenv("PATH");
    char newPath[PATH_MAX * 4];
    snprintf(newPath, sizeof(newPath), "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:%s", currentPath ? currentPath : "");
    setenv("PATH", newPath, 1);

    // Change working directory to backendDir
    chdir(backendDir);

    // Ensure input and output directories exist
    mkdir("input", 0755);
    mkdir("output", 0755);

    // Execute python desktop_app.py
    char* execArgs[] = {
        pythonExe,
        scriptPath,
        NULL
    };

    execv(pythonExe, execArgs);
    return 1;
}
