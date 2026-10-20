import yaml
from django.contrib import admin
try:
    from unfold.decorators import action
except ImportError:
    from django.contrib.admin import action
from django.utils.html import format_html
from .schemas import AssetsSchema, BackgroundSchema, CharacterSchema, PropSchema, VoiceSchema
from django.utils.translation import gettext_lazy as _, get_language
from django.urls import path
from django.conf import settings
from task.models import Task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.models import Group, Permission, User
from django.conf import settings
import secrets
import string
from django.http import JsonResponse
from django.apps import apps
from .utils import render_image_markup, get_thumbnail_url
from django.shortcuts import get_object_or_404

ELEMENT_FIELDSETS = (
        ("Write", {
            "classes": ["tab"],
            "fields": ["name","prompt",  'action'],
        }),
        ("Settings", {
            "classes": ["tab"],
            "fields": ["image","prompt_refine", "story" ],
        }),
    )

ACTION_FIELDSETS = (
        ("Composition", {
            "classes": ["tab"],
            "fields": ["name", "scene", "prompt", "order", "actor", "props", "cast", "background", "consistent_with", "image"],
        }),
        ("Translations", {
            "classes": ["tab"],
            "fields": ["prompt_comic", "image_comic", "prompt_voice", "audio_voice"],
        }),
        ("Video", {
            "classes": ["tab"],
            "fields": ["prompt_video", "video", "image_first", "image_last"],
        }),
        ("Refine", {
            "classes": ["tab"],
            "fields": ["prompt_refine", "image_refine"],
        }),
        ("Execute On Save", {
            "classes": ["tab"],
            "fields": ["action"],
        }),
    )

class CurrentLanguageListMixin:
    """Ensures translated fields in list_display, list_editable, and ajax_shift_fields show and edit only the current active language."""

    def __init__(self, model, admin_site):
        self._orig_list_display = tuple(getattr(self, 'list_display', ()))
        self._orig_list_editable = tuple(getattr(self, 'list_editable', ()))
        super().__init__(model, admin_site)

    def _is_translated_field(self, field_name):
        if not field_name or not isinstance(field_name, str):
            return None
        for code, lang_name in getattr(settings, 'LANGUAGES', ()):
            if field_name.endswith(f"_{code}"):
                base = field_name[:-len(code)-1]
                try:
                    self.model._meta.get_field(f"{base}_{code}")
                    return base
                except Exception:
                    pass
        for code, lang_name in getattr(settings, 'LANGUAGES', ()):
            try:
                self.model._meta.get_field(f"{field_name}_{code}")
                return field_name
            except Exception:
                pass
        return None

    def _map_current_lang_fields(self, field_list):
        if not field_list:
            return field_list
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]

        result = []
        seen = set()
        for field in field_list:
            base_field = self._is_translated_field(field)
            if base_field:
                lang_field = f"{base_field}_{lang}"
                try:
                    self.model._meta.get_field(lang_field)
                    target = lang_field
                except Exception:
                    default_field = f"{base_field}_en"
                    try:
                        self.model._meta.get_field(default_field)
                        target = default_field
                    except Exception:
                        target = field
                if target not in seen:
                    seen.add(target)
                    result.append(target)
            else:
                if field not in seen:
                    seen.add(field)
                    result.append(field)
        return tuple(result) if isinstance(field_list, tuple) else list(result)

    def patch_translation_fields(self, fields):
        """Prevent TranslationAdmin from expanding fields to all configured languages."""
        return self._map_current_lang_fields(fields)

    def get_list_display(self, request):
        fields = getattr(self, '_orig_list_display', None) or getattr(self, 'list_display', ())
        return self._map_current_lang_fields(fields)

    def get_list_editable(self, request):
        fields = getattr(self, '_orig_list_editable', None) or getattr(self, 'list_editable', ())
        return self._map_current_lang_fields(fields)

    def get_changelist_instance(self, request):
        cl = super().get_changelist_instance(request)
        cl.list_display = self._map_current_lang_fields(cl.list_display)
        if hasattr(cl, 'list_editable'):
            cl.list_editable = self._map_current_lang_fields(cl.list_editable)
        return cl

    def ajax_config_view(self, request):
        fields = getattr(self, 'ajax_shift_fields', [])
        mapped = self._map_current_lang_fields(fields)
        return JsonResponse({'ajax_shift_fields': list(mapped)})


class ProxyHistoryAdminMixin:
    """Ensures proxy models delegate history tracking to their concrete model."""

    def __init__(self, model, admin_site):
        if getattr(model._meta, "proxy", False):
            concrete_meta = model._meta.concrete_model._meta
            attr_name = getattr(concrete_meta, "simple_history_manager_attribute", "history")
            if not hasattr(model._meta, "simple_history_manager_attribute"):
                setattr(model._meta, "simple_history_manager_attribute", attr_name)
        super().__init__(model, admin_site)


class ModelDisplayMixin:
    MAX_IMAGE_HEIGHT = 400

    @property
    def model_name(self):
        """Exposes the model name to templates (avoids underscore access restriction)."""
        return self._meta.model_name

    def _render_image_with_menu(self, field_name, label, max_height=None):
        image = getattr(self, field_name, None)
        url = image.url if image and hasattr(image, 'url') else ""
        h = max_height or self.MAX_IMAGE_HEIGHT
        thumb_size = (0, min(h, 200))
        thumb_url = get_thumbnail_url(image, size=thumb_size, crop=False) if image else ""
        model_label = f"{self._meta.app_label}.{self._meta.model_name}"
        
        return render_image_markup(url, model_label, self.pk, field_name, h, label, thumb_url=thumb_url)

    def video_download(self):
        video = getattr(self, 'video', None)
        if video:
            return format_html('<a href="{}" download >{}</a>', video.url, _("Download"))
        return _("No Video")
    video_download.short_description = _("Video Download")

    def pic(self):
        return self._render_image_with_menu('image', _("Image"))
    pic.short_description = _("Image")

    def pic_comic(self):
        return self._render_image_with_menu('image_comic', _("Comic Image"))
    pic_comic.short_description = _("Comic Image")
    
    def pic_refine(self):
        return self._render_image_with_menu('image_refine', _("Refined Image"))
    pic_refine.short_description = _("Refined Image")
    
    def pic_first(self):
        return self._render_image_with_menu('image_first', _("First Frame"))
    pic_first.short_description = _("First Frame")
    
    def pic_last(self):
        return self._render_image_with_menu('image_last', _("Last Frame"))
    pic_last.short_description = _("Last Frame")

    def action_pic(self):
        action = getattr(self, 'action', None)
        if action and hasattr(action, 'pic'):
            return action.pic()
        return "-"
    action_pic.short_description = _("Action Image")
    
    def contents_html(self):
        if hasattr(self, 'get_contents') and self.get_contents():
            return format_html('''
        <a class="btn btn-primary" data-toggle="collapse" href="#collapse{}" role="button" aria-expanded="false" aria-controls="collapseExample">
            {}
        </a>
        <div class="collapse" id="collapse{}">
            <div class="card card-body">
                {}
            </div>
        </div>
        {}
        ''', self.id, _("Get Prompt"), self.id, self.get_contents(), self.features() if hasattr(self, 'features') else "")
        return _("No contents")
    contents_html.short_description = _("Contents")
    
    def contents_refine_html(self):
        if hasattr(self, 'get_contents') and hasattr(self, 'PRESET_REFINE') and self.get_contents(generate_self=True, preset=self.PRESET_REFINE):
            return format_html('''
        <a class="btn btn-primary" data-toggle="collapse" href="#collapse{}" role="button" aria-expanded="false" aria-controls="collapseExample">
            {}
        </a>
        <div class="collapse" id="collapse{}">
            <div class="card card-body">
                {}
            </div>
        </div>
        ''', self.id, _("Get Prompt"), self.id, self.get_contents(generate_self=True, preset=self.PRESET_REFINE))
        return _("No contents")
    contents_refine_html.short_description = _("Refined Contents")

    def video_player(self):
        video = getattr(self, 'video', None)
        if video:
            return format_html('''
        <video controls class="rounded-md shadow-sm">
            <source src="{}" type="video/mp4">
        </video>
        ''', video.url)
        return _("No contents")
    video_player.short_description = _("Video Player")
    
    def voice_player(self):
        audio_voice = None
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        default_lang = getattr(settings, 'MODELTRANSLATION_DEFAULT_LANGUAGE', 'en')

        val = getattr(self, f"audio_voice_{lang}", None)
        if val and hasattr(val, 'url') and val.url:
            audio_voice = val
        elif lang == default_lang:
            val = getattr(self, "audio_voice", None)
            if val and hasattr(val, 'url') and val.url:
                audio_voice = val
        elif not hasattr(self, f"audio_voice_{default_lang}"):
            val = getattr(self, "audio_voice", None)
            if val and hasattr(val, 'url') and val.url:
                audio_voice = val

        if audio_voice and hasattr(audio_voice, 'url') and audio_voice.url:
            uid = secrets.token_hex(4)
            audio_id = f"audio_{self.pk}_{uid}"
            return format_html(
                '<div class="flex items-center justify-center">'
                '<audio id="{0}" src="{1}" preload="none" onended="this.nextElementSibling.querySelector(\'span\').textContent=\'play_circle\'"></audio>'
                '<button type="button" class="p-0 border-none bg-transparent cursor-pointer text-primary-600 hover:text-primary-500 transition-all flex items-center justify-center active:scale-95"'
                ' onclick="const a=document.getElementById(\'{0}\'); if(a.paused){{ a.play(); this.querySelector(\'span\').textContent=\'pause_circle\'; }}else{{ a.pause(); this.querySelector(\'span\').textContent=\'play_circle\'; }}">'
                '<span class="material-symbols-outlined text-[32px]">play_circle</span>'
                '</button>'
                '</div>',
                audio_id, audio_voice.url
            )
        return _("No contents")
    voice_player.short_description = _("Play")

class SceneFilterMixin:
    # anything that has a scene foreign key can use this mixin to filter by the user's current scene

    def save_model(self, request, obj, form, change):
        if hasattr(self, 'scene') and obj.scene is None and request.user.story_profile.scene:
            obj.scene = request.user.story_profile.scene
        save_obj = super().save_model(request, obj, form, change)
        return save_obj

    def get_queryset(self, request):
        qs = super().get_queryset(request) #call original queryset method that you are overriding
        if request.user.story_profile.enable_filters:
            if request.user.story_profile.scene:
                return qs.filter(scene=request.user.story_profile.scene)
            return qs.filter(scene__story=request.user.story_profile.get_current_story())
        return qs

class StoryFilterMixin:
    # anything that has a story or scene foreign key can use this mixin to filter by the user's current story/scene
    
    def save_model(self, request, obj, form, change):
        if not change:
            profile = getattr(request.user, 'story_profile', None)
            if profile:
                story = profile.get_current_story()
                if story and hasattr(obj, 'story') and getattr(obj, 'story') is None:
                    obj.story = story
                if profile.scene and hasattr(obj, 'scene') and getattr(obj, 'scene') is None:
                    obj.scene = profile.scene
        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        profile = getattr(request.user, 'story_profile', None)
        if profile:
            if 'story' not in initial:
                story = profile.get_current_story()
                if story:
                    initial['story'] = story.pk
            if 'scene' not in initial and profile.scene:
                initial['scene'] = profile.scene.pk
        return initial

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        profile = getattr(request.user, 'story_profile', None)
        if not profile:
            return qs

        story = profile.get_current_story()
        scene = profile.scene

        if not story and scene:
            story = scene.story

        if not story and not scene:
            return qs

        model_name = self.model._meta.model_name
        if model_name == 'story':
            return qs.filter(pk=story.pk) if story else qs

        field_names = [f.name for f in self.model._meta.get_fields()]
        if 'scene' in field_names:
            if scene:
                return qs.filter(scene=scene)
            if story:
                return qs.filter(scene__story=story)
        elif 'story' in field_names:
            if story:
                return qs.filter(story=story)

        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "voice":
            story = None
            resolver_match = getattr(request, 'resolver_match', None)
            if resolver_match:
                obj_id = resolver_match.kwargs.get('object_id')
                if obj_id:
                    try:
                        obj = self.get_object(request, obj_id)
                        if hasattr(obj, 'scene') and obj.scene:
                            story = obj.scene.story
                        elif hasattr(obj, 'story') and obj.story:
                            story = obj.story
                    except Exception:
                        pass
            if not story and hasattr(request.user, 'story_profile'):
                story = request.user.story_profile.get_current_story()
            if story:
                from .models import Voice
                kwargs["queryset"] = Voice.objects.filter(story=story)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class StaffReadOnlyMixin:
    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly_fields.extend(self.staff_readonly_fields)         
        return readonly_fields

class ViewYourOwnMixin:
    def get_queryset(self, request):
        qs = super().get_queryset(request) #call original queryset method that you are overriding
        if not request.user.is_superuser:
            return qs.filter(user=request.user)
        return qs

class EmailSenderMixin: 
    
    def send_email(self, subject,  context, recipient_list):
        html_message = render_to_string(self.email_template, context)
        plain_message = strip_tags(html_message)
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            recipient_list,
            html_message=html_message
        )

class UserCreatorMixin:
    
    def create_user(self, obj, email):
        username = email.split('@')[0]
        # 1. Generate a secure random string
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for i in range(12))
        user, created = User.objects.get_or_create(username=username, email=email)
        user.set_password(password)
        user.is_staff = True
        group = Group.objects.get(name='faf')
        user.groups.add(group)
        user.save()
        # Render HTML and create plain text alternative
        html_message = render_to_string(
            'email/invitation.html', 
            {'user': user, 
                'obj': obj,
                'password': password, 
                'cta': settings.SITE_URL + f'/admin/scene/story/?id__exact={obj.id}'
            }
        )
        plain_message = strip_tags(html_message)
        send_mail(
            f'Invitation to co-author: {obj.name}', plain_message, settings.DEFAULT_FROM_EMAIL, [email],
            html_message=html_message # <--- HTML added here
        )
        return user

class PromptPreviewMixin:
    """Mixin to provide an endpoint for previewing prompts based on presets."""
    def get_urls(self):
        return [
            path(
                'prompt-preview/<int:object_id>/',
                self.admin_site.admin_view(self.prompt_preview_view),
                name='prompt_preview',
            ),
        ] + super().get_urls()

    def prompt_preview_view(self, request, object_id):
        obj = get_object_or_404(self.model, pk=object_id)
        preset = request.GET.get('preset') or None
        contents = obj.get_contents(preset=preset)
        
        if isinstance(contents, list):
            # Join string parts with double newlines for readability
            text = "\n\n".join([str(p) for p in contents if isinstance(p, (str, bytes))])
        elif isinstance(contents, dict):
            text = contents.get('prompt', '')
        else:
            text = str(contents)

        return JsonResponse({"content": text})

class AdminActionsMixin:
    @action(description=_("Add to comic video"), icon="playlist_add")
    def comic_to_video(self, request, queryset):
        Render = apps.get_model('scene', 'Render')
        RenderItem = apps.get_model('scene', 'RenderItem')
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            render = Render.get_from_scene(obj.scene, language=lang)
            comic_img = getattr(obj, f"image_comic_{lang}", None) or obj.image_comic or obj.image
            RenderItem.objects.create(
                image=comic_img,
                render=render,
                order=obj.order,
            )

    @action(description=_("Add to scene video"), icon="playlist_add")
    def video_to_scene_video(self, request, queryset):
        Render = apps.get_model('scene', 'Render')
        RenderItem = apps.get_model('scene', 'RenderItem')
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            render = Render.get_from_scene(obj.scene, language=lang)
            RenderItem.objects.create(
                video=obj.video,
                render=render,
                order=obj.order,
            )

    @action(description=_("Clone selected items"), icon="content_copy")
    def clone(self, request, queryset):
        for obj in queryset:
            props = None
            cast = None
            if hasattr(obj, 'props'):
                props = list(obj.props.all())
            if hasattr(obj, 'cast'):
                cast = list(obj.cast.all())
            obj.pk = None
            if hasattr(obj, 'name') and obj.name:
                obj.name = f"{obj.name} (Clone)"
            if hasattr(obj, 'order'):
                obj.order = obj.order + 1
            obj.save()
            if props is not None:
                obj.props.set(props)
            if cast is not None:
                obj.cast.set(cast)
        self.message_user(request, "Selected items have been cloned.")

    @action(description=_("Generate image"), icon="image")
    def default_generate_image(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_IMAGE, owner=request.user) is None:
                obj.generate_image(user=request.user)
            self.message_user(request, "Image generated for item ID {}.".format(obj.id))

    @action(description=_("Refine image"), icon="auto_fix_high")
    def default_refine_image(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_REFINE_IMAGE, owner=request.user) is None:
                obj.refine_image(user=request.user) 
            self.message_user(request, "Image generated for item ID {}.".format(obj.id))

    @action(description=_("Refined as image"), icon="check_circle")
    def accept_refined_image(self, request, queryset):
        for obj in queryset:
            obj.image=obj.image_refine
            obj.save()
            self.message_user(request, "image accepted for item ID {}.".format(obj.id))

    @action(description=_("Refined as first frame"), icon="first_page")
    def accept_refined_first(self, request, queryset):
        for obj in queryset:
            obj.image_first=obj.image_refine
            obj.save()
            self.message_user(request, "image accepted for item ID {}.".format(obj.id))

    @action(description=_("Refined as last frame"), icon="last_page")
    def accept_refined_last(self, request, queryset):
        for obj in queryset:
            obj.image_last=obj.image_refine
            obj.save()
            self.message_user(request, "image accepted for item ID {}.".format(obj.id))

    @action(description=_("Video from image"), icon="videocam")
    def generate_video(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_VIDEO, owner=request.user) is None:
                obj.generate_video(obj.PRESET_VIDEO, user=request.user)
            self.message_user(request, "video generated for item ID {}.".format(obj.id))

    @action(description=_("Comic from image"), icon="auto_awesome")
    def generate_comic(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_COMIC, owner=request.user) is None:
                obj.generate_comic(user=request.user)
            self.message_user(request, "comic generated for item ID {}.".format(obj.id))

    @action(description=_("Video from first to last"), icon="movie")
    def generate_video_first_last(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_VIDEO_FIRST_LAST, owner=request.user) is None:
                obj.generate_video(obj.PRESET_VIDEO_FIRST_LAST, user=request.user)
            self.message_user(request, "video generated for item ID {}.".format(obj.id))

    @action(description=_("Omni Video"), icon="video_camera_front")
    def generate_omni_video(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_OMNI_VIDEO, owner=request.user) is None:
                obj.generate_omni_video(obj.PRESET_OMNI_VIDEO, user=request.user)
            self.message_user(request, "omni video generated for item ID {}.".format(obj.id))

    @action(description=_("Flow Video"), icon="videocam")
    def generate_flow_video(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_FLOW, owner=request.user) is None:
                obj.generate_flow_video(obj.PRESET_FLOW_VIDEO, user=request.user)
            self.message_user(request, "flow video generated for item ID {}.".format(obj.id))

    @action(description=_("Generate Voice"), icon="record_voice_over")
    def generate_voice(self, request, queryset):
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_GENERATE_VOICE, owner=request.user, payload={'target_language': lang}) is None:
                obj.generate_voice(obj.PRESET_VOICE, user=request.user)
            self.message_user(request, "voice generated for item ID {}.".format(obj.id))

    @action(description=_("Generate Prompt"), icon="edit_note")
    def generate_scene_prompt(self, request, queryset):
        for obj in queryset:
            if hasattr(obj, 'task_from_action') and hasattr(obj, 'ACTION_CREATE_PROMPT'):
                if obj.task_from_action(obj.ACTION_CREATE_PROMPT, request.user) is None:
                    obj.generate_text(preset=getattr(obj, 'PRESET_CREATE_PROMPT', 'scene_create_prompt'), user=request.user)
            self.message_user(request, "Generation task for prompt started for scene: {}.".format(obj.name))

    @action(description=_("Generate Elements"), icon="interests")
    def generate_scene_elements(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_SCENE_ELEMENTS, owner=request.user) is None:
                pass
            model_label = obj._meta.verbose_name
            self.message_user(request, "Generation task for elements started for {}: {}.".format(model_label, obj.name))

    @action(description=_("Generate Shots"), icon="play_arrow")
    def generate_scene_actions(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_SCENE_ACTIONS, owner=request.user) is None:
                pass
            self.message_user(request, "Generation task for actions started for scene: {}.".format(obj.name))

    @action(description=_("Generate Voices"), icon="record_voice_over")
    def generate_scene_voices(self, request, queryset):
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_SCENE_VOICES, owner=request.user, payload={'target_language': lang}) is None:
                # This block would run if queuing is disabled.
                # You could add direct execution here if needed.
                pass
            self.message_user(request, "Generation task for voices started for scene: {}.".format(obj.name))

    @action(description=_("Generate Comics"), icon="auto_awesome")
    def generate_scene_comics(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_SCENE_COMICS, owner=request.user) is None:
                pass
            self.message_user(request, "Generation task for comics started for scene: {}.".format(obj.name))

    @action(description=_("Add me as author"), icon="person_add")
    def add_me_as_author(self, request, queryset):
        for obj in queryset:
            if obj.add_author(request.user):
                self.message_user(request, f"You have been added as an author to story {obj.name}")

    @action(description=_("Sync Structure"), icon="sync")
    def extract_scene(self, request, queryset):
        for obj in queryset:
            if Task.createTaskIfQueueEnabled( obj, settings.TASK_TYPE_EXTRACT_SCENE, owner=request.user) is None:
                obj.generate_scene(user=request.user)
            self.message_user(request, f"Extracting scene from contribution {obj.id} in story {obj.story.id}.")

    @action(description=_("Generate Render Preview (step 3.5)"), icon="preview")
    def generate_render(self, request, queryset):
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            if hasattr(obj, 'generate_render'):
                obj.generate_render(language=lang)
                self.message_user(request, _("Render generated for : {}").format(obj.name))

    @action(description=_("Refresh Render (step 4)"), icon="refresh")
    def refresh_render(self, request, queryset):
        lang = (get_language() or 'en').replace('-', '_').split('_')[0]
        for obj in queryset:
            render = obj.generate_render(language=lang)
            Task.createTaskIfQueueEnabled(
                subject=render,
                task_type=settings.TASK_TYPE_VIDEO_RENDER,
                thr=obj,
                owner=request.user,
                payload={'target_language': lang}
            )
            self.message_user(request, _("Render generated and video task queued for: {}").format(obj.name))

class RenderTypeMixin:
    RENDER_TYPE_FILM = 'film'
    RENDER_TYPE_GRAPHIC_NOVEL = 'comic'
    RENDER_TYPE_ANIMATIC = 'animatic'

    RENDER_TYPE_CHOICES = [
        (RENDER_TYPE_FILM, 'Film'),
        (RENDER_TYPE_GRAPHIC_NOVEL, 'Graphic Novel'),
        (RENDER_TYPE_ANIMATIC, 'Animatic'),
    ]
    def __getattr__(self, name):
        if name == "is_comic":
            return getattr(self, "render_type", None) == getattr(self, "RENDER_TYPE_GRAPHIC_NOVEL", "comic")
        if name == "is_film":
            return getattr(self, "render_type", None) == getattr(self, "RENDER_TYPE_FILM", "film")
        if name == "is_animatic":
            return getattr(self, "render_type", None) == getattr(self, "RENDER_TYPE_ANIMATIC", "animatic")
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


class YAMLAssetsMixin:
    def get_elements_as_yaml(self):
        """
        Serializes the model's main elements (locations, characters, props, voices)
        into a YAML formatted string.
        """
        locations = [BackgroundSchema(name=b.name, prompt=b.prompt) for b in self.get_locations()]
        characters = [CharacterSchema(name=c.name, prompt=c.prompt) for c in self.get_cast()]
        props = [PropSchema(name=p.name, prompt=p.prompt) for p in self.get_props()]
        voices = [
            VoiceSchema(
                name=v.name,
                prompt=v.prompt,
                google_voice=v.google_voice.name if v.google_voice else None
            ) for v in self.get_voices()
        ]

        elements_data = AssetsSchema(
            locations=locations,
            characters=characters,
            props=props,
            voices=voices,
        ).model_dump()

        filtered_data = {k: v for k, v in elements_data.items() if v}
        if not filtered_data:
            return None

        context_key = f"{self._meta.model_name}_context"
        return yaml.dump({context_key: filtered_data}, indent=2, default_flow_style=False)

class ChangelistScrollToEditedMixin:
    """
    Mixin that appends the `#id={obj.id}` anchor hash to the redirect URL 
    after adding or changing an object, so the changelist can scroll back 
    to the edited row.
    """
    def response_add(self, request, obj, post_url_continue=None):
        res = super().response_add(request, obj, post_url_continue)
        if res.status_code in [301, 302] and '_continue' not in request.POST and '_addanother' not in request.POST:
            res['Location'] = f"{res['Location']}#id={obj.id}"
        return res

    def response_change(self, request, obj):
        res = super().response_change(request, obj)
        if res.status_code in [301, 302] and '_continue' not in request.POST and '_addanother' not in request.POST:
            res['Location'] = f"{res['Location']}#id={obj.id}"
        return res
