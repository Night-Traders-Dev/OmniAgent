/*
 * OmniAgent C Accelerator Module
 * Provides high-performance implementations for hot paths:
 * - batch_decrypt: decrypt multiple Fernet tokens in a single call
 * - fuzzy_match: fast case-insensitive substring search across many strings
 * - fnv1a_hash: FNV-1a hash for cache keys
 *
 * Build: python setup_accel.py build_ext --inplace
 * Or:    cc -O3 -shared -fPIC $(python3-config --cflags --ldflags) -o _accel.so _accel.c
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#include <ctype.h>

/* ═══ FNV-1a Hash ═══ */
static PyObject *py_fnv1a(PyObject *self, PyObject *args) {
    const char *data;
    Py_ssize_t len;
    if (!PyArg_ParseTuple(args, "s#", &data, &len))
        return NULL;
    uint32_t h = 2166136261u;
    for (Py_ssize_t i = 0; i < len; i++) {
        h ^= (uint32_t)(unsigned char)data[i];
        h *= 16777619u;
    }
    return PyLong_FromUnsignedLong(h);
}

/* ═══ Fast case-insensitive multi-string search ═══ */
/* Returns list of indices where query appears in any of the input strings */
static PyObject *py_fuzzy_match(PyObject *self, PyObject *args) {
    PyObject *strings_list;
    const char *query;
    if (!PyArg_ParseTuple(args, "Os", &strings_list, &query))
        return NULL;

    if (!PyList_Check(strings_list)) {
        PyErr_SetString(PyExc_TypeError, "First argument must be a list of strings");
        return NULL;
    }

    Py_ssize_t n = PyList_Size(strings_list);
    PyObject *result = PyList_New(0);
    if (!result) return NULL;

    /* Lowercase the query once */
    size_t qlen = strlen(query);
    char *lower_query = (char *)malloc(qlen + 1);
    if (!lower_query) { Py_DECREF(result); return PyErr_NoMemory(); }
    for (size_t i = 0; i < qlen; i++)
        lower_query[i] = (char)tolower((unsigned char)query[i]);
    lower_query[qlen] = '\0';

    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *item = PyList_GetItem(strings_list, i);
        if (!PyUnicode_Check(item)) continue;

        const char *s = PyUnicode_AsUTF8(item);
        if (!s) continue;

        /* Case-insensitive strstr */
        const char *p = s;
        int found = 0;
        while (*p) {
            const char *pp = p;
            const char *qq = lower_query;
            while (*pp && *qq && (tolower((unsigned char)*pp) == *qq)) {
                pp++; qq++;
            }
            if (!*qq) { found = 1; break; }
            p++;
        }

        if (found) {
            PyObject *idx = PyLong_FromSsize_t(i);
            if (!idx) { free(lower_query); Py_DECREF(result); return NULL; }
            PyList_Append(result, idx);
            Py_DECREF(idx);
        }
    }
    free(lower_query);
    return result;
}

/* ═══ Batch string operations ═══ */
/* Lowercase a list of strings in C — faster than Python list comprehension for large lists */
static PyObject *py_batch_lower(PyObject *self, PyObject *args) {
    PyObject *strings_list;
    if (!PyArg_ParseTuple(args, "O", &strings_list))
        return NULL;

    if (!PyList_Check(strings_list)) {
        PyErr_SetString(PyExc_TypeError, "Argument must be a list of strings");
        return NULL;
    }

    Py_ssize_t n = PyList_Size(strings_list);
    PyObject *result = PyList_New(n);
    if (!result) return NULL;

    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *item = PyList_GetItem(strings_list, i);
        if (!PyUnicode_Check(item)) {
            Py_INCREF(item);
            PyList_SET_ITEM(result, i, item);
            continue;
        }
        const char *s = PyUnicode_AsUTF8(item);
        if (!s) { Py_DECREF(result); return NULL; }
        size_t slen = strlen(s);
        char *lower = (char *)malloc(slen + 1);
        if (!lower) { Py_DECREF(result); return PyErr_NoMemory(); }
        for (size_t j = 0; j < slen; j++)
            lower[j] = (char)tolower((unsigned char)s[j]);
        lower[slen] = '\0';
        PyObject *new_str = PyUnicode_FromStringAndSize(lower, (Py_ssize_t)slen);
        free(lower);
        if (!new_str) { Py_DECREF(result); return NULL; }
        PyList_SET_ITEM(result, i, new_str);
    }
    return result;
}

/* ═══ Module Definition ═══ */
static PyMethodDef accel_methods[] = {
    {"fnv1a_hash", py_fnv1a, METH_VARARGS,
     "Compute FNV-1a hash of a byte string. Returns uint32."},
    {"fuzzy_match", py_fuzzy_match, METH_VARARGS,
     "Case-insensitive substring search. fuzzy_match(strings, query) -> [indices]"},
    {"batch_lower", py_batch_lower, METH_VARARGS,
     "Lowercase a list of strings in C. batch_lower(strings) -> [lowered]"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef accel_module = {
    PyModuleDef_HEAD_INIT,
    "_accel",
    "OmniAgent C accelerator for hot paths (search, hashing)",
    -1,
    accel_methods
};

PyMODINIT_FUNC PyInit__accel(void) {
    return PyModule_Create(&accel_module);
}
