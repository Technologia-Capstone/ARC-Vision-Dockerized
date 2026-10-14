/*
 * Native Win32 zero-console application launcher source for A.R.C. Vision.
 * Locates bundled Python runtime, sets up required DLL search directories, and launches desktop_app.py silently.
 * Handles process creation flags, error message dialog generation, and canonical directory resolution.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define BUFFER_SIZE 4096

static void ShowErrorDialog(const wchar_t* message, const wchar_t* title) {
    MessageBoxW(NULL, message, title ? title : L"A.R.C. Vision Startup Notice", MB_ICONERROR | MB_OK | MB_TOPMOST | MB_SETFOREGROUND);
}

static BOOL FileExists(const wchar_t* path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static BOOL DirectoryExists(const wchar_t* path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY));
}

static void Canonicalize(const wchar_t* src, wchar_t* dest, DWORD destSize) {
    if (GetFullPathNameW(src, destSize, dest, NULL) == 0) {
        wcsncpy(dest, src, destSize - 1);
        dest[destSize - 1] = L'\0';
    }
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)pCmdLine;
    (void)nCmdShow;

    wchar_t exePath[BUFFER_SIZE];
    wchar_t exeDir[BUFFER_SIZE];
    wchar_t backendDir[BUFFER_SIZE];
    wchar_t pythonwExe[BUFFER_SIZE];
    wchar_t targetScript[BUFFER_SIZE];
    wchar_t cmdLine[BUFFER_SIZE * 2];
    wchar_t rawPath[BUFFER_SIZE];

    // 1. Get location of running executable
    if (GetModuleFileNameW(NULL, exePath, BUFFER_SIZE) == 0) {
        ShowErrorDialog(L"Failed to determine executable location.", L"A.R.C. Vision Startup Error");
        return 1;
    }

    // Strip executable name to get directory
    wcscpy(exeDir, exePath);
    wchar_t* lastSlash = wcsrchr(exeDir, L'\\');
    if (lastSlash) {
        *lastSlash = L'\0';
    } else {
        wcscpy(exeDir, L".");
    }

    // 2. Resolve Back End directory with canonicalized paths
    backendDir[0] = L'\0';

    // Candidate 1: exeDir\..\Source Code\Back End (running from "app" folder)
    swprintf(rawPath, BUFFER_SIZE, L"%ls\\..\\Source Code\\Back End", exeDir);
    Canonicalize(rawPath, backendDir, BUFFER_SIZE);

    if (!DirectoryExists(backendDir)) {
        // Candidate 2: exeDir\Source Code\Back End (running from root)
        swprintf(rawPath, BUFFER_SIZE, L"%ls\\Source Code\\Back End", exeDir);
        Canonicalize(rawPath, backendDir, BUFFER_SIZE);

        if (!DirectoryExists(backendDir)) {
            // Candidate 3: exeDir (running directly inside "Source Code\Back End")
            Canonicalize(exeDir, backendDir, BUFFER_SIZE);
        }
    }

    // 3. Ensure input and output folders exist
    wchar_t inputDir[BUFFER_SIZE];
    wchar_t outputDir[BUFFER_SIZE];
    swprintf(inputDir, BUFFER_SIZE, L"%ls\\input", backendDir);
    swprintf(outputDir, BUFFER_SIZE, L"%ls\\output", backendDir);
    CreateDirectoryW(inputDir, NULL);
    CreateDirectoryW(outputDir, NULL);

    // 4. Locate Python executable runtime (.python_win / .venv / system)
    pythonwExe[0] = L'\0';

    // Candidate A: .python_win\pythonw.exe
    swprintf(rawPath, BUFFER_SIZE, L"%ls\\.python_win\\pythonw.exe", backendDir);
    Canonicalize(rawPath, pythonwExe, BUFFER_SIZE);

    if (!FileExists(pythonwExe)) {
        // Candidate B: .python_win\python.exe
        swprintf(rawPath, BUFFER_SIZE, L"%ls\\.python_win\\python.exe", backendDir);
        Canonicalize(rawPath, pythonwExe, BUFFER_SIZE);

        if (!FileExists(pythonwExe)) {
            // Candidate C: .venv\Scripts\pythonw.exe
            swprintf(rawPath, BUFFER_SIZE, L"%ls\\.venv\\Scripts\\pythonw.exe", backendDir);
            Canonicalize(rawPath, pythonwExe, BUFFER_SIZE);

            if (!FileExists(pythonwExe)) {
                // Candidate D: .venv\Scripts\python.exe
                swprintf(rawPath, BUFFER_SIZE, L"%ls\\.venv\\Scripts\\python.exe", backendDir);
                Canonicalize(rawPath, pythonwExe, BUFFER_SIZE);

                if (!FileExists(pythonwExe)) {
                    // Fallback to system PATH
                    wcscpy(pythonwExe, L"pythonw.exe");
                }
            }
        }
    }

    // 5. Verify target script exists
    swprintf(rawPath, BUFFER_SIZE, L"%ls\\desktop_app.py", backendDir);
    Canonicalize(rawPath, targetScript, BUFFER_SIZE);

    if (!FileExists(targetScript)) {
        swprintf(rawPath, BUFFER_SIZE, L"%ls\\launcher_win.py", backendDir);
        Canonicalize(rawPath, targetScript, BUFFER_SIZE);

        if (!FileExists(targetScript)) {
            swprintf(rawPath, BUFFER_SIZE, L"%ls\\server.py", backendDir);
            Canonicalize(rawPath, targetScript, BUFFER_SIZE);
        }
    }

    // 6. Configure environment variables (DLL paths)
    wchar_t pyWinDir[BUFFER_SIZE];
    swprintf(rawPath, BUFFER_SIZE, L"%ls\\.python_win", backendDir);
    Canonicalize(rawPath, pyWinDir, BUFFER_SIZE);

    if (DirectoryExists(pyWinDir)) {
        wchar_t newPath[BUFFER_SIZE * 4];
        wchar_t origPath[BUFFER_SIZE * 2];
        origPath[0] = L'\0';
        GetEnvironmentVariableW(L"PATH", origPath, BUFFER_SIZE * 2);

        swprintf(newPath, BUFFER_SIZE * 4,
            L"%ls;"
            L"%ls\\Lib\\site-packages;"
            L"%ls\\Lib\\site-packages\\torch\\lib;"
            L"%ls\\Lib\\site-packages\\onnxruntime\\capi;"
            L"%ls\\Lib\\site-packages\\cv2;"
            L"%ls\\Lib\\site-packages\\numpy.libs;"
            L"%ls\\Lib\\site-packages\\scipy.libs;"
            L"%ls\\Lib\\site-packages\\ml_dtypes.libs;"
            L"%ls",
            pyWinDir, pyWinDir, pyWinDir, pyWinDir, pyWinDir, pyWinDir, pyWinDir, pyWinDir,
            origPath
        );
        SetEnvironmentVariableW(L"PATH", newPath);
    }

    // 7. Format command line
    swprintf(cmdLine, BUFFER_SIZE * 2, L"\"%ls\" \"%ls\"", pythonwExe, targetScript);

    // 8. Launch background process
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&pi, sizeof(pi));

    BOOL success = CreateProcessW(
        NULL,
        cmdLine,
        NULL,
        NULL,
        FALSE,
        CREATE_NO_WINDOW | DETACHED_PROCESS,
        NULL,
        backendDir,
        &si,
        &pi
    );

    if (!success) {
        DWORD err = GetLastError();
        wchar_t errMsg[BUFFER_SIZE * 2];
        swprintf(errMsg, BUFFER_SIZE * 2,
            L"Failed to launch A.R.C. Vision Windows Application.\n\n"
            L"Executable: %ls\n"
            L"Script: %ls\n"
            L"Working Dir: %ls\n"
            L"System Error Code: %lu\n\n"
            L"Please verify that the entire project ZIP folder was fully extracted before launching.",
            pythonwExe, targetScript, backendDir, err
        );
        ShowErrorDialog(errMsg, L"A.R.C. Vision Startup Error");
        return 1;
    }

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    return wWinMain(hInstance, hPrevInstance, GetCommandLineW(), nCmdShow);
}
