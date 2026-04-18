#include "scrcpy-process.h"

#include <obs-module.h>
#include <plugin-support.h>
#include <util/dstr.h>
#include <util/platform.h>

#include <string.h>

#ifdef _WIN32

static void quote_arg(struct dstr *out, const char *arg)
{
	bool need_quote = (*arg == '\0') || strpbrk(arg, " \t\"") != NULL;
	if (!need_quote) {
		dstr_cat(out, arg);
		return;
	}
	dstr_cat(out, "\"");
	size_t backslashes = 0;
	for (const char *p = arg; *p; ++p) {
		if (*p == '\\') {
			backslashes++;
		} else if (*p == '"') {
			for (size_t i = 0; i < backslashes * 2 + 1; ++i)
				dstr_cat(out, "\\");
			dstr_cat_ch(out, '"');
			backslashes = 0;
		} else {
			for (size_t i = 0; i < backslashes; ++i)
				dstr_cat(out, "\\");
			dstr_cat_ch(out, *p);
			backslashes = 0;
		}
	}
	for (size_t i = 0; i < backslashes * 2; ++i)
		dstr_cat(out, "\\");
	dstr_cat(out, "\"");
}

static wchar_t *utf8_to_wide(const char *utf8)
{
	if (!utf8)
		return NULL;
	int need = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, NULL, 0);
	if (need <= 0)
		return NULL;
	wchar_t *w = bmalloc((size_t)need * sizeof(wchar_t));
	MultiByteToWideChar(CP_UTF8, 0, utf8, -1, w, need);
	return w;
}

static void build_env_block(struct dstr *env_block,
			    const char *server_path,
			    const char *adb_dir)
{
	wchar_t *existing = GetEnvironmentStringsW();
	for (wchar_t *p = existing; *p; p += wcslen(p) + 1) {
		int u8_len = WideCharToMultiByte(CP_UTF8, 0, p, -1, NULL, 0, NULL, NULL);
		char *u8 = bmalloc((size_t)u8_len);
		WideCharToMultiByte(CP_UTF8, 0, p, -1, u8, u8_len, NULL, NULL);
		bool skip = false;
		if (server_path && _strnicmp(u8, "SCRCPY_SERVER_PATH=", 19) == 0)
			skip = true;
		if (adb_dir && _strnicmp(u8, "PATH=", 5) == 0)
			skip = true;
		if (!skip)
			dstr_ncat(env_block, u8, (size_t)u8_len);
		bfree(u8);
	}
	FreeEnvironmentStringsW(existing);

	if (server_path) {
		struct dstr e = {0};
		dstr_printf(&e, "SCRCPY_SERVER_PATH=%s", server_path);
		dstr_ncat(env_block, e.array, e.len + 1);
		dstr_free(&e);
	}
	if (adb_dir) {
		const char *cur_path = getenv("PATH");
		struct dstr e = {0};
		if (cur_path && *cur_path)
			dstr_printf(&e, "PATH=%s;%s", adb_dir, cur_path);
		else
			dstr_printf(&e, "PATH=%s", adb_dir);
		dstr_ncat(env_block, e.array, e.len + 1);
		dstr_free(&e);
	}
	dstr_cat_ch(env_block, '\0');
}

bool scrcpy_proc_spawn(scrcpy_proc_t *proc,
		       const char *exe_path,
		       const char *const *argv,
		       const char *server_path,
		       const char *adb_dir,
		       const char *log_path)
{
	memset(proc, 0, sizeof(*proc));

	struct dstr cmdline = {0};
	quote_arg(&cmdline, exe_path);
	for (size_t i = 0; argv[i]; ++i) {
		dstr_cat_ch(&cmdline, ' ');
		quote_arg(&cmdline, argv[i]);
	}

	struct dstr env_block_utf8 = {0};
	build_env_block(&env_block_utf8, server_path, adb_dir);

	int wenv_len = MultiByteToWideChar(CP_UTF8, 0, env_block_utf8.array,
					   (int)env_block_utf8.len, NULL, 0);
	wchar_t *wenv = bmalloc((size_t)(wenv_len + 1) * sizeof(wchar_t));
	MultiByteToWideChar(CP_UTF8, 0, env_block_utf8.array,
			    (int)env_block_utf8.len, wenv, wenv_len);
	wenv[wenv_len] = 0;

	wchar_t *wexe = utf8_to_wide(exe_path);
	wchar_t *wcmd = utf8_to_wide(cmdline.array);

	HANDLE job = CreateJobObjectW(NULL, NULL);
	if (job) {
		JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = {0};
		info.BasicLimitInformation.LimitFlags =
			JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
		SetInformationJobObject(job, JobObjectExtendedLimitInformation,
					&info, sizeof(info));
	}

	HANDLE log_h = INVALID_HANDLE_VALUE;
	if (log_path && *log_path) {
		SECURITY_ATTRIBUTES sa = {0};
		sa.nLength = sizeof(sa);
		sa.bInheritHandle = TRUE;
		wchar_t *wlog = utf8_to_wide(log_path);
		log_h = CreateFileW(wlog, FILE_APPEND_DATA, FILE_SHARE_READ |
				    FILE_SHARE_WRITE, &sa, CREATE_ALWAYS,
				    FILE_ATTRIBUTE_NORMAL, NULL);
		bfree(wlog);
		if (log_h == INVALID_HANDLE_VALUE) {
			obs_log(LOG_WARNING,
				"scrcpy-process: cannot open log %s (err=%lu)",
				log_path, GetLastError());
		}
	}

	STARTUPINFOW si = {0};
	si.cb = sizeof(si);
	si.dwFlags = STARTF_USESTDHANDLES;
	si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
	if (log_h != INVALID_HANDLE_VALUE) {
		si.hStdOutput = log_h;
		si.hStdError = log_h;
	} else {
		si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
		si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
	}

	PROCESS_INFORMATION pi = {0};
	DWORD flags = CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW |
		      CREATE_SUSPENDED;

	BOOL ok = CreateProcessW(wexe, wcmd, NULL, NULL, TRUE, flags,
				 wenv, NULL, &si, &pi);

	bfree(wexe);
	bfree(wcmd);
	bfree(wenv);
	dstr_free(&cmdline);
	dstr_free(&env_block_utf8);
	if (log_h != INVALID_HANDLE_VALUE)
		CloseHandle(log_h);

	if (!ok) {
		obs_log(LOG_ERROR, "CreateProcessW failed: %lu", GetLastError());
		if (job)
			CloseHandle(job);
		return false;
	}

	if (job) {
		if (!AssignProcessToJobObject(job, pi.hProcess)) {
			obs_log(LOG_WARNING,
				"AssignProcessToJobObject failed: %lu",
				GetLastError());
		}
	}

	ResumeThread(pi.hThread);
	CloseHandle(pi.hThread);

	proc->process = pi.hProcess;
	proc->job = job;
	proc->pid = pi.dwProcessId;
	return true;
}

bool scrcpy_proc_alive(const scrcpy_proc_t *proc)
{
	if (!proc->process)
		return false;
	DWORD code = 0;
	if (!GetExitCodeProcess(proc->process, &code))
		return false;
	return code == STILL_ACTIVE;
}

void scrcpy_proc_kill(scrcpy_proc_t *proc)
{
	if (proc->job) {
		TerminateJobObject(proc->job, 1);
	} else if (proc->process) {
		TerminateProcess(proc->process, 1);
	}
	if (proc->process)
		WaitForSingleObject(proc->process, 2000);
}

void scrcpy_proc_close(scrcpy_proc_t *proc)
{
	if (proc->process) {
		CloseHandle(proc->process);
		proc->process = NULL;
	}
	if (proc->job) {
		CloseHandle(proc->job);
		proc->job = NULL;
	}
	proc->pid = 0;
}

#else /* POSIX */

#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

bool scrcpy_proc_spawn(scrcpy_proc_t *proc,
		       const char *exe_path,
		       const char *const *argv,
		       const char *server_path,
		       const char *adb_dir,
		       const char *log_path)
{
	memset(proc, 0, sizeof(*proc));
	(void)log_path;

	size_t argc = 0;
	while (argv[argc])
		argc++;

	char **spawn_argv = bmalloc(sizeof(char *) * (argc + 2));
	spawn_argv[0] = (char *)exe_path;
	for (size_t i = 0; i < argc; ++i)
		spawn_argv[i + 1] = (char *)argv[i];
	spawn_argv[argc + 1] = NULL;

	if (server_path)
		setenv("SCRCPY_SERVER_PATH", server_path, 1);
	if (adb_dir) {
		const char *cur = getenv("PATH");
		struct dstr p = {0};
		if (cur && *cur)
			dstr_printf(&p, "%s:%s", adb_dir, cur);
		else
			dstr_copy(&p, adb_dir);
		setenv("PATH", p.array, 1);
		dstr_free(&p);
	}

	pid_t pid = 0;
	int rc = posix_spawn(&pid, exe_path, NULL, NULL, spawn_argv, environ);
	bfree(spawn_argv);
	if (rc != 0) {
		obs_log(LOG_ERROR, "posix_spawn failed: %d", rc);
		return false;
	}
	proc->pid = pid;
	return true;
}

bool scrcpy_proc_alive(const scrcpy_proc_t *proc)
{
	if (proc->pid <= 0)
		return false;
	return kill(proc->pid, 0) == 0;
}

void scrcpy_proc_kill(scrcpy_proc_t *proc)
{
	if (proc->pid > 0) {
		kill(proc->pid, SIGTERM);
		for (int i = 0; i < 20; ++i) {
			int status = 0;
			pid_t r = waitpid(proc->pid, &status, WNOHANG);
			if (r == proc->pid || r < 0)
				return;
			usleep(100000);
		}
		kill(proc->pid, SIGKILL);
		waitpid(proc->pid, NULL, 0);
	}
}

void scrcpy_proc_close(scrcpy_proc_t *proc)
{
	proc->pid = 0;
}

#endif
