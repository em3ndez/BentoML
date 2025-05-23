from __future__ import annotations

import json
import socket
import typing as t

import click


@click.command()
@click.argument("bento_identifier", type=click.STRING, required=False, default=".")
@click.option(
    "--fd",
    type=click.INT,
    required=True,
    help="File descriptor of the socket to listen on",
)
@click.option(
    "--runner-map",
    type=click.STRING,
    envvar="BENTOML_RUNNER_MAP",
    help="JSON string of runners map, default sets to envars `BENTOML_RUNNER_MAP`",
)
@click.option(
    "--backlog", type=click.INT, default=2048, help="Backlog size for the socket"
)
@click.option(
    "--working-dir",
    type=click.Path(exists=True),
    help="Working directory for the API server",
)
@click.option(
    "--worker-id",
    required=False,
    type=click.INT,
    default=None,
    help="If set, start the server as a bare worker with the given worker ID. Otherwise start a standalone server with a supervisor process.",
)
@click.option(
    "--ssl-certfile",
    type=str,
    default=None,
    help="SSL certificate file",
)
@click.option(
    "--ssl-keyfile",
    type=str,
    default=None,
    help="SSL key file",
)
@click.option(
    "--ssl-keyfile-password",
    type=str,
    default=None,
    help="SSL keyfile password",
)
@click.option(
    "--ssl-version",
    type=int,
    default=None,
    help="SSL version to use (see stdlib 'ssl' module)",
)
@click.option(
    "--ssl-cert-reqs",
    type=int,
    default=None,
    help="Whether client certificate is required (see stdlib 'ssl' module)",
)
@click.option(
    "--ssl-ca-certs",
    type=str,
    default=None,
    help="CA certificates file",
)
@click.option(
    "--ssl-ciphers",
    type=str,
    default=None,
    help="Ciphers to use (see stdlib 'ssl' module)",
)
@click.option(
    "--timeout-keep-alive",
    type=click.INT,
    default=5,
    help="Close Keep-Alive connections if no new data is received within this timeout.",
)
@click.option(
    "--timeout-graceful-shutdown",
    type=click.INT,
    default=None,
    help="Maximum number of seconds to wait for graceful shutdown. After this timeout, the server will start terminating requests.",
)
@click.option(
    "--development-mode",
    type=click.BOOL,
    help="Run the API server in development mode",
    is_flag=True,
    default=False,
    show_default=True,
)
@click.option(
    "--timeout",
    type=click.INT,
    help="Specify the timeout for API server",
)
def main(
    bento_identifier: str,
    fd: int,
    runner_map: str | None,
    backlog: int,
    working_dir: str | None,
    worker_id: int,
    ssl_certfile: str | None,
    ssl_keyfile: str | None,
    ssl_keyfile_password: str | None,
    ssl_version: int | None,
    ssl_cert_reqs: int | None,
    ssl_ca_certs: str | None,
    ssl_ciphers: str | None,
    timeout_keep_alive: int | None,
    timeout_graceful_shutdown: int | None,
    development_mode: bool,
    timeout: int | None,
):
    """
    Start a HTTP api server worker.
    """
    import psutil

    import bentoml
    from bentoml._internal.configuration.containers import BentoMLContainer
    from bentoml._internal.context import server_context
    from bentoml._internal.log import configure_server_logging

    server_context.service_type = "api_server"
    server_context.worker_index = worker_id
    configure_server_logging()

    if worker_id is None:
        # worker ID is not set; this server is running in standalone mode
        # and should not be concerned with the status of its runners
        BentoMLContainer.config.runner_probe.enabled.set(False)
    else:
        BentoMLContainer.worker_index.set(worker_id)

    BentoMLContainer.development_mode.set(development_mode)
    if runner_map is not None:
        BentoMLContainer.remote_runner_mapping.set(json.loads(runner_map))
    if timeout is not None:
        BentoMLContainer.api_server_config.traffic.timeout.set(timeout)
    svc = bentoml.load(bento_identifier, working_dir=working_dir)

    # setup context
    server_context.service_name = svc.name
    if svc.tag is None:
        server_context.bento_name = svc.name
        server_context.bento_version = "not available"
    else:
        server_context.bento_name = svc.tag.name
        server_context.bento_version = svc.tag.version or "not available"

    uvicorn_options: dict[str, t.Any] = {
        "backlog": backlog,
        "log_config": None,
        "workers": 1,
    }

    if ssl_certfile:
        import ssl

        uvicorn_options["ssl_certfile"] = ssl_certfile
        if ssl_keyfile:
            uvicorn_options["ssl_keyfile"] = ssl_keyfile
        if ssl_keyfile_password:
            uvicorn_options["ssl_keyfile_password"] = ssl_keyfile_password
        if ssl_ca_certs:
            uvicorn_options["ssl_ca_certs"] = ssl_ca_certs

        if not ssl_version:
            ssl_version = ssl.PROTOCOL_TLS_SERVER
            uvicorn_options["ssl_version"] = ssl_version
        if not ssl_cert_reqs:
            ssl_cert_reqs = ssl.CERT_NONE
            uvicorn_options["ssl_cert_reqs"] = ssl_cert_reqs
        if not ssl_ciphers:
            ssl_ciphers = "TLSv1"
            uvicorn_options["ssl_ciphers"] = ssl_ciphers

    if timeout_keep_alive:
        uvicorn_options["timeout_keep_alive"] = timeout_keep_alive
    if timeout_graceful_shutdown:
        uvicorn_options["timeout_graceful_shutdown"] = timeout_graceful_shutdown

    if psutil.WINDOWS:
        uvicorn_options["loop"] = "asyncio"
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore

    import uvicorn

    # skip the uvicorn internal supervisor
    sock = socket.socket(fileno=fd)
    config = uvicorn.Config(svc.asgi_app, **uvicorn_options)
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
