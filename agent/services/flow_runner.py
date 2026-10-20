import asyncio
import os
from pathlib import Path
import sys
from typing import Any, Optional
from django.conf import settings


class FlowRunner:
    """
    Python runner for local flow-agent operations.
    Executes image, video, and character operations directly via FlowEngine.
    """

    def __init__(self, service_dir: Optional[Path] = None):
        base_dir = service_dir or (Path(settings.BASE_DIR) / "agent" / "services" / "flow-agent")
        nested_dir = base_dir / "flow-agent"
        self.service_dir: Path = nested_dir if (nested_dir / "main.py").exists() else base_dir
        self.engine = self._load_engine()

    def _load_engine(self):
        service_path = str(self.service_dir)
        if service_path not in sys.path:
            sys.path.insert(0, service_path)
        from flow_agent import FlowEngine
        return FlowEngine(root=self.service_dir)

    def _extract_file(self, result: dict[str, Any]) -> Path:
        for item in result.get("files") or []:
            raw_path = item.get("path") if isinstance(item, dict) else item
            if raw_path:
                candidate = Path(raw_path)
                if not candidate.is_absolute():
                    candidate = self.service_dir / candidate
                if candidate.exists():
                    return candidate

        output_dir = self.service_dir / "output"
        if output_dir.exists():
            files = sorted(output_dir.iterdir(), key=os.path.getmtime, reverse=True)
            if files:
                return files[0]

        raise FileNotFoundError(f"Flow Agent completed without generating a detectable output file: {result}")

    def list_characters(self, project_id: Optional[str] = None) -> list[dict]:
        """Lists registered characters for the Flow project."""
        return asyncio.run(self.engine.get_characters(project_id=project_id))

    def register_character(
        self, name: str, character_id: str, project_id: Optional[str] = None
    ) -> dict:
        """Registers a character handle and UUID for the Flow project."""
        return asyncio.run(
            self.engine.add_character(
                name=name,
                character_id=character_id,
                project_id=project_id or "",
            )
        )

    def run_image(
        self,
        prompt: str,
        aspect: str = "1:1",
        count: int = 1,
        model: str = "narwhal",
    ) -> Path:
        """Executes text-to-image generation."""
        result = asyncio.run(
            self.engine.generate_image(
                prompt=prompt,
                aspect=aspect,
                count=count,
                model=model,
            )
        )
        return self._extract_file(result)

    def run_video(
        self,
        prompt: str,
        aspect: str = "landscape",
        duration: str = "4s",
        quality: str = "480p",
        start_image: Optional[str] = None,
    ) -> Path:
        """Executes text-to-video, image-to-video, or @character-bound R2V generation."""
        result = asyncio.run(
            self.engine.generate_video(
                prompt=prompt,
                aspect=aspect,
                duration=duration,
                quality=quality,
                start_image=start_image,
            )
        )
        return self._extract_file(result)


