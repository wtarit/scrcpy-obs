#pragma once

#include <obs-module.h>

#ifdef __cplusplus
extern "C" {
#endif

char *get_bin_dir(void);
char *path_join(const char *dir, const char *leaf);
void fill_device_list(obs_property_t *list);
char *first_adb_serial(void);

#ifdef __cplusplus
}
#endif
