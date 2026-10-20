from django.contrib import admin

class AdminActionsMixin:
    @admin.action(description="Clone selected items")
    def clone(self, request, queryset):
        for obj in queryset:
            if hasattr(obj, 'name') and obj.name:
                obj.name = f"{obj.name} (Clone)"
            obj.save()
            
        self.message_user(request, "Selected items have been cloned.")


class ModelActionsAdminMixin:
    """
    Admin mixin that dynamically creates changelist admin actions for all
    actions configured in the model (via ACTION_CHOICES and optional ACTIONS_NO_INPUT).
    """

    def _execute_model_action(self, request, obj, action_code):
        """Triggers the task for an object via task_from_action or generic task creation."""
        if hasattr(obj, "task_from_action"):
            obj.task_from_action(action_code, request.user)
        else:
            from task.models import Task
            Task.createTaskIfQueueEnabled(
                subject=obj,
                task_type=action_code,
                owner=request.user,
            )

    def _build_admin_action(self, action_code, description, action_name):
        """Constructs an action callback with proper signature and localized message."""
        def action_func(modeladmin, request, queryset):
            for obj in queryset:
                modeladmin._execute_model_action(request, obj, action_code)
            model_label = modeladmin.model._meta.verbose_name_plural
            modeladmin.message_user(
                request,
                f"Action '{description}' triggered for {queryset.count()} selected {model_label}."
            )

        action_func.__name__ = action_name
        action_func.short_description = description
        return action_func

    def get_actions(self, request):
        """Dynamically populates admin actions from the model's configured action choices."""
        actions = super().get_actions(request)
        model = getattr(self, "model", None)
        if not model:
            return actions

        from django.utils.text import slugify
        from django.utils.translation import gettext_lazy as _

        action_choices = dict(getattr(model, "ACTION_CHOICES", ()))
        no_input_actions = getattr(model, "ACTIONS_NO_INPUT",  None)
        target_codes = no_input_actions if no_input_actions is not None else list(action_choices.keys())

        for action_code in target_codes:
            description = action_choices.get(action_code, action_code)
            action_name = f"action_{slugify(str(action_code)).replace('-', '_')}"
            func = self._build_admin_action(action_code, description, action_name)
            actions[action_name] = (func, action_name, description)

        return actions


class AgentFlowMixin:
    """
    Mixin for Agent delegating image generation, image refinement, and video
    generation to the local FlowRunner service when Agent.type == 'flow'.
    """

    FLOW_IMAGE_ASPECT_MAP = {
        "1:1": "1:1",
        "16:9": "16:9",
        "9:16": "9:16",
        "4:3": "4:3",
        "3:4": "3:4",
        "21:9": "16:9",
        "3:2": "16:9",
        "2:3": "9:16",
    }
    FLOW_PORTRAIT_ASPECTS = {"9:16", "3:4", "2:3", "portrait"}
    FLOW_IMAGE_MODELS = {"narwhal", "harbor_seal", "gem_pix_2"}

    def _get_flow_runner(self):
        from agent.services.flow_runner import FlowRunner
        return FlowRunner()

    def _resolve_flow_image_aspect(self, prompt_obj) -> str:
        raw = prompt_obj.config("aspect_ratio", default="1:1") if hasattr(prompt_obj, "config") else "1:1"
        return self.FLOW_IMAGE_ASPECT_MAP.get(raw, "1:1")

    def _resolve_flow_video_aspect(self, prompt_obj) -> str:
        raw = prompt_obj.config("aspect_ratio", default="16:9") if hasattr(prompt_obj, "config") else "16:9"
        return "portrait" if raw in self.FLOW_PORTRAIT_ASPECTS else "landscape"

    def _resolve_flow_image_model(self) -> str:
        model_name = getattr(getattr(self, "agent_model", None), "name", "") or ""
        return model_name if model_name in self.FLOW_IMAGE_MODELS else "narwhal"

    def _extract_text_parts(self, instructions, contents) -> list[str]:
        parts = [str(i).strip() for i in (instructions or []) if isinstance(i, str) and str(i).strip()]
        if isinstance(contents, dict):
            prompt_val = contents.get("prompt")
            if isinstance(prompt_val, str) and prompt_val.strip():
                parts.append(prompt_val.strip())
        elif isinstance(contents, list):
            parts.extend(s.strip() for s in contents if isinstance(s, str) and s.strip())
        return parts

    def _collect_characters(self, prompt_obj) -> list:
        chars = []
        actor = getattr(prompt_obj, "actor", None)
        if actor:
            chars.append(actor)
        cast_mgr = getattr(prompt_obj, "cast", None)
        if cast_mgr and hasattr(cast_mgr, "all"):
            for char in cast_mgr.all():
                if char not in chars:
                    chars.append(char)
        return chars

    def _collect_props(self, prompt_obj) -> list:
        props_mgr = getattr(prompt_obj, "props", None)
        if props_mgr and hasattr(props_mgr, "all"):
            return list(props_mgr.all())
        return []

    def _resolve_style(self, prompt_obj):
        story = getattr(prompt_obj, "story", None)
        if not story:
            scene = getattr(prompt_obj, "scene", None)
            story = getattr(scene, "story", None) if scene else None
        return getattr(story, "style", None) if story else None

    def _collect_visual_context(self, prompt_obj) -> list[str]:
        parts: list[str] = []
        base = (getattr(prompt_obj, "prompt", "") or getattr(prompt_obj, "name", "") or "").strip()
        if base:
            parts.append(base)

        for char in self._collect_characters(prompt_obj):
            desc = (getattr(char, "prompt", "") or "").strip()
            parts.append(f"Character ({char.name}): {desc}" if desc else f"Character: {char.name}")

        for prop in self._collect_props(prompt_obj):
            desc = (getattr(prop, "prompt", "") or "").strip()
            parts.append(f"Prop ({prop.name}): {desc}" if desc else f"Prop: {prop.name}")

        bg = getattr(prompt_obj, "background", None)
        if bg:
            desc = (getattr(bg, "prompt", "") or "").strip()
            parts.append(f"Background ({bg.name}): {desc}" if desc else f"Background: {bg.name}")

        consistent = getattr(prompt_obj, "consistent_with", None)
        if consistent:
            desc = (getattr(consistent, "prompt", "") or "").strip()
            if desc:
                parts.append(f"Consistent with previous shot: {desc}")

        style = self._resolve_style(prompt_obj)
        style_prompt = (getattr(style, "prompt", "") or "").strip()
        if style_prompt:
            parts.append(f"Style: {style_prompt}")
        return parts

    def _build_flow_image_prompt(self, instructions, contents, prompt_obj) -> str:
        parts = self._collect_visual_context(prompt_obj)
        if not parts:
            parts = self._extract_text_parts(instructions, contents)
        return "\n".join(parts)

    def _build_flow_refine_prompt(self, instructions, contents, prompt_obj) -> str:
        parts = self._collect_visual_context(prompt_obj)
        refine_text = (getattr(prompt_obj, "prompt_refine", "") or "").strip()
        if refine_text:
            parts.append(refine_text)
        else:
            for item in self._extract_text_parts([], contents):
                if item not in parts:
                    parts.append(item)
        return "\n".join(parts)

    def _build_flow_video_prompt(self, instructions, contents, prompt_obj) -> str:
        if hasattr(prompt_obj, "_build_flow_video_prompt"):
            body = prompt_obj._build_flow_video_prompt()
            if body:
                return body.strip()
        parts = [str(i).strip() for i in (instructions or []) if isinstance(i, str) and str(i).strip()]
        if isinstance(contents, dict) and contents.get("prompt"):
            parts.append(str(contents["prompt"]).strip())
        else:
            parts.extend(self._extract_text_parts([], contents))
        return "\n".join(parts)

    def _extract_image_path(self, img_obj):
        if not img_obj:
            return None
        if hasattr(img_obj, "file") and getattr(img_obj.file, "path", None):
            return img_obj.file.path
        if getattr(img_obj, "path", None):
            return img_obj.path
        return getattr(img_obj, "filename", None)

    def _resolve_flow_start_image(self, contents, prompt_obj):
        for attr in ("image_first", "image"):
            path = self._extract_image_path(getattr(prompt_obj, attr, None))
            if path:
                return path
        if isinstance(contents, dict):
            for key in ("image_first", "image"):
                path = self._extract_image_path(contents.get(key))
                if path:
                    return path
        return None

    def _save_flow_media(self, source_path, prompt_obj, folder: str, prefix: str, default_ext: str):
        import random
        import shutil
        from pathlib import Path
        from django.conf import settings
        from django.utils.text import slugify
        from filer.models.imagemodels import Image as FilerImage

        ext = Path(source_path).suffix or default_ext
        stem = f"{prefix}{slugify(prompt_obj.__class__.__name__)}_{slugify(prompt_obj.name)}_{slugify(self.name)}_{random.randint(1000, 9999)}"
        filename = f"{stem}{ext}"
        rel_path = f"{folder}/{filename}"
        dest_path = Path(settings.MEDIA_ROOT) / folder / filename
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(dest_path))
        return FilerImage.objects.create(
            original_filename=filename,
            file=rel_path,
            name=filename,
        )

    def flow_generate_image(self, preset, prompt_obj, message=None, user=None, contents=None):
        instructions = self.get_instructions(user=user, preset=preset, obj=prompt_obj)
        if message:
            message.set_instructions(instructions)
        if contents is None:
            contents = prompt_obj.get_contents(generate_self=True, preset=preset)
        prompt = self._build_flow_image_prompt(instructions, contents, prompt_obj)
        aspect = self._resolve_flow_image_aspect(prompt_obj)
        model = self._resolve_flow_image_model()
        output_file = self._get_flow_runner().run_image(prompt=prompt, aspect=aspect, model=model)
        return self._save_flow_media(output_file, prompt_obj, folder="agent_images", prefix="", default_ext=".png")

    def flow_refine_image(self, preset, prompt_obj, message=None, user=None, contents=None):
        instructions = self.get_instructions(user=user, preset=preset, obj=prompt_obj)
        if message:
            message.set_instructions(instructions)
        if contents is None:
            contents = prompt_obj.get_contents(generate_self=True, preset=preset)
        prompt = self._build_flow_refine_prompt(instructions, contents, prompt_obj)
        aspect = self._resolve_flow_image_aspect(prompt_obj)
        model = self._resolve_flow_image_model()
        output_file = self._get_flow_runner().run_image(prompt=prompt, aspect=aspect, model=model)
        return self._save_flow_media(output_file, prompt_obj, folder="agent_images", prefix="refine_", default_ext=".png")

    def flow_generate_video(self, preset, prompt_obj, message=None, user=None, contents=None):
        instructions = self.get_instructions(user=user, preset=preset, obj=prompt_obj)
        if message:
            message.set_instructions(instructions)
        if contents is None:
            contents = prompt_obj.get_contents(generate_self=True, preset=preset)
        prompt = self._build_flow_video_prompt(instructions, contents, prompt_obj)
        aspect = self._resolve_flow_video_aspect(prompt_obj)
        start_image = self._resolve_flow_start_image(contents, prompt_obj)
        output_file = self._get_flow_runner().run_video(
            prompt=prompt,
            aspect=aspect,
            start_image=start_image,
        )
        return self._save_flow_media(output_file, prompt_obj, folder="agent_videos", prefix="video_", default_ext=".mp4")