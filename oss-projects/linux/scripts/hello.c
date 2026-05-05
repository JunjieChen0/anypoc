/* hello.c — sanity PoC for the linux project image.
 *
 * Runs as PID 1 inside the busybox initramfs. Exercises a couple of plain
 * syscalls (uname, write) so we can confirm the kernel actually serviced a
 * userspace request before printing "hello world" on the serial console. */

#include <stdio.h>
#include <sys/utsname.h>
#include <unistd.h>

int main(void) {
    struct utsname u;
    if (uname(&u) == 0) {
        printf("[hello] kernel: %s %s %s\n", u.sysname, u.release, u.machine);
    } else {
        perror("[hello] uname");
    }

    const char msg[] = "hello world from PID 1\n";
    if (write(STDOUT_FILENO, msg, sizeof(msg) - 1) < 0) {
        perror("[hello] write");
    }

    fflush(stdout);
    return 0;
}
