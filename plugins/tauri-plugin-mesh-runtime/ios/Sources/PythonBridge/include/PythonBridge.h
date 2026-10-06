#ifndef MESH_CHAT_PYTHON_BRIDGE_H
#define MESH_CHAT_PYTHON_BRIDGE_H

int mesh_python_start(const char *resource_path);
char *mesh_python_invoke(const char *function_name, const char *json_request);
void mesh_python_free(char *value);

#endif
