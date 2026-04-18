#include "scrcpy-reader.h"

#include <obs-module.h>
#include <plugin-support.h>
#include <util/bmem.h>

struct scrcpy_reader {
	obs_source_t *source;
	uint16_t port;
};

scrcpy_reader_t *scrcpy_reader_create(obs_source_t *source, uint16_t port)
{
	scrcpy_reader_t *r = bzalloc(sizeof(*r));
	r->source = source;
	r->port = port;
	obs_log(LOG_INFO,
		"scrcpy-reader: stub created for port %u (decode path TODO)",
		(unsigned)port);
	return r;
}

void scrcpy_reader_destroy(scrcpy_reader_t *r)
{
	if (!r)
		return;
	bfree(r);
}
