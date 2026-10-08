from agent.models import GetContentsMixin

class TaskGenerateText:
    def __init__(self, task):
        self.task = task

    def process(self):
        item = self.task.subject
        agent = self.task.thr
        payload = self.task.payload or {}
        preset = payload.get('preset', GetContentsMixin.PRESET_REFINE_PROMPT)
        message = payload.get('message', None)

        prompts = payload.get('prompts', [])
        target_field = payload.get('target_field', "prompt")
        schema = payload.get('schema', None)

        item.generate_text(
            agent=agent, 
            preset=preset, 
            message=message, 
            instructions=prompts, 
            schema=schema,
            user=self.task.owner,
            target_field=target_field
        )


import os
import random
import shutil
from pathlib import Path
from celery import shared_task
from django.conf import settings
from django.utils.text import slugify
from filer.models.imagemodels import Image as FilerImage
from agent.services.flow_runner import FlowRunner
from task.models import Task


class FlowTask:
    """
    Celery task delegate that drives Google Flow image and video generation
    via the FlowRunner CLI service and links output assets to Django Filer.
    """

    def __init__(self, task):
        self.task = task

    def _extract_prompt(self, payload: dict, subject) -> str:
        prompt = payload.get("prompt")
        if prompt:
            return prompt
        if hasattr(subject, "prompt") and subject.prompt:
            return str(subject.prompt)
        if hasattr(subject, "get_contents") and callable(subject.get_contents):
            contents = subject.get_contents()
            if isinstance(contents, dict) and "prompt" in contents:
                return str(contents["prompt"])
            if isinstance(contents, (list, tuple)) and contents:
                return str(contents[0])
            if isinstance(contents, str) and contents.strip():
                return contents
        return str(subject)

    def _persist_media(self, generated_path: Path, subject, action: str) -> FilerImage:
        ext = generated_path.suffix.lower() or (".mp4" if action == "video" else ".jpg")
        sub_name = getattr(subject, "name", str(subject.pk if hasattr(subject, "pk") else "item"))
        filename = f"flow_{action}_{slugify(sub_name)}_{random.randint(1000, 9999)}{ext}"

        dest_dir = Path(settings.MEDIA_ROOT) / "agent_flow"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        shutil.copy2(str(generated_path), str(dest_path))

        rel_path = f"agent_flow/{filename}"
        return FilerImage.objects.create(
            original_filename=filename,
            file=rel_path,
            name=filename,
        )

    def _dispatch_generation(self, runner: FlowRunner, payload: dict, prompt: str) -> tuple[Path, str]:
        action = payload.get("action", "image").lower()
        if action == "video":
            aspect = payload.get("aspect", "landscape")
            duration = payload.get("duration", "8s")
            quality = payload.get("quality", "720p")
            start_image = payload.get("start_image")
            output_file = runner.run_video(
                prompt=prompt,
                aspect=aspect,
                duration=duration,
                quality=quality,
                start_image=start_image,
            )
        else:
            aspect = payload.get("aspect", "1:1")
            count = int(payload.get("count", 1))
            model = payload.get("model", "narwhal")
            output_file = runner.run_image(
                prompt=prompt,
                aspect=aspect,
                count=count,
                model=model,
            )
        return output_file, action

    def process(self):
        """Processes the Flow generation task."""
        self.task.set_status(Task.TASK_STATUS_STARTED)
        payload = self.task.payload or {}
        subject = self.task.subject
        prompt = self._extract_prompt(payload, subject)

        runner = FlowRunner()
        output_file, action = self._dispatch_generation(runner, payload, prompt)
        filer_obj = self._persist_media(output_file, subject, action)

        target_field = payload.get("target_field") or ("video" if action == "video" else "image")
        if subject and hasattr(subject, target_field):
            setattr(subject, target_field, filer_obj)
            subject.save()

        self.task.log(f"Generated {action} successfully via Flow Agent: {filer_obj.file.url if hasattr(filer_obj, 'file') else filer_obj}")
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


@shared_task
def flow_task(task_id: int):
    """Shared Celery task entrypoint for FlowTask."""
    task = Task.objects.get(id=task_id)
    FlowTask(task).process()