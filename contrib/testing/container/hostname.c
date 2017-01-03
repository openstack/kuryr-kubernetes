#define _GNU_SOURCE
#include <arpa/inet.h>
#include <err.h>
#include <errno.h>
#include <linux/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_LEN 1024
#define BACKLOG 10
#define LISTENING_PORT 8000

volatile sig_atomic_t running = 1;
volatile sig_atomic_t sig_number;

static void handler(int signo) {
	sig_number = signo;
	running = 0;
}


int main() {
	struct sigaction sa = {
		.sa_handler = handler,
		.sa_flags = 0};
	sigemptyset(&sa.sa_mask);

	if (sigaction(SIGINT, &sa, NULL) == -1) {
		err(1, "Failed to set SIGINT handler");
	}
	if (sigaction(SIGTERM, &sa, NULL) == -1) {
		err(1, "Failed to set SIGTERM handler");
	}

	int enable = 1;
	int result = 1;
	char hostname[MAX_LEN];
	int res = gethostname(hostname, MAX_LEN);
	if (res < 0) {
		err(1, "Failed to retrieve hostname");
	}

	char *response;
	ssize_t responselen;
	responselen = asprintf(&response, "HTTP/1.1 200 OK\r\n"
			"Content-Type: text/html; charset=UTF-8\r\n\r\n"
			"%s\r\n", hostname);
	if (responselen == -1) {
		err(1, "Failed to form response");
	}

	int sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock < 0) {
		perror("Failed to open socket");
		goto nosocket;
	}

	res = setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &enable,
			sizeof(int));
	if (res < 0) {
		perror("Failed to set socket options");
		goto cleanup;
	}

	struct sockaddr_in srv = {
		.sin_family = AF_INET,
		.sin_port = htons(LISTENING_PORT),
		.sin_addr = { .s_addr = INADDR_ANY}};
	socklen_t addrlen= sizeof(srv);

	res = bind(sock, (struct sockaddr *) &srv, (socklen_t) sizeof(srv));
	if (res < 0) {
		res = close(sock);
		if (res == -1) {
			perror("Failed close socket");
			goto cleanup;
		}
		perror("Failed to bind socket");
		goto cleanup;
	}

	res = listen(sock, BACKLOG);
	if (res < 0) {
		perror("Failed to set socket to listen");
		goto cleanup;
	}

	while (running) {
		struct sockaddr_in cli;
		int client_fd = accept(sock, (struct sockaddr *) &cli,
				&addrlen);
		if (client_fd == -1) {
			if (running) {
				perror("failed to accept connection");
				continue;
			} else {
				char *signame = strsignal(sig_number);
				printf("Received %s. Quitting\n", signame);
				break;
			}
		}
		fprintf(stderr, "Accepted client connection\n");

		/* Assume we write it all at once */
		write(client_fd, response, responselen);
		res = shutdown(client_fd, SHUT_RDWR);
		if (res == -1) {
			perror("Failed to shutdown client connection");
			goto cleanup;
		}
		res = close(client_fd);
		if (res == -1) {
			perror("Failed to close client connection");
			goto cleanup;
		}
	}

	result = 0;
cleanup:
	close(sock);
nosocket:
	free(response);
	return result;
}
