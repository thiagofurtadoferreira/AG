#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define PATH_CAPACITY 32768

static int show_error(const wchar_t *message) {
#ifdef CONSOLE
    fwprintf(stderr, L"Simulador de Cotacao: %ls\n", message);
#else
    MessageBoxW(NULL, message, L"Simulador de Cotação", MB_OK | MB_ICONERROR);
#endif
    return 1;
}

static const wchar_t *arguments(void) {
    const wchar_t *p = GetCommandLineW();
    if (*p == L'"') {
        ++p;
        while (*p && *p != L'"') ++p;
        if (*p) ++p;
    } else {
        while (*p && *p != L' ' && *p != L'\t') ++p;
    }
    while (*p == L' ' || *p == L'\t') ++p;
    return p;
}

static int launch(void) {
    wchar_t dir[PATH_CAPACITY];
    wchar_t python[PATH_CAPACITY];
    wchar_t app[PATH_CAPACITY];
    DWORD count = GetModuleFileNameW(NULL, dir, PATH_CAPACITY);
    if (!count || count >= PATH_CAPACITY) return show_error(L"Caminho do aplicativo inválido.");
    wchar_t *separator = wcsrchr(dir, L'\\');
    if (!separator) return show_error(L"Pasta do aplicativo inválida.");
    *separator = L'\0';
#ifdef CONSOLE
    const wchar_t *interpreter = L"python.exe";
    const wchar_t *mode = L" --cli";
#else
    const wchar_t *interpreter = L"pythonw.exe";
    const wchar_t *mode = L"";
#endif
    if (swprintf(python, PATH_CAPACITY, L"%ls\\runtime\\%ls", dir, interpreter) < 0 ||
        swprintf(app, PATH_CAPACITY, L"%ls\\app.py", dir) < 0)
        return show_error(L"Caminho do aplicativo longo demais.");
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(app) == INVALID_FILE_ATTRIBUTES)
        return show_error(L"Extraia todo o ZIP antes de abrir o executável.");

    const wchar_t *args = arguments();
    size_t size = wcslen(python) + wcslen(app) + wcslen(mode) + wcslen(args) + 12;
    wchar_t *command = calloc(size, sizeof(*command));
    if (!command) return show_error(L"Memória insuficiente.");
    swprintf(command, size, L"\"%ls\" \"%ls\"%ls %ls", python, app, mode, args);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION child = {0};
    startup.cb = sizeof(startup);
    BOOL started = CreateProcessW(python, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &child);
    free(command);
    if (!started) return show_error(L"Falha ao iniciar o runtime do simulador.");
    CloseHandle(child.hThread);
    DWORD code = 0;
#ifdef CONSOLE
    WaitForSingleObject(child.hProcess, INFINITE);
    if (!GetExitCodeProcess(child.hProcess, &code)) code = 1;
#endif
    CloseHandle(child.hProcess);
    return (int)code;
}

#ifdef CONSOLE
int wmain(void) { return launch(); }
#else
int WINAPI wWinMain(HINSTANCE current, HINSTANCE previous, PWSTR args, int options) {
    (void)current; (void)previous; (void)args; (void)options;
    return launch();
}
#endif
