#include "PythonBridge.h"

#include <Python.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

static bool mesh_python_started = false;

static int append_path(PyConfig *config, const wchar_t *root, const wchar_t *suffix) {
    size_t size = wcslen(root) + wcslen(suffix) + 1;
    wchar_t *path = calloc(size, sizeof(wchar_t));
    if (path == NULL) return -1;
    wcscpy(path, root);
    wcscat(path, suffix);
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, path);
    free(path);
    return PyStatus_Exception(status) ? -1 : 0;
}

int mesh_python_start(const char *resource_path) {
    if (mesh_python_started) return 0;
    if (resource_path == NULL) return -1;

    wchar_t *resource = Py_DecodeLocale(resource_path, NULL);
    if (resource == NULL) return -1;

    PyPreConfig preconfig;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;
    PyStatus status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) {
        PyMem_RawFree(resource);
        return -1;
    }

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.buffered_stdio = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 1;
    config.module_search_paths_set = 1;

    size_t home_size = wcslen(resource) + wcslen(L"/python") + 1;
    wchar_t *home = calloc(home_size, sizeof(wchar_t));
    if (home == NULL) {
        PyConfig_Clear(&config);
        PyMem_RawFree(resource);
        return -1;
    }
    wcscpy(home, resource);
    wcscat(home, L"/python");
    status = PyConfig_SetString(&config, &config.home, home);
    free(home);
    if (PyStatus_Exception(status) ||
        append_path(&config, resource, L"/python/lib/python3.13") != 0 ||
        append_path(&config, resource, L"/python/lib/python3.13/lib-dynload") != 0 ||
        append_path(&config, resource, L"/app_packages") != 0) {
        PyConfig_Clear(&config);
        PyMem_RawFree(resource);
        return -1;
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    PyMem_RawFree(resource);
    if (PyStatus_Exception(status)) return -1;

    mesh_python_started = true;
    PyEval_SaveThread();
    return 0;
}

char *mesh_python_invoke(const char *function_name, const char *json_request) {
    if (!mesh_python_started || function_name == NULL) return NULL;
    PyGILState_STATE gil = PyGILState_Ensure();
    char *output = NULL;
    PyObject *module = PyImport_ImportModule("mesh_chat.mobile_bridge");
    if (module != NULL) {
        PyObject *function = PyObject_GetAttrString(module, function_name);
        if (function != NULL && PyCallable_Check(function)) {
            PyObject *result = json_request == NULL
                ? PyObject_CallNoArgs(function)
                : PyObject_CallFunction(function, "s", json_request);
            if (result != NULL) {
                const char *value = PyUnicode_AsUTF8(result);
                if (value != NULL) output = strdup(value);
                Py_DECREF(result);
            }
            Py_XDECREF(function);
        }
        Py_DECREF(module);
    }
    if (PyErr_Occurred()) PyErr_Clear();
    PyGILState_Release(gil);
    return output;
}

void mesh_python_free(char *value) {
    free(value);
}
