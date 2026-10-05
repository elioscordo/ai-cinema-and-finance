import abc
import datetime
import http.client
import json
import socket
import time
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from argo.backtest.runner import StrategyBacktestRunner
from argo.backtest.optimizer import ParameterOptimizer, ParameterGrid


class TaskRunBacktest:
    """
    Celery task delegate running historical simulation for a Backtest model instance.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        backtest = self.task.subject
        if not backtest.is_covered():
            backtest.load_data()
        instance = backtest.strategy_instance
        runner = StrategyBacktestRunner(starting_balance=float(backtest.initial_capital))

        start_dt = backtest.start_date or (timezone.now() - datetime.timedelta(days=90))
        end_dt = backtest.end_date or timezone.now()

        result = runner.run(
            instance=instance,
            start=start_dt,
            end=end_dt,
            params_override=backtest.params_override or None,
            backtest=backtest,
        )

        # Update Backtest record with calculated metrics
        backtest.total_pnl = result.total_pnl
        backtest.return_pct = result.return_pct
        backtest.sharpe_ratio = result.sharpe_ratio
        backtest.sortino_ratio = result.sortino_ratio
        backtest.calmar_ratio = result.calmar_ratio
        backtest.max_drawdown_pct = result.max_drawdown_pct
        backtest.profit_factor = result.profit_factor
        backtest.win_rate = result.win_rate
        backtest.total_trades = result.total_trades
        backtest.save()

        summary_msg = (
            f"Backtest Completed for {instance}:\n"
            f"- Period: {result.start_time} -> {result.end_time}\n"
            f"- Total PnL: ${result.total_pnl:,.2f} ({result.return_pct:.2%})\n"
            f"- Sharpe: {result.sharpe_ratio:.2f} | Sortino: {result.sortino_ratio:.2f} | Calmar: {result.calmar_ratio:.2f}\n"
            f"- Max DD: {result.max_drawdown_pct:.2%} | Win Rate: {result.win_rate:.1%} ({result.total_trades} trades)"
        )
        if result.total_trades == 0:
            summary_msg += "\n[DIAGNOSTIC] 0 trades executed. Review strategy entry rules, parameters, or market data."
        self.task.log(summary_msg)


class TaskRunOptimization:
    """
    Celery task delegate running parameter grid sweeps and ranking for a Backtest model instance.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        backtest = self.task.subject
        if not backtest.is_covered():
            backtest.load_data()
        instance = backtest.strategy_instance
        runner = StrategyBacktestRunner(starting_balance=float(backtest.initial_capital))
        optimizer = ParameterOptimizer(runner=runner, objective=backtest.optimization_objective or "sharpe")

        start_dt = backtest.start_date or (timezone.now() - datetime.timedelta(days=90))
        end_dt = backtest.end_date or timezone.now()

        grid_dict = backtest.param_grid or optimizer.get_default_grid(instance.strategy_model)
        grid = ParameterGrid(grid_dict)

        report = optimizer.optimize(
            instance=instance,
            param_grid=grid,
            start=start_dt,
            end=end_dt,
            apply_best=False,  # Keep params in Backtest model until explicit promotion
        )

        backtest.best_params = report.best_params
        backtest.leaderboard = report.leaderboard
        if report.best_result:
            res = report.best_result
            backtest.total_pnl = res.total_pnl
            backtest.return_pct = res.return_pct
            backtest.sharpe_ratio = res.sharpe_ratio
            backtest.sortino_ratio = res.sortino_ratio
            backtest.calmar_ratio = res.calmar_ratio
            backtest.max_drawdown_pct = res.max_drawdown_pct
            backtest.profit_factor = res.profit_factor
            backtest.win_rate = res.win_rate
            backtest.total_trades = res.total_trades

        backtest.save()

        summary_msg = (
            f"Optimization Completed ({report.total_iterations} iterations, objective: {report.objective}):\n"
            f"- Best Parameters: {report.best_params}\n"
            f"- Best Sharpe: {getattr(report.best_result, 'sharpe_ratio', 0.0):.2f}\n"
            f"- Best PnL: ${getattr(report.best_result, 'total_pnl', 0.0):,.2f}"
        )
        self.task.log(summary_msg)


class TaskLoadData:
    """
    Celery task delegate checking and synchronizing historical market data for Backtest or HistoricalData model instances.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        subject = self.task.subject
        if hasattr(subject, 'sync_data'):
            data_record = subject.sync_data()
        elif hasattr(subject, 'load_data'):
            data_record = subject.load_data()
        else:
            raise ValueError(f"Subject {subject} does not implement sync_data or load_data.")

        first_rec = data_record[0] if isinstance(data_record, (list, tuple)) and data_record else data_record

        if hasattr(first_rec, 'instrument'):
            summary_msg = (
                f"Historical Data Ready for {subject}:\n"
                f"- Instrument: {first_rec.instrument.symbol}\n"
                f"- Bar Type: {first_rec.bar_type}\n"
                f"- Range: {first_rec.start_date.strftime('%Y-%m-%d %H:%M') if first_rec.start_date else '?'} -> {first_rec.end_date.strftime('%Y-%m-%d %H:%M') if first_rec.end_date else '?'}\n"
                f"- Total Bars: {first_rec.bar_count:,}\n"
                f"- Storage: Parquet\n"
                f"- Catalog: {first_rec.catalog_path}"
            )
        else:
            summary_msg = f"Historical Data Sync Completed for {subject}."
        self.task.log(summary_msg)
        return data_record


TaskSyncData = TaskLoadData


class TaskSearchAndCreateInstruments:
    """
    Task delegate executing an IB search for each symbol in an InstrumentGroup
    and creating the corresponding Instrument and IBContract models.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        group = self.task.subject
        created_count, total_count = group.search_and_create_instruments()
        summary_msg = (
            f"IB Search & Instrument Creation completed for '{group.name}':\n"
            f"- Created: {created_count} new instrument(s)\n"
            f"- Total Processed: {total_count} symbol(s)"
        )
        self.task.log(summary_msg)


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTP connection over a Unix Domain Socket for Docker daemon communication."""

    def __init__(self, socket_path: str, timeout: int = 10):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class DockerClientInterface(abc.ABC):
    """Abstract Strategy interface for Docker daemon operations."""

    @abc.abstractmethod
    def get_container_info(self, name: str) -> dict:
        """Inspect container and return metadata dict, or empty dict if not found."""
        pass

    @abc.abstractmethod
    def restart_container(self, name: str, timeout: int = 10) -> bool:
        """Trigger container restart."""
        pass


class DockerSocketClient(DockerClientInterface):
    """Docker client communicating directly via /var/run/docker.sock without third-party deps."""

    def __init__(self, socket_path: str = None, timeout: int = 10):
        self.socket_path = socket_path or getattr(settings, "DOCKER_SOCKET_PATH", "/var/run/docker.sock")
        self.timeout = timeout

    def _request(self, method: str, path: str) -> tuple[int, bytes]:
        conn = UnixSocketHTTPConnection(self.socket_path, timeout=self.timeout)
        try:
            conn.request(method, path, headers={"Host": "localhost"})
            res = conn.getresponse()
            return res.status, res.read()
        finally:
            conn.close()

    def get_container_info(self, name: str) -> dict:
        try:
            status, body = self._request("GET", f"/containers/{name}/json")
            return json.loads(body.decode("utf-8")) if status == 200 else {}
        except Exception:
            return {}

    def restart_container(self, name: str, timeout: int = 10) -> bool:
        try:
            status, _ = self._request("POST", f"/containers/{name}/restart?t={timeout}")
            return status in (200, 204)
        except Exception:
            return False


class DockerSDKClient(DockerClientInterface):
    """Docker client leveraging official 'docker' python library when installed."""

    def __init__(self):
        import docker  # type: ignore
        self.client = docker.from_env()

    def get_container_info(self, name: str) -> dict:
        try:
            container = self.client.containers.get(name)
            return container.attrs
        except Exception:
            return {}

    def restart_container(self, name: str, timeout: int = 10) -> bool:
        try:
            container = self.client.containers.get(name)
            container.restart(timeout=timeout)
            return True
        except Exception:
            return False


class DockerClientFactory:
    """Factory selecting the best available Docker strategy."""

    @classmethod
    def create(cls, socket_path: str = None) -> DockerClientInterface:
        try:
            return DockerSDKClient()
        except Exception:
            return DockerSocketClient(socket_path=socket_path)


class IBGatewayService:
    """
    Service coordinating Interactive Brokers Gateway container verification and restart.
    """

    def __init__(self, client: DockerClientInterface = None):
        self.client = client or DockerClientFactory.create()

    @staticmethod
    def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
        """Test TCP socket reachability on target host and port."""
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False

    def inspect_container(self, name: str) -> dict:
        """Retrieve container run state and health."""
        info = self.client.get_container_info(name)
        if not info:
            return {"exists": False, "status": "unknown", "running": False, "health": "unknown"}
        state = info.get("State", {})
        health = state.get("Health", {}).get("Status", "none")
        return {
            "exists": True,
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "health": health,
        }

    def restart_container(self, name: str, timeout: int = 10) -> bool:
        """Trigger container restart via Docker client."""
        return self.client.restart_container(name, timeout=timeout)

    def wait_for_port(self, host: str, port: int, max_wait: int = 30, interval: float = 2.0) -> bool:
        """Poll port connectivity until open or timeout reached."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if self.check_port(host, port, timeout=interval):
                return True
            time.sleep(interval)
        return False

    def verify_and_restart(
        self,
        container_name: str = None,
        host: str = None,
        port: int = None,
        force: bool = False,
        wait_ready: bool = True,
    ) -> dict:
        """
        Verify IB Gateway container & API port; restart if unhealthy, down, or forced.
        """
        c_name = container_name or getattr(settings, "IB_GATEWAY_CONTAINER", "ib-gateway")
        ib_host = host or getattr(settings, "IB_HOST", "127.0.0.1")
        ib_port = port or getattr(settings, "IB_PORT", 4002)

        initial_state = self.inspect_container(c_name)
        port_open = self.check_port(ib_host, ib_port)
        needs_restart = force or not initial_state["running"] or not port_open

        if not needs_restart:
            return {
                "restarted": False,
                "container": initial_state,
                "port_open": True,
                "message": f"IB Gateway '{c_name}' is running and port {ib_port} is responsive.",
            }

        restarted = self.restart_container(c_name)
        ready = self.wait_for_port(ib_host, ib_port) if (restarted and wait_ready) else False
        final_state = self.inspect_container(c_name)

        return {
            "restarted": restarted,
            "container": final_state,
            "port_open": ready,
            "message": (
                f"IB Gateway '{c_name}' restart {'succeeded' if ready else 'initiated'}. "
                f"Port {ib_port} open: {ready}."
            ),
        }


class TaskVerifyAndRestartIBGateway:
    """
    Task delegate verifying the status of the IB Gateway Docker container and restarting it if needed.
    """

    def __init__(self, task):
        self.task = task
        self.service = IBGatewayService()

    def process(self):
        payload = getattr(self.task, "payload", {}) or {}
        container_name = payload.get("container_name") or getattr(settings, "IB_GATEWAY_CONTAINER", "ib-gateway")
        host = payload.get("host") or getattr(settings, "IB_HOST", "127.0.0.1")
        port = payload.get("port") or getattr(settings, "IB_PORT", 4002)
        force = bool(payload.get("force", False))

        self.task.log(f"Verifying IB Gateway status (container: {container_name}, host: {host}:{port}, force={force})...")
        result = self.service.verify_and_restart(container_name=container_name, host=host, port=port, force=force)

        summary = (
            f"IB Gateway Verification & Restart Summary:\n"
            f"- Container: {container_name} (Status: {result['container']['status']}, Health: {result['container']['health']})\n"
            f"- Action: {'Restarted' if result['restarted'] else 'Verified (No restart needed)'}\n"
            f"- Port {port}: {'Listening & Accessible' if result['port_open'] else 'Unreachable'}\n"
            f"- Message: {result['message']}"
        )
        self.task.log(summary)

        if not result["container"].get("exists"):
            raise RuntimeError(f"IB Gateway container '{container_name}' not found on Docker host.")
        if result["restarted"] and not result["port_open"]:
            raise RuntimeError(f"IB Gateway '{container_name}' was restarted but port {port} is not listening.")
        return result


TaskRestartIBGateway = TaskVerifyAndRestartIBGateway
TaskIBGatewayHealth = TaskVerifyAndRestartIBGateway


def restart_ib_gateway(container_name: str = None, host: str = None, port: int = None, force: bool = True) -> dict:
    """
    Direct function to restart IB Gateway, callable by TaskExecuteFunc or directly.
    """
    service = IBGatewayService()
    return service.verify_and_restart(container_name=container_name, host=host, port=port, force=force)


@shared_task
def verify_and_restart_ib_gateway(container_name=None, host=None, port=None, force=False):
    """
    Celery shared task to verify and restart IB Gateway container.
    """
    service = IBGatewayService()
    return service.verify_and_restart(
        container_name=container_name,
        host=host,
        port=port,
        force=force,
    )

