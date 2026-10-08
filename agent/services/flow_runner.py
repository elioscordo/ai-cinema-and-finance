import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional
from django.conf import settings


class FlowRunner:
    """
    Command runner for local flow-agent CLI operations.
    Executes image and video generation through the flow-agent repository.
    """

    def __init__(self, service_dir: Optional[Path] = None):
        self.service_dir: Path = (
            service_dir or (Path(settings.BASE_DIR) / "agent" / "services" / "flow-agent")
        )

    def _resolve_python(self) -> str:
        venv_python = self.service_dir / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    def _find_generated_file(self, stdout: str) -> Path:
        match = re.search(r"saved\s+([^\s]+)", stdout)
        if match:
            candidate = self.service_dir / match.group(1).strip()
            if candidate.exists():
                return candidate

        output_dir = self.service_dir / "output"
        if output_dir.exists():
            files = sorted(output_dir.iterdir(), key=os.path.getmtime, reverse=True)
            if files:
                return files[0]

        raise FileNotFoundError("Flow Agent completed without generating a detectable output file.")

    def _execute(self, cmd_args: list[str]) -> Path:
        if not self.service_dir.exists():
            raise FileNotFoundError(
                f"flow-agent directory not found at {self.service_dir}. "
                "Please clone https://github.com/kodelyx/flow-agent into agent/services/flow-agent."
            )

        result = subprocess.run(
            cmd_args,
            cwd=str(self.service_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            raise RuntimeError(f"Flow Agent execution failed (code {result.returncode}): {error_msg}")

        return self._find_generated_file(result.stdout)

    def run_image(
        self,
        prompt: str,
        aspect: str = "1:1",
        count: int = 1,
        model: str = "narwhal",
    ) -> Path:
        """Executes text-to-image generation."""
        py = self._resolve_python()
        cmd = [
            py, "main.py", "image", prompt,
            "--aspect", aspect,
            "--count", str(count),
            "--model", model,
        ]
        return self._execute(cmd)

    def run_video(
        self,
        prompt: str,
        aspect: str = "landscape",
        duration: str = "8s",
        quality: str = "720p",
        start_image: Optional[str] = None,
    ) -> Path:
        """Executes text-to-video or image-to-video generation."""
        py = self._resolve_python()
        cmd = [
            py, "main.py", "video", prompt,
            "--aspect", aspect,
            "--duration", duration,
            "--quality", quality,
        ]
        if start_image:
            cmd.extend(["--start-image", str(start_image)])
        return self._execute(cmd)
