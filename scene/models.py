from django.db import models
from django.conf import settings
from agent.models import Agent, Prompt
from filer.fields.image import FilerImageField, FilerFileField
from agent.models import GetContentsMixin, GoogleVoice
from scene.mixins import (
    EmailSenderMixin, UserCreatorMixin, ModelDisplayMixin, RenderTypeMixin, YAMLAssetsMixin
)
from .schemas import BackgroundSchema, CharacterSchema, PropSchema, VoiceSchema, GoogleVoiceSchema

from task.mixins import  AfterSaveActionMixin
from task.models import TaskHolder, Task
import yaml
from .schemas import ActionSchema
from django.utils.translation import gettext_lazy as _, get_language
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from simple_history.models import HistoricalRecords

from PIL import Image

def dashboard_callback(request, context):
    stories = []
    if request.user.is_authenticated:
        profile = getattr(request.user, 'story_profile', None)
        if profile:
            current_story = profile.get_current_story()
            if current_story:
                stories = Story.objects.filter(pk=current_story.pk)
            else:
                stories = Story.objects.filter(authors__user=request.user).distinct()
        else:
            stories = Story.objects.filter(authors__user=request.user).distinct()
    context.update({'stories': stories})
    return context

class Theme(models.Model):
    name = models.CharField(_("name"), max_length=100, default='New Game')
    prompt = models.TextField(_("prompt"), null=True, blank=True)
    
    def __str__(self):
        return "{}".format(self.name)


class Style(models.Model, GetContentsMixin, ModelDisplayMixin):
    prompt = models.TextField(_("prompt"), null=True, blank=True)
    name = models.CharField(_("name"), max_length=100, default="")
    global_default = models.BooleanField(_("global default"), default=False)
    
    def __str__(self):
        return "{}".format(self.name)
    
    def context_text(self, generate_self=True, preset=None):
        if preset == self.PRESET_REFINE:
            return self.prompt_refine
        return self.prompt

class Preset(models.Model):
    name = models.CharField(_("name"), null=True, blank=True)
    preset = models.JSONField(_("preset"), null=True, blank=True)
    

class Author(models.Model, UserCreatorMixin):
    story = models.ForeignKey('scene.Story', verbose_name=_("story"), related_name='authors', on_delete=models.CASCADE, null=True, blank=True)
    order = models.IntegerField(_("order"), default=0)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("user"), related_name='authors', on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField(_("email"), null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.email and not self.user:
            raise ValueError("Either email or user must be provided.")
        if self.email and self.user is None:
            user = self.create_user(self.story, self.email)
            self.user = user
        super().save(*args, **kwargs)
           

    def __str__(self):
        return "{}".format(self.user.username if self.user else self.email)

    def username(self):
        return self.user.username if self.user else self.email
    
    def scene_count(self):
        return self.scenes.count()

class Story(AfterSaveActionMixin, RenderTypeMixin, YAMLAssetsMixin, models.Model, GetContentsMixin, TaskHolder, ModelDisplayMixin):
    name = models.CharField(_("name"), max_length=200)
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    style = models.ForeignKey(Style, verbose_name=_("style"), related_name='stories', null=True, blank=True, on_delete=models.CASCADE)
    theme = models.ForeignKey('Theme', verbose_name=_("theme"), on_delete=models.CASCADE, null=True, blank=True)
    group = models.ForeignKey('scene.StoryGroup', verbose_name=_("group"), help_text=_("Auto create authors from this group, it happens only when the script is saved for the first time"),  on_delete=models.CASCADE, null=True, blank=True, related_name='stories')

    prompt = models.TextField(_("prompt"), null=True, blank=True, default="#Plot\n")
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    prompt_elements = models.TextField(_("Prompt Elements"), null=True, blank=True, default="#Locations\n#Characters\n#Props\n#Voices\n")
    prompt_translations = models.TextField(_("Prompt Translations"), null=True, blank=True)

    @property
    def translations(self):
        return self.prompt_translations

    @translations.setter
    def translations(self, value):
        self.prompt_translations = value

    action = models.SlugField(_("action"), choices=settings.TASK_TYPE_CHOICES, null=True, blank=True)
    mentor = models.ForeignKey("agent.Agent", verbose_name=_("mentor"), related_name='mentors_stories', on_delete=models.CASCADE, null=True, blank=True)
    history = HistoricalRecords()
    

    TASK_TEXT_GENERATE = settings.TASK_TYPE_GENERATE_TEXT
    
    PRESET_CREATE_SCENES = "create_scenes"
    PRESET_EDIT_SCENES = "edit_scenes"
    PRESET_CREATE_ELEMENTS = "create_elements"
    PRESET_EDIT_ELEMENTS = "edit_elements"
    PRESET_SYNC_ELEMENTS = "sync_elements"
    PRESET_EDIT_SYNC_ELEMENTS = "edit_sync_elements"
    PRESET_SYNC_SCENES = "sync_scenes"
    PRESET_TRANSLATE_SHOTS = "translate_shots"
    
    ACTION_CREATE_SCENES = f"{TASK_TEXT_GENERATE}-preset-{PRESET_CREATE_SCENES}"
    ACTION_EDIT_SCENES = f"{TASK_TEXT_GENERATE}-preset-{PRESET_EDIT_SCENES}"

    ACTION_CREATE_ELEMENTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_CREATE_ELEMENTS}-target-prompt_elements-schema-{settings.SCHEMA_OUTPUT_WITH_MESSAGE}"
    ACTION_EDIT_ELEMENTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_EDIT_ELEMENTS}-target-prompt_elements-schema-{settings.SCHEMA_OUTPUT_WITH_MESSAGE}"

    ACTION_SYNC_SCENES = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_SCENES}-schema-{settings.SCHEMA_STORY_SCENES}"
    ACTION_SYNC_ELEMENTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_ELEMENTS}-schema-{settings.SCHEMA_ASSETS}"
    ACTION_EDIT_SYNC_ELEMENTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_EDIT_SYNC_ELEMENTS}-schema-{settings.SCHEMA_ASSETS}"
    ACTION_TRANSLATE_SHOTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_TRANSLATE_SHOTS}-target-prompt_translations-schema-{settings.SCHEMA_OUTPUT_WITH_MESSAGE}"

    ACTION_CHOICES = (
        (ACTION_CREATE_SCENES, _("Create story scenes")),
        (ACTION_EDIT_SCENES, _("Edit story scenes")),
        (ACTION_CREATE_ELEMENTS, _("Create story elements")),
        (ACTION_EDIT_ELEMENTS, _("Edit story elements")),
        (ACTION_SYNC_SCENES, _("Sync story scenes")),
        (ACTION_SYNC_ELEMENTS, _("Sync story elements")),
        (ACTION_EDIT_SYNC_ELEMENTS, _("Edit Sync elements")),
        (ACTION_TRANSLATE_SHOTS, _("Translate shots")),
    ) + settings.COMMON_TEXT_ACTION_CHOICES


    AGENT_PRESETS = (
        (PRESET_CREATE_SCENES, _("Create story scenes")),
        (PRESET_EDIT_SCENES, _("Edit story scenes")),
        (PRESET_CREATE_ELEMENTS, _("Create  story elements")),
        (PRESET_EDIT_ELEMENTS, _("Edit story elements")),
        (PRESET_SYNC_ELEMENTS, _("Sync story elements")),
        (PRESET_SYNC_SCENES, _("Sync story scenes")),  
        (PRESET_EDIT_SYNC_ELEMENTS, _("Edit Sync elements")),
        (PRESET_TRANSLATE_SHOTS, _("Translate shots")),
    )

    RENDER_TYPE_FILM = 'film'
    RENDER_TYPE_GRAPHIC_NOVEL = 'comic'
    RENDER_TYPE_ANIMATIC = 'animatic'

    RENDER_TYPE_CHOICES = [
        (RENDER_TYPE_FILM, _('Film')),
        (RENDER_TYPE_GRAPHIC_NOVEL, _('Graphic Novel')),
        (RENDER_TYPE_ANIMATIC, _('Animatic')),
    ]

    render_type = models.CharField(
        _("render type"),
        max_length=50,
        choices=RENDER_TYPE_CHOICES,
        default=getattr(settings, 'DEFAULT_RENDER_TYPE', RENDER_TYPE_ANIMATIC),
        help_text=_("The default render format for this story.")
    )
    config = models.ForeignKey(Preset, verbose_name=_("config"), related_name='stories', on_delete=models.SET_NULL, null=True, blank=True)
    
    def __str__(self):
        return "{}".format(self.name)

    class Meta:
        verbose_name = _('Story')
        verbose_name_plural = _('Stories')

    def get_mentor(self):
        out = self.mentor
        if not out:
            out = Agent.objects.filter(output_type=Agent.OUTPUT_TYPE_TEXT).first()
        return out
    
    def get_locations(self):
        return self.backgrounds.all().order_by('name')

    def get_cast(self):
        return self.characters.all().order_by('name')

    def get_slides(self):
        slides = []
        for scene in self.scenes.all().order_by('order'):
            for action in scene.actions.all().order_by('order'):
                slides.append(action.slide())
        return slides
    
    def get_conf(self, key):
        out = None
        if self.config and self.config and key in self.config.preset:
            out =  self.config.preset[key]
        return out

    def get_props(self):
        return Prop.objects.filter(story=self).order_by('name')

    def get_voices(self):
        return Voice.objects.filter(story=self).order_by('name')

    def get_missing_elements(self):
        """Collects all locations, cast characters, and props of a story that lack an image."""
        elements = set()
        for bg in self.get_locations():
            if not bg.image:
                elements.add(bg)
        for char in self.get_cast():
            if not char.image:
                elements.add(char)
        for prop in self.get_props():
            if not prop.image:
                elements.add(prop)
        return elements

    def import_group_members(self):
        if self.group is not None:
            for member in self.group.users.all():
                if not Author.objects.filter(story=self, user=member).exists():
                    Author.objects.create(story=self, user=member)

    def add_author(self, user):
        out = False
        if not Author.objects.filter(story=self, user=user).exists():
            Author.objects.create(story=self, user=user)
            out = True
        return out

    def save(self, *args, **kwargs):
        if not self.style:
            default_style = Style.objects.filter(global_default=True).first()
            if default_style:
                self.style = default_style
                
        do_import = not self.id and self.group is not None
        super().save(*args, **kwargs)
        if do_import:
            self.import_group_members()

    def intro(self):
        intro_action = Action.objects.filter(is_intro='story', scene__story=self).first()
        if intro_action:
            return intro_action.intro()
        return None
    
    def items(self):
        """
        Renders a summary dropdown of story elements using a template.
        """
        scenes_count = self.scenes.all().count()
        chars_count = self.get_cast().count()
        locs_count = self.get_locations().count()
        props_count = self.get_props().count()
        voices_count = self.get_voices().count()
        actions_count = Action.objects.filter(scene__story=self).count()
        video_actions_count = VideoAction.objects.filter(scene__story=self).count()
        comic_actions_count = ComicAction.objects.filter(scene__story=self).count()
        voice_actions_count = VoiceAction.objects.filter(scene__story=self).count()

        context = {
            "instance": self,
            "scenes_count": scenes_count,
            "characters_count": chars_count,
            "locations_count": locs_count,
            "props_count": props_count,
            "voices_count": voices_count,
            "actions_count": actions_count,
            "video_actions_count": video_actions_count,
            "comic_actions_count": comic_actions_count,
            "voice_actions_count": voice_actions_count,
            "count": scenes_count + chars_count + locs_count + props_count + voices_count + actions_count,
        }
        return render_to_string("story/items_dropdown.html", context)

    def generate_render(self, language=None):
        """
        Creates a new Render object for this story based on the story's render type
        and populates it with RenderItems for each action in the story's scenes.
        """
        lang = language or (get_language() or 'en').replace('-', '_').split('_')[0]
        render_type = self.render_type if self.render_type else 'animatic'
        render = Render.objects.create(
            story=self,
            name=f"Render for {self.name or self.id} ({lang.upper()})",
            render_type=render_type,
            language=lang
        )
        render.refresh_render()    
        return render

    def get_contents(self, generate_self=True, preset=None):
        parts = []
        if not generate_self:
            if self.style:
                parts.extend(self.style.get_contents(generate_self=False))
        elif preset in [self.PRESET_SYNC_SCENES, self.PRESET_EDIT_SCENES]:
                parts.append(self.prompt)
                parts.append(self.get_elements_as_yaml())
        elif preset == self.PRESET_EDIT_SYNC_ELEMENTS:
            parts.append(self.get_elements_as_yaml())
        elif preset in [self.PRESET_CREATE_ELEMENTS]:
            parts.append(self.prompt)
            parts.append(self.get_elements_as_yaml())
            if self.style:
                parts.append(self.style.get_contents(generate_self=False))   
        elif preset in [self.PRESET_EDIT_ELEMENTS]:
            parts.append(self.prompt_elements)
            parts.append(self.prompt)
            parts.append(self.get_elements_as_yaml())
            if self.style:
                parts.append(self.style.get_contents(generate_self=False))
        elif preset in [self.PRESET_SYNC_ELEMENTS]:
            parts.append(self.prompt_elements) 
        elif preset in [self.PRESET_TRANSLATE_SHOTS]:
            default_lang = getattr(settings, 'MODELTRANSLATION_DEFAULT_LANGUAGE', 'en')
            configured_langs = list(getattr(settings, 'MODELTRANSLATION_LANGUAGES', ('en', 'it', 'es', 'pt', 'fr')))
            shots_data = []

            for scene in self.scenes.all().order_by('order', 'id'):
                for action in scene.actions.all().order_by('order', 'id'):
                    if not action.prompt_voice and not any(getattr(action, f"prompt_voice_{l}", None) for l in configured_langs):
                        continue
                    shot_entry = {
                        'shot_id': action.id,
                        'shot_name': action.name,
                        'scene': scene.name or f"Scene {scene.id}",
                        'character_voice': action.voice.name if action.voice else "Narrator",
                    }
                    for l in configured_langs:
                        val = getattr(action, f"prompt_voice_{l}", None)
                        if not val and l == default_lang:
                            val = action.prompt_voice
                        shot_entry[f"prompt_voice_{l}"] = val or ""
                    shots_data.append(shot_entry)

            voice_yaml = yaml.dump({'shots': shots_data}, indent=2, sort_keys=False, allow_unicode=True) if shots_data else "shots: []"

            parts.append(
                f"### Story Voice Prompt Translation Task\n"
                f"Default language: `{default_lang}`\n"
                f"Target languages: `{configured_langs}`\n\n"
                f"Instructions:\n"
                f"1. For each shot, translate `prompt_voice_{default_lang}` into all target languages: {', '.join([f'prompt_voice_{l}' for l in configured_langs])}.\n"
                f"2. If `prompt_voice_{default_lang}` can be improved in quality, tone, or natural dialogue flow, provide a `suggested_default_improvement` field with the improved version.\n"
                f"3. Return the entire output in clean, valid YAML format matching the following structure:\n\n"
                f"```yaml\n"
                f"shots:\n"
                f"  - shot_id: <id>\n"
                f"    shot_name: <name>\n"
                f"    prompt_voice_{default_lang}: <original default text>\n"
                f"    suggested_default_improvement: <improved default text or null>\n"
                + "\n".join([f"    prompt_voice_{l}: <translated text in {l}>" for l in configured_langs if l != default_lang]) + "\n"
                f"```\n\n"
                f"Current Shot Voice Data:\n```yaml\n{voice_yaml}\n```"
            )
        else:
            parts = super().get_contents(generate_self=generate_self, preset=preset)
        
        return parts
    
class Scene(AfterSaveActionMixin, YAMLAssetsMixin, models.Model, TaskHolder, GetContentsMixin, ModelDisplayMixin):
    
    TASK_TEXT_GENERATE = settings.TASK_TYPE_GENERATE_TEXT
    TASK_EXTRACT_SCENE = settings.TASK_TYPE_EXTRACT_SCENE
    # draft 

    # shot prompt (shots)
    PRESET_CREATE_PROMPT = "scene_create_prompt"
    PRESET_EDIT_PROMPT = "scene_edit_prompt"

    # sync structure
    PRESET_SYNC_ELEMENTS = "scene_sync_elements"
    PRESET_SYNC_SHOTS = "scene_sync_shots"
    PRESET_SYNC_TRANSLATION = "scene_sync_translation"

    # edit a structured scene      
    PRESET_FROM_SHOTS = "scene_from_shots"
    PRESET_TRANSLATE = "translate"
    PRESET_TRANSLATE_SHOTS = "translate_shots"

    AGENT_PRESETS = (
        (PRESET_CREATE_PROMPT, _("Create prompt")),
        (PRESET_EDIT_PROMPT, _("Refine from prompt")),
        (PRESET_FROM_SHOTS, _("Refine from shots")),
        (PRESET_TRANSLATE, _("Translate from prompt")),
        (PRESET_TRANSLATE_SHOTS, _("Translate shots")),
        (PRESET_SYNC_SHOTS, _("Scene Sync Shots")),
        (PRESET_SYNC_ELEMENTS, _("Scene Sync Elements")),
        (PRESET_SYNC_TRANSLATION, _("Scene Sync Translation"))
    ) + settings.COMMON_TEXT_AGENT_PRESETS

    # shot prompt (shots)
    ACTION_CREATE_PROMPT = f"{TASK_TEXT_GENERATE}-preset-{PRESET_CREATE_PROMPT}"
    ACTION_EDIT_PROMPT = f"{TASK_TEXT_GENERATE}-preset-{PRESET_EDIT_PROMPT}"

    ACTION_EDIT_FROM_SHOTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_FROM_SHOTS}"
    
    ACTION_TRANSLATE_SHOTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_TRANSLATE_SHOTS}-target-prompt_translations-schema-{settings.SCHEMA_OUTPUT_WITH_MESSAGE}"
    ACTION_SYNC_ELEMENTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_ELEMENTS}-schema-{settings.SCHEMA_ASSETS}"
    ACTION_SYNC_SHOTS = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_SHOTS}-schema-{settings.SCHEMA_SCENE}"
    ACTION_SYNC_TRANSLATION = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_TRANSLATION}-schema-{settings.SCHEMA_TRANSLATION}"
    


    ACTION_CHOICES = (
        (ACTION_CREATE_PROMPT, _("Create prompt from plot")),  
        (ACTION_EDIT_PROMPT, _("Edit prompt")), 
        (ACTION_EDIT_FROM_SHOTS, _("Edit shots")),
        (ACTION_TRANSLATE_SHOTS, _("Translate shots")),
        (ACTION_SYNC_ELEMENTS, _("Sync Elements")),
        (ACTION_SYNC_SHOTS, _("Sync Shots")),
        (ACTION_SYNC_TRANSLATION, _("Sync Translation"))
    ) + settings.COMMON_TEXT_ACTION_CHOICES

    ACTION_NO_INPUT = (ACTION_CREATE_PROMPT, ACTION_TRANSLATE_SHOTS, ACTION_SYNC_SHOTS, ACTION_SYNC_TRANSLATION )
    ACTIONS_NO_INPUT = ACTION_NO_INPUT
    name = models.CharField(_("name"), max_length=200, null=True, blank=True)
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    prompt_plot = models.TextField(_("Prompt Plot"), null=True, blank=True)
    prompt = models.TextField(_("Prompt Shots from Draft"), null=True, blank=True, default="#Shots\n")    
    prompt_elements = models.TextField(_("Prompt Elements"), null=True, blank=True)
    prompt_translations = models.TextField(_("Prompt Translations"), null=True, blank=True)

    @property
    def translations(self):
        return self.prompt_translations

    @translations.setter
    def translations(self, value):
        self.prompt_translations = value

    action = models.SlugField(_("action"), max_length=1024, choices=ACTION_CHOICES, null=True, blank=True)

    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    story = models.ForeignKey('Story', verbose_name=_("story"), related_name='scenes', null=True, blank=True, on_delete=models.CASCADE)
    author = models.ForeignKey('Author', verbose_name=_("author"), related_name='scenes', on_delete=models.CASCADE, null=True, blank=True)
    instructions = models.ManyToManyField('agent.Prompt', verbose_name=_("instructions"), null=True, blank=True)

    history = HistoricalRecords()

    locations = models.ManyToManyField('Background', verbose_name=_("locations"), related_name='scenes', blank=True)
    cast = models.ManyToManyField('Character', verbose_name=_("cast"), related_name='scenes', blank=True)
    props = models.ManyToManyField('Prop', verbose_name=_("props"), related_name='scenes', blank=True)
    voices = models.ManyToManyField('Voice', verbose_name=_("voices"), related_name='scenes', blank=True)

    def __str__(self):
        return "{}".format(self.name if self.name else f"Scene{self.id} of {self.story}")
    
    def get_instructions(self, preset):
        return self.instructions.filter(category=preset)

    def shots(self):
        return self.actions.all()
    
    def get_shots_as_yaml(self):
        """
        Serializes the scene's actions (shots) into a YAML formatted string.
        """
        shots = self.shots()
        if not shots.exists():
            return None

        action_list = [
            ActionSchema(
                name=a.name,
                order=a.order,
                prompt=a.prompt or "",
                prompt_comic=a.prompt_comic or "",
                prompt_video=a.prompt_video or "",
                prompt_voice=a.prompt_voice or "",
                text=a.text or "",
                voice=a.voice.name if a.voice else "None",
                background=a.background.name if a.background else "None",
                cast=[c.name for c in a.cast.all()],
                props=[p.name for p in a.props.all()]
            ).model_dump()
            for a in shots
        ]
        
        return yaml.dump(action_list, indent=2, default_flow_style=False)

    def location_parts(self):
        parts = []
        for location in self.locations.all():
            parts.extend(location.get_contents(generate_self=False))
        return parts
                         
    def get_contents(self, generate_self=True, preset=None):
        parts = []
        if not generate_self:
            parts.extend(self.story.style.get_contents(generate_self=False))
        else:
            # deprecated
            if preset == self.PRESET_REFINE_PROMPT:
                parts.append(self.prompt_refine)
                if self.shots().exists():
                    parts.append(self.get_shots_as_yaml())
                else:
                    parts.append(self.prompt)
            elif preset == self.PRESET_SYNC_ELEMENTS:
                parts.append(self.prompt_plot)
                parts.extend(self.location_parts())
            elif preset in [self.PRESET_CREATE_PROMPT]:
                parts.append(self.prompt_plot)
                parts.extend(self.location_parts())
            elif preset in [self.PRESET_EDIT_PROMPT]:
                parts.append(self.prompt)
                parts.extend(self.location_parts())
            elif preset == self.PRESET_FROM_SHOTS:
                if self.shots().exists():
                    parts.append(self.get_shots_as_yaml())
            elif preset == self.PRESET_EDIT_PROMPT:
                if self.prompt:
                    parts.append(self.prompt)
                elif self.prompt_plot:
                    parts.append(self.prompt_plot)
            elif preset == self.PRESET_SYNC_SHOTS:
                parts.append(f"<MdScript>{self.prompt}</MdScript>")
            elif preset ==  self.PRESET_TRANSLATE_SHOTS:
                default_lang = getattr(settings, 'MODELTRANSLATION_DEFAULT_LANGUAGE', 'en')
                configured_langs = list(getattr(settings, 'MODELTRANSLATION_LANGUAGES', ('en', 'it', 'es', 'pt', 'fr')))
                shots_data = []

                for action in self.actions.all().order_by('order', 'id'):
                    if not action.prompt_voice and not any(getattr(action, f"prompt_voice_{l}", None) for l in configured_langs):
                        continue
                    shot_entry = {
                        'shot_id': action.id,
                        'shot_name': action.name,
                        'scene': self.name or f"Scene {self.id}",
                        'character_voice': action.voice.name if action.voice else "Narrator",
                    }
                    for l in configured_langs:
                        val = getattr(action, f"prompt_voice_{l}", None)
                        if not val and l == default_lang:
                            val = action.prompt_voice
                        shot_entry[f"prompt_voice_{l}"] = val or ""
                    shots_data.append(shot_entry)

                voice_yaml = yaml.dump({'shots': shots_data}, indent=2, sort_keys=False, allow_unicode=True) if shots_data else "shots: []"

                parts.append(
                    f"### Scene Voice Prompt Translation Task\n"
                    f"Scene: `{self.name or self.id}`\n"
                    f"Default language: `{default_lang}`\n"
                    f"Target languages: `{configured_langs}`\n\n"
                    f"Instructions:\n"
                    f"1. For each shot in this scene, translate `prompt_voice_{default_lang}` into all target languages: {', '.join([f'prompt_voice_{l}' for l in configured_langs])}.\n"
                    f"2. If `prompt_voice_{default_lang}` can be improved in quality, tone, or natural dialogue flow, provide a `suggested_default_improvement` field with the improved version.\n"
                    f"3. Return the entire output in clean, valid YAML format matching the following structure:\n\n"
                    f"```yaml\n"
                    f"shots:\n"
                    f"  - shot_id: <id>\n"
                    f"    shot_name: <name>\n"
                    f"    prompt_voice_{default_lang}: <original default text>\n"
                    f"    suggested_default_improvement: <improved default text or null>\n"
                    + "\n".join([f"    prompt_voice_{l}: <translated text in {l}>" for l in configured_langs if l != default_lang]) + "\n"
                    f"```\n\n"
                    f"Current Scene Shot Voice Data:\n```yaml\n{voice_yaml}\n```"
                )
                return parts
            elif preset in [self.PRESET_SYNC_TRANSLATION]:
                if self.prompt_translations:
                    parts.append(self.prompt_translations)
                return parts
        if self.story and preset in [
                self.PRESET_REFINE_PROMPT,
                self.PRESET_FROM_SHOTS,
                self.PRESET_CREATE_PROMPT, 
                self.PRESET_EDIT_PROMPT, 
                self.PRESET_SYNC_SCENE,
                self.PRESET_SYNC_ELEMENTS,
                self.PRESET_SYNC_SHOTS                
            ]:
            elements_yaml = self.story.get_elements_as_yaml()
            if elements_yaml: parts.append(elements_yaml)
        
        if len(parts) == 0:
            parts = super().get_contents(generate_self=generate_self, preset=preset)
        return parts

    def get_cast(self):
        return self.cast.all()

    def get_locations(self):
        return self.locations.all()

    def get_props(self):
        return self.props.all()

    def get_voices(self):
        return self.voices.all()

    def get_missing_elements(self):
        """Collects all locations, cast characters, and props of a scene that lack an image."""
        elements = set()
        for bg in self.get_locations():
            if not bg.image:
                elements.add(bg)
        for char in self.get_cast():
            if not char.image:
                elements.add(char)
        for prop in self.get_props():
            if not prop.image:
                elements.add(prop)
        return elements

    def get_elements(self):
        """
        Returns a dictionary containing distinct Backgrounds, Props, Characters, and Voices
        referenced by all actions within this scene, ordered by name.
        """
        actions = self.actions.all()

        locations = self.get_locations()
        props = self.get_props()
        characters = self.get_cast()
        voices = self.get_voices()
       
        return {
            'locations': locations,
            'characters': characters,
            'props': props,
            'voices': voices,
        }

    def items(self):
        """
        Renders a summary dropdown of scene elements using a template.
        """
        props_count = self.props.count()
        chars_count = self.cast.count()
        locs_count = self.locations.count()
        voices_count = self.voices.count()
        actions_count = self.actions.count()

        context = {
            "instance": self,
            "count": props_count + chars_count + locs_count + voices_count + actions_count,
            "props_count": props_count,
            "characters_count": chars_count,
            "locations_count": locs_count,
            "voices_count": voices_count,
            "actions_count": actions_count,
        }
        return render_to_string("scene/items_dropdown.html", context)

    def generate_render(self, language=None):
        """
        Creates a new Render object for this scene based on the story's render type
        and populates it with RenderItems for each action in the scene.
        """
        lang = language or (get_language() or 'en').replace('-', '_').split('_')[0]
        render_type = self.story.render_type if (self.story and self.story.render_type) else 'animatic'
        render = Render.objects.create(
            scene=self,
            story=self.story,
            name=f"Render for {self.name or self.id} ({lang.upper()})",
            render_type=render_type,
            language=lang
        )
        render.refresh_render()
        
        return render

    class Meta:
        ordering = ['order']


class Nudge(models.Model, EmailSenderMixin):
    email_template = 'email/nudge.html'

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("sender"), related_name='sent_nudges', on_delete=models.CASCADE, null=True, blank=True)
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("receiver"), related_name='received_nudges', on_delete=models.CASCADE, null=True, blank=True)
    story = models.ForeignKey('scene.Story', verbose_name=_("story"), related_name='nudges', on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField(_("message"), null=True, blank=True, help_text=_("Optional message to include in the nudge email."))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        return "{}".format(self.sender.username)

    def mark_as_read(self):
        self.read = True
        self.save() 
   
    def save(self, *args, **kwargs):
        if self.sender == self.receiver:
            raise ValueError("Sender and receiver cannot be the same user.")
        send = False
        cta_url = ""
        if not self.id:
            author = Author.objects.filter(story=self.story, user=self.receiver).first()
            if author:
                cta_url = settings.SITE_URL + f'/admin/scene/scene/add?story={self.story.id}&author={author.id}'
                send = True
        super().save(*args, **kwargs)
        if send:
            self.send_email(
                subject=_("Nudge on the story: %(story_name)s. %(sender_name)s nudged you!") % {
                    'story_name': self.story.name,
                    'sender_name': self.sender.username
                },
                context={
                    'item': self,
                    'cta': cta_url
                },
                recipient_list=[self.receiver.email]
            )


class Prop(AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder, ModelDisplayMixin):
    name = models.CharField(_("name"), max_length=100, default="")
    image = FilerImageField(verbose_name=_("image"), null=True, blank=True, on_delete=models.SET_NULL, related_name='props')
    prompt= models.TextField(_("prompt"), null=True, blank=True)
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    story = models.ForeignKey('Story', verbose_name=_("story"), related_name='props', null=True, blank=True, on_delete=models.CASCADE)
    history = HistoricalRecords()

    # trick to save and execute tasks
    TASK_TYPE_CHOICES = settings.TASK_TYPE_CHOICES
    action = models.SlugField(_("action"), choices=settings.TASK_TYPE_CHOICES, null=True, blank=True)

    def __str__(self):
        return "{}".format(self.name)

    def context_text(self, generate_self=True, preset=None):
        if preset == self.PRESET_REFINE:
            return self.prompt_refine
        if generate_self:
            return self.prompt
        return f"Object or Prop referenced as: {self.name}:"
    
    def get_contents(self, generate_self=True, preset=None):
        parts = super().get_contents(generate_self=generate_self, preset=preset)
        if self.story and self.story.style and generate_self:
            parts.extend(self.story.style.get_contents(generate_self=False))
        return parts

class Voice(AfterSaveActionMixin, models.Model, TaskHolder, GetContentsMixin, ModelDisplayMixin):
    SAMPLE_TEXT_DEFAULT = "Hello, this is a sample voice. 1, 2, 3. Change me and add a sample prompt for better results. Add audio effects for more interesting voices!"
    PROMPT_SAMPLE_DEFAULT = "Speak:"
    PROMPT_DEFAULT = "Style: [describe the style of speaking you want, e.g. excited, sad, professional, etc.]\nPace: [describe the pace of speaking you want, e.g. fast, slow, etc.]\nAccent: [describe the accent you want, e.g. British, American, etc.]\n\n"
    
    name = models.CharField(_("name"), max_length=100)
    google_voice = models.ForeignKey('agent.GoogleVoice', verbose_name=_("google voice"), related_name='voices', on_delete=models.SET_NULL, null=True, blank=True)
    prompt = models.TextField(_("prompt"), null=True, blank=True , default=PROMPT_DEFAULT)
    audio_voice = FilerFileField(verbose_name=_("audio voice"), null=True, blank=True, on_delete=models.SET_NULL, related_name='samples')
    sample_text = models.TextField(_("sample text"), null=True, blank=True , default=SAMPLE_TEXT_DEFAULT)
    story = models.ForeignKey('scene.Story', verbose_name=_("story"), related_name='voices', on_delete=models.CASCADE, null=True, blank=True)
    global_default = models.BooleanField(_("global default"), default=False)
    history = HistoricalRecords()

    TASK_TYPE_CHOICES = [
        (settings.TASK_TYPE_GENERATE_VOICE, _("Generate Voice"))
    ]
    action = models.SlugField(_("action"), choices=TASK_TYPE_CHOICES, null=True, blank=True)

    
    def __str__(self):
        return "{}".format(self.name)
    
    def get_prompt_header(self):
        return f"# AUDIO PROFILE: {self.name}/n/n"

    def get_sample_text(self):
        return self.sample_text if self.sample_text else self.SAMPLE_TEXT_DEFAULT
    
    def get_contents(self, generate_self=True, preset=None):
        prompt = ""
        if preset == self.PRESET_VOICE:
            prompt = f"out {self.get_prompt_header()} ### DIRECTOR'S NOTES\n\n {self.prompt} \n\n #### TRANSCRIPT \n\n"
            if generate_self:
                prompt += self.get_sample_text()
        return {
            'prompt': prompt,
            'voice': self.google_voice.name
        }
    
class Character(models.Model, GetContentsMixin, TaskHolder, ModelDisplayMixin):
    name = models.CharField(_("name"), max_length=100, default="")
    image = FilerImageField(verbose_name=_("image"), null=True, blank=True, on_delete=models.SET_NULL, related_name='characters')
    prompt= models.TextField(_("prompt"), null=True, blank=True)
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    story = models.ForeignKey('Story', verbose_name=_("story"), related_name='characters', null=True, blank=True, on_delete=models.CASCADE)
    voice = models.ForeignKey(Voice, verbose_name=_("voice"), related_name='characters', on_delete=models.SET_NULL, null=True, blank=True) 
    TASK_TYPE_CHOICES = settings.TASK_TYPE_CHOICES
    action = models.SlugField(_("action"), choices=settings.TASK_TYPE_CHOICES, null=True, blank=True)
    history = HistoricalRecords()
   
    def __str__(self):
        return "{}".format(self.name)

    def context_text(self, generate_self=True, preset=None):
        if preset == self.PRESET_REFINE:
            return self.prompt_refine
        if generate_self:
            return self.prompt
        return f"Character: {self.name}:"

    def get_contents(self, generate_self=True, preset=None):
        parts = super().get_contents(generate_self=generate_self, preset=preset)
        if self.story and self.story.style and generate_self:
            parts.extend(self.story.style.get_contents(generate_self=False))
        return  parts # reverse to have the character prompt last so it is more important

    class Meta:
        verbose_name = _('Character')
        verbose_name_plural = _('Characters')


class Background(AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder, ModelDisplayMixin):
    name = models.CharField(_("name"), max_length=100, default="")
    prompt= models.TextField(_("prompt"), null=True, blank=True)
    image = FilerImageField(verbose_name=_("image"), null=True, blank=True, on_delete=models.SET_NULL, related_name='backgrounds')
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    image_refine = FilerImageField(verbose_name=_("image refine"), null=True, blank=True, on_delete=models.SET_NULL, related_name='background_refine')
    story = models.ForeignKey('Story', verbose_name=_("story"), related_name='backgrounds', null=True, blank=True, on_delete=models.CASCADE)
    history = HistoricalRecords()

    # trick to save and execute tasks
    TASK_TYPE_CHOICES = settings.TASK_TYPE_CHOICES
    action = models.SlugField(_("action"), choices=settings.TASK_TYPE_CHOICES, null=True, blank=True)


    def config(self, field_name, default=None):
        if field_name == self.CONFIG_ASPECT_RATIO:
            return self.ASPECT_RATIO_16_9
        return super().config(field_name, default=default)
    
    def __str__(self):
        return "{}".format(self.name)

    def context_text(self, generate_self=True, preset=None):
        if preset == self.PRESET_REFINE:
            return self.prompt_refine
        if generate_self:
            return self.prompt
        return self.name

    def get_contents(self, generate_self=True, preset=None):
        parts = super().get_contents(generate_self=generate_self, preset=preset)
        if self.story and self.story.style and generate_self and not preset == self.PRESET_REFINE:
            parts.extend(self.story.style.get_contents())
        return parts

    class Meta:
        verbose_name = _('Location')
        verbose_name_plural = _('Locations')

class Sync(AfterSaveActionMixin, models.Model, TaskHolder, ModelDisplayMixin):
    story = models.ForeignKey('Story', verbose_name=_("story"), related_name='syncs', on_delete=models.CASCADE)
    last_file_in = FilerFileField(verbose_name=_("last file in"), null=True, blank=True, on_delete=models.SET_NULL, related_name='syncs_in')
    last_file_out = FilerFileField(verbose_name=_("last file out"), null=True, blank=True, on_delete=models.SET_NULL, related_name='syncs_out')

    def __str__(self):
        return f"Sync: {self.story.name}"

class SyncItem(AfterSaveActionMixin, models.Model, TaskHolder, ModelDisplayMixin):
    TYPE_IMPORT = 'import'
    TYPE_EXPORT = 'export'
    TYPE_CHOICES = [
        (TYPE_IMPORT, _('Import')),
        (TYPE_EXPORT, _('Export')),
    ]
    sync = models.ForeignKey(Sync, verbose_name=_("sync"), related_name='items', on_delete=models.CASCADE)
    type = models.CharField(_("type"), max_length=10, choices=TYPE_CHOICES)
    zip_file = FilerFileField(verbose_name=_("zip file"), null=True, blank=True, on_delete=models.SET_NULL, related_name='sync_items')
    
    TASK_TYPE_CHOICES = settings.TASK_TYPE_CHOICES
    action = models.SlugField(_("action"), choices=TASK_TYPE_CHOICES, null=True, blank=True)

    def __str__(self):
        return f"{self.get_type_display()} for {self.sync.story.name} ({self.id})"

    class Meta:
        ordering = ['-id']


class StoryGroup(models.Model):
    story = models.ForeignKey(Story, verbose_name=_("story"), related_name='story_groups', on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(_("name"), max_length=200)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name=_("users"), related_name='story_groups')
    
    def __str__(self):
        return "{}".format(self.name)


class StoryProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name=_("user"), related_name='story_profile', on_delete=models.CASCADE)
    story = models.ForeignKey(Story, verbose_name=_("story"), related_name='story_profiles', on_delete=models.SET_NULL, null=True, blank=True)
    scene = models.ForeignKey(Scene, verbose_name=_("scene"), related_name='story_profiles', on_delete=models.SET_NULL, null=True, blank=True)
    group = models.ForeignKey(StoryGroup, verbose_name=_("group"), related_name='story_profiles', on_delete=models.SET_NULL, null=True, blank=True)
    enable_filters = models.BooleanField(_("enable filters"), default=False)
    
    def __str__(self):
        return "{}".format(self.user.username)

    def get_current_story(self):
        story = None
        if self.story:
            story = self.story
        if self.group and self.group.story:
            story = self.group.story
        if not story and self.scene and self.scene.story:
            story = self.scene.story
        return story

class Action(AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder, ModelDisplayMixin):
    
    IS_INTRO_CHOICES = [
        ('scene', _('Scene Intro')),
        ('story', _('Story Intro'))
    ]
    SHOT_TYPE_SILENT = 'silent'
    SHOT_TYPE_VOICE = 'voice'
    SHOT_TYPE_VIDEO = 'video'
    SHOT_TYPE_COMIC = 'comic'
    SHOT_TYPE_VIDEO_LOOP = 'video_loop'

    RENDER_TYPE_GRAPHIC_NOVEL = 'comic'
    RENDER_TYPE_ANIMATIC = 'animatic'

    SHOT_TYPE_CHOICES = [
        (SHOT_TYPE_SILENT, _('Silent')),
        (SHOT_TYPE_VOICE, _('Voice')),
        (SHOT_TYPE_VIDEO, _('Video')),
        (SHOT_TYPE_COMIC, _('Comic')),
        (SHOT_TYPE_VIDEO_LOOP, _('Video Loop')),
    ]

    name = models.CharField(_("name"), max_length=200, default="Action")
    scene = models.ForeignKey(Scene, verbose_name=_("scene"), related_name='actions', on_delete=models.CASCADE)
    is_intro = models.SlugField(_("is intro"), choices=IS_INTRO_CHOICES, null=True, blank=True)
    prompt = models.TextField(_("prompt"), null=True, blank=True)
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    image = FilerImageField(verbose_name=_("image"), null=True, blank=True, on_delete=models.SET_NULL, related_name='panel')
    background = models.ForeignKey(Background, verbose_name=_("background"), related_name='actions', on_delete=models.SET_NULL, null=True, blank=True)
    actor = models.ForeignKey(Character, verbose_name=_("actor"), related_name='actions', on_delete=models.SET_NULL, null=True, blank=True)
    props = models.ManyToManyField(Prop, verbose_name=_("props"), related_name='actions', blank=True)
    cast = models.ManyToManyField(Character, verbose_name=_("cast"), related_name='actions_cast', blank=True)
    consistent_with = models.ForeignKey('self', verbose_name=_("consistent with"), related_name='consistent_actions', on_delete=models.SET_NULL, null=True, blank=True)
    prompt_refine = models.TextField(_("prompt refine"), null=True, blank=True)
    image_refine = FilerImageField(verbose_name=_("image refine"), null=True, blank=True, on_delete=models.SET_NULL, related_name='action_refine')
    # video
    image_first = FilerImageField(verbose_name=_("image first"), null=True, blank=True, on_delete=models.SET_NULL, related_name='actions_first')
    image_last = FilerImageField(verbose_name=_("image last"), null=True, blank=True, on_delete=models.SET_NULL, related_name='actions_last')
    video = FilerFileField(verbose_name=_("video"), null=True, blank=True, on_delete=models.SET_NULL, related_name='actions_video')
    prompt_video = models.TextField(_("prompt video"), null=True, blank=True)

    TASK_TYPE_CHOICES = settings.TASK_TYPE_CHOICES#
    action = models.SlugField(_("action"), choices=settings.TASK_TYPE_CHOICES, null=True, blank=True)

    prompt_comic = models.TextField(_("prompt comic"), null=True, blank=True)
    image_comic = FilerImageField(verbose_name=_("image comic"), null=True, blank=True, on_delete=models.SET_NULL, related_name='actions_comic')
    voice = models.ForeignKey(Voice, verbose_name=_("voice"), related_name='actions_voice', on_delete=models.SET_NULL, null=True, blank=True)
    audio_voice = FilerFileField(verbose_name=_("audio voice"), null=True, blank=True, on_delete=models.SET_NULL, related_name='actions_audio')
    prompt_voice = models.TextField(_("prompt voice"), null=True, blank=True)
    text = models.TextField(_("text"), null=True, blank=True)
    parameters = models.JSONField(_("configuration"), null=True, blank=True)
    shot_type = models.CharField(_("shot type"), max_length=20, choices=SHOT_TYPE_CHOICES, null=True, blank=True)
    history = HistoricalRecords(
        excluded_fields=[
            f"{f}_{lang}"
            for f in ("prompt_comic", "prompt_voice", "image_comic", "audio_voice")
            for lang in getattr(settings, "MODELTRANSLATION_LANGUAGES", ("en", "it", "es", "pt", "fr"))
        ]
    )

    def __str__(self):
        return self.get_name()
    
    def get_name(self):
        return self.name if self.name else f"#{self.id} of{self.scene.name}"
        
    def items(self):
        """Renders the explore dropdown for the action."""
        return render_to_string("scene/action_items_dropdown.html", {"instance": self, "scene": self.scene})
    items.short_description = _("Items")

    def slide(self):
        return {
            "media_url": self.video.url if self.video else (self.image_comic.url if self.image_comic else (self.image.url if self.image else None)),
            "media_type": "video" if self.video else "image",
            "audio_url": self.audio_voice.url if self.audio_voice else None,
            "text": self.text,
            "name": self.get_name()
        }

    class Meta:
        ordering = ['order', 'name']
        verbose_name = _('Shot')
        verbose_name_plural = _('Shots')

    def elements(self):
        props = []
        cast_members = []
        main_actor = self.actor.name if self.actor else "None"
        background = self.background.name if self.background else "None"
        if self.props:
            props.extend([prop.name for prop in self.props.all()])
        if self.cast:
            cast_members.extend([character.name for character in self.cast.all()])
        output =  f"Main Actor: <b>{main_actor}</b><br/> Background: <b>{background}</b><br/> Props: <b>{', '.join(props)}</b><br/> Cast: <b>{', '.join(cast_members)}</b><br/>"
        return mark_safe(output)
    
    def get_thumbnail(self, preset=None):
        return Image.open(self.image.path)

    def generate_comic(self, user=None, target_field="image_comic"):
        image_agent = Agent.objects.filter(output_type=Agent.OUTPUT_TYPE_IMAGE).first()
        out = image_agent.generate(self, preset=self.PRESET_COMIC, user=user, target_field=target_field)
        return out
    
    def intro(self):
        out = None
        if self.image_comic:
            out = self.image_comic
        elif self.image:
            out = self.image   
        return out

    def _build_flow_video_prompt(self):
        base_prompt = (self.prompt_video or self.prompt or "").strip()
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        dialogue = getattr(self, f"prompt_voice_{lang}", None) or self.prompt_voice
        if self.actor and dialogue and f"@{self.actor.name}" not in base_prompt:
            return f'@{self.actor.name.strip()} says: "{dialogue.strip()}" {base_prompt}'.strip()
        return base_prompt

    def get_contents(self, generate_self=True, preset=None):
        from google.genai import types
        if preset == self.PRESET_FLOW_VIDEO:
            contents = {
                'prompt': self._build_flow_video_prompt(),
                'image': self.image,
            }
        elif preset in (self.PRESET_VIDEO, self.PRESET_OMNI_VIDEO):
            contents = {}
            contents['prompt'] = self.prompt_video or self.prompt
            contents['image'] = self.image_comic or self.image
        elif preset == self.PRESET_VIDEO_FIRST_LAST:
            contents = {}
            contents['prompt'] = self.prompt_video
            contents['image_first'] = self.image_first or self.image
            contents['image_last'] = self.image_last or contents['image_first']
        elif preset == self.PRESET_VOICE:
            contents = {}
            contents = self.voice.get_contents(generate_self=False, preset=Voice.PRESET_VOICE)
            lang = (get_language() or 'en').replace('-', '_').split('_')[0]
            voice_prompt = getattr(self, f"prompt_voice_{lang}", None) or self.prompt_voice or ""
            contents["prompt"] += voice_prompt
        else:
            # preset refine is handled in the mixin
            contents = super().get_contents(generate_self=generate_self, preset=preset)
            if preset != self.PRESET_COMIC and preset != self.PRESET_REFINE:
                if self.consistent_with:
                    contents.extend(["Maximise consistency, preserve character features and objects to the following image", self.consistent_with.image])
                if self.actor:
                    contents.extend(self.actor.get_contents(generate_self=False))
                if self.cast:
                    for character in self.cast.all():
                        contents.extend(character.get_contents(generate_self=False))
                if self.props:
                    for prop in self.props.all():
                        contents.extend(prop.get_contents(generate_self=False))
                if self.background:
                    contents.extend(self.background.get_contents(generate_self=False))
                if self.scene:
                    contents.extend(self.scene.get_contents(generate_self=False))
        return contents
    
    def context_text(self, generate_self=True, preset=None):
        out = None
        if not generate_self:
            out = self.name
        elif preset == self.PRESET_IMAGE:
            out = self.prompt
        elif preset == self.PRESET_COMIC:
            out = self.prompt_comic 
        elif preset == self.PRESET_REFINE:
            return self.prompt_refine
        return out

class SceneOrganizer(Scene):
    class Meta:
        proxy = True
        verbose_name = _('Scene Organizer')
        verbose_name_plural = _('Scene Organizers')

class ActionOrganizer(Action):
    class Meta:
        proxy = True
        verbose_name = _('Shot Organizer')
        verbose_name_plural = _('Shot Organizers')

class VideoAction(Action):

    ACTION_FLOW_VIDEO = 'flow_video'
    ACTION_OMNI_VIDEO = 'omni_video'
    ACTION_CHOICES = (
        (ACTION_FLOW_VIDEO, _("Create omni video")),  
        (ACTION_OMNI_VIDEO, _("Edit flow video")), 
     ) + settings.COMMON_TEXT_ACTION_CHOICES
    
    class Meta:
        proxy = True
        verbose_name = _('Video Shot ')
        verbose_name_plural = _('Video Shots')

class ComicAction(Action):
    class Meta:
        proxy = True
        verbose_name = _('Comic Shot')
        verbose_name_plural = _('Comic Shots')


class VoiceAction(Action):
    class Meta:
        proxy = True
        verbose_name = _('Voice Shot')
        verbose_name_plural = _('Voice Shots')


class Render(RenderTypeMixin, models.Model, TaskHolder, ModelDisplayMixin):
    RENDER_TYPE_FILM = 'film'
    RENDER_TYPE_GRAPHIC_NOVEL = 'comic'
    RENDER_TYPE_ANIMATIC = 'animatic'

    RENDER_TYPE_CHOICES = [
        (RENDER_TYPE_FILM, _('Film')),
        (RENDER_TYPE_GRAPHIC_NOVEL, _('Graphic Novel')),
        (RENDER_TYPE_ANIMATIC, _('Animatic')),
    ]

    name = models.CharField(_("name"), max_length=200, default="")
    scene = models.ForeignKey(Scene, verbose_name=_("scene"), related_name='renders', null=True, blank=True, on_delete=models.CASCADE)
    video = FilerFileField(verbose_name=_("video"), null=True, blank=True, on_delete=models.SET_NULL, related_name='render_videos')
    story = models.ForeignKey(Story, verbose_name=_("story"), related_name='renders', null=True, blank=True, on_delete=models.CASCADE)
    render_type = models.CharField(
        _("render type"),
        max_length=50,
        choices=RENDER_TYPE_CHOICES,
        default=RENDER_TYPE_FILM,
        help_text=_("The format in which this scene will be synthesized.")
    )
    language = models.CharField(
        _("language"),
        max_length=10,
        choices=settings.LANGUAGES,
        default='en',
        help_text=_("The language for voiceovers and localized assets.")
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True, null=True, blank=True)
    modified_at = models.DateTimeField(_("modified at"), auto_now=True, null=True, blank=True)

    def __str__(self):
        return "{}".format(self.name)

    def _create_item_from_action(self, action, order):
        """Helper to create a RenderItem based on the current render_type and language."""
        item = RenderItem(
            render=self,
            scene=action.scene,
            action=action,
            order=order
        )

        lang = (self.language or 'en').replace('-', '_').split('_')[0]
        item.video = action.video
        audio = getattr(action, f"audio_voice_{lang}", None) or action.audio_voice
        item.audio = audio
        comic_img = getattr(action, f"image_comic_{lang}", None) or action.image_comic
        item.image = comic_img or action.image
        comic_img = getattr(action, f"image_comic_{lang}", None) or action.image_comic
        item.image = comic_img or action.image
        item.save()
        return item
    def get_conf(self, key):
        story = self.story
        if self.scene:
            story = self.scene.story
        return story.get_conf(key)

    def refresh_render(self):
        """
        Clears existing RenderItems and recreates them. 
        Iterates through the Story's scenes if available, otherwise just the specific Scene.
        """
        self.render_items.all().delete()

        actions = []
        if self.scene:
            actions = list(self.scene.actions.all().order_by('order'))
        elif self.story:
            actions = list(Action.objects.filter(scene__story=self.story).order_by("order"))
        for i, action in enumerate(actions):
            self._create_item_from_action(action, order=i)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = _('Render Composition')
        verbose_name_plural = _('Render Compositions')

    @classmethod
    def get_from_scene(cls, scene, language=None):
        lang = language or (get_language() or 'en').replace('-', '_').split('_')[0]
        render_type = scene.story.render_type if (scene.story and scene.story.render_type) else cls.RENDER_TYPE_ANIMATIC
        return cls.objects.get_or_create(
            scene=scene,
            story=scene.story,
            language=lang,
            defaults={
                'name': f"Render for {scene.name} ({lang.upper()})",
                'render_type': render_type,
            }
        )[0]
        
class RenderItem(models.Model, TaskHolder, ModelDisplayMixin):
    DEFAULT_IMAGE_DURATION = 8
    image = FilerImageField(verbose_name=_("image"), null=True, blank=True, on_delete=models.SET_NULL, related_name='video_item')
    video = FilerFileField(verbose_name=_("video"), null=True, blank=True, on_delete=models.SET_NULL, related_name='video_item_video')
    audio = FilerFileField(verbose_name=_("audio"), null=True, blank=True, on_delete=models.SET_NULL, related_name='video_item_audio')
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    config = models.JSONField(_("config"), null=True, blank=True)
    params = models.CharField(_("params"), max_length=255, null=True, blank=True)
    render = models.ForeignKey("scene.Render", verbose_name=_("render"), related_name='render_items',null=True, blank=True, on_delete=models.CASCADE)
    scene = models.ForeignKey("scene.Scene", verbose_name=_("scene"), related_name='render_items', null=True, blank=True, on_delete=models.SET_NULL)
    action = models.ForeignKey("scene.Action", verbose_name=_("action"), related_name='render_items', null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Item {self.order} for {self.render.name if self.render else 'Unassigned'}"
    
    class Meta:
        ordering = ['order']
        verbose_name = _('Render Item')
        verbose_name_plural = _('Render Items')

    @property
    def duration(self):
        out = self.DEFAULT_IMAGE_DURATION
        if self.config and 'duration' in self.config: 
            out = self.config['duration']
        return out

class WorkShop(models.Model):
    name = models.CharField(_("name"), max_length=255)
    description = models.TextField(_("description"))
    date = models.DateTimeField(_("date"))
    location = models.CharField(_("location"), max_length=255)

    def __str__(self):
        return self.name

class ContactRequest(models.Model):
    CONTRIBUTION_CHOICES = [
        ("pay", _("I am ok to pay 20/30 dollars/euros for the workshop")),
        ("api_key", _("I am ok to bring my google api key to the project")),
        ("collaborate", _("I want to help testing")),
        ("trial", _("I just want to try it out and use the local open source version")),
    ]

    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"))
    contribuition = models.TextField(_("contribution"), choices=CONTRIBUTION_CHOICES, null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    prompt = models.TextField(_("A glimpse of your imagination"), null=True, blank=True, help_text=_("Just imagine and write with as many typos as you want. Guillermo will curate your scene"), default="#Location\n#Cast\n#Props\n#Actions\n")
    workshop = models.ForeignKey(WorkShop, verbose_name=_("workshop"), related_name='contact_requests', on_delete=models.CASCADE, null=True, blank=True)
    group_number = models.IntegerField(_("group number"), null=True, blank=True, help_text=_("How many friends and family member you would bring to the workshop?"))

    def __str__(self):
        return f"{self.name} ({self.email})"