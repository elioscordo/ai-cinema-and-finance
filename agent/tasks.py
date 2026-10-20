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
    def __init__(self, task):
        self.task = task

    def _save_video(self, source_path: Path, name: str) -> FilerImage:
        filename = f"flow_{slugify(name)}_{random.randint(1000, 9999)}.mp4"
        dest_path = Path(settings.MEDIA_ROOT) / "agent_flow" / filename
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(dest_path))
        return FilerImage.objects.create(
            original_filename=filename,
            file=f"agent_flow/{filename}",
            name=filename,
        )

    def process(self):
        item = self.task.subject
        data = item.get_contents(preset=GetContentsMixin.PRESET_FLOW_VIDEO)
        start_image = data["image"].path if data.get("image") else None

        output_file = FlowRunner().run_video(prompt=data["prompt"], start_image=start_image)
        item.video = self._save_video(output_file, item.name)
        item.save()


@shared_task
def flow_task(task_id: int):
    task = Task.objects.get(id=task_id)
    FlowTask(task).process()