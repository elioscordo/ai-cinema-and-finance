import io
import os
import zipfile

from django.contrib import admin
from httpcore import request
from unfold.admin import ModelAdmin
from django.urls import path
from django.urls import path, reverse
from django import forms
from django.utils.translation import gettext_lazy as _, get_language
from agent.widgets import DynamicMarkdownWidget as MarkdownWidget
from agent.sections import MessageHistorySection, PromptFormSection
from simple_history.admin import SimpleHistoryAdmin
from agent.sections import AjaxSectionAdminMixin, MessageHistorySection
from django.conf import settings
from task.models import Task
from unfold.admin import StackedInline
try:
    from modeltranslation.admin import TabbedTranslationAdmin, TranslationAdmin
except ImportError:
    class TabbedTranslationAdmin:
        pass
    class TranslationAdmin:
        pass

from .models import ActionOrganizer, Character, Scene, Preset, Action, Background, SceneOrganizer, StoryGroup, Style, Prop, ComicAction, RenderItem, VideoAction, Render, Story, StoryProfile, Voice, VoiceAction, Author, Nudge, ContactRequest, WorkShop, Sync, SyncItem
from .admin_utils import AdminLinker
from agent.admin_utils import AjaxTaskModelAdmin, ModelActionsAdminMixin
from agent.utils import normalize_target_field
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from agent.models import Message
from .sections import AuthorSection, ElementSection, SceneSection, SceneCharactersSection, SceneLocationsSection, ScenePropsSection, RenderSection, MarkDownSection, ScriptSection
from .mixins import ACTION_FIELDSETS, ELEMENT_FIELDSETS, SceneFilterMixin, StaffReadOnlyMixin, StoryFilterMixin, ViewYourOwnMixin, PromptPreviewMixin, AdminActionsMixin, ChangelistScrollToEditedMixin, CurrentLanguageListMixin, ProxyHistoryAdminMixin
from unfold.sections import TableSection, TemplateSection, render_to_string
from rangefilter.filters import NumericRangeFilter
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify 
DEFAULT_IMAGE_AGENT_NAME = "DIGA"
from django.apps import apps 
from agent.models import Prompt
from django.utils.safestring import mark_safe
import markdown
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.decorators import action

class PromptMarkdownMixin:
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        is_changelist = False
        if request and getattr(request, 'resolver_match', None):
            url_name = getattr(request.resolver_match, 'url_name', '') or ''
            if url_name.endswith('_changelist'):
                is_changelist = True
        if not is_changelist and (db_field.name == 'prompt' or db_field.name.startswith('prompt_') ):
            kwargs['widget'] = MarkdownWidget()
        return super().formfield_for_dbfield(db_field, request, **kwargs)
        

class PromptPreviewSection(TemplateSection):
    """Section that renders a dropdown to preview model prompts."""
    template_name = "sections/prompt_preview.html"

    def get_context_data(self, request, instance):
        presets = []
        # Automatically discover constants starting with PRESET_ on the model
        for attr in dir(instance):
            if attr.startswith("PRESET_"):
                val = getattr(instance, attr)
                # Don't add if it's a method/callable
                if not callable(val):
                    label = attr.replace("PRESET_", "").replace("_", " ").title()
                    presets.append({"value": val, "label": label})
        
        return {
            "presets": sorted(presets, key=lambda x: x['label']),
            "instance": instance,
            "request": request,
        }

@admin.register(Style)
class StyleAdmin(PromptMarkdownMixin, AdminActionsMixin, ModelAdmin):
    list_display = ('id','name', 'prompt')
    list_editable = ('name', 'prompt')
    list_display_links = ('id',)
    actions = ['clone']
    search_fields = ['name']


class AuthorInline(StackedInline):
    model = Author 
    show_count = True  # This will run `count()`
    collapsible = True
    autocomplete_fields = ['user']

class PlotSection(MarkDownSection):
    field_name = "prompt_plot"
    title = "Plot"
    key = "plot"
    
class DraftSection(MarkDownSection):
    field_name = "prompt_draft"
    title = "Draft"
    key = "draft"   

@admin.register(Story)
class StoryAdmin(ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, StoryFilterMixin, AdminActionsMixin, AdminLinker, AjaxTaskModelAdmin):
    inlines = [AuthorInline]
    autocomplete_fields = ['group']
    search_fields = ['name']
    list_refresh = ['items']
    list_sections = [
        MessageHistorySection,
        MarkDownSection,
        ElementSection,
        AuthorSection,
        SceneLocationsSection,
        SceneCharactersSection, 
        ScenePropsSection,
        RenderSection,
        PromptFormSection
    ]
    list_display = ['__str__', 'items', 'scenes_dropdown', 'add_scene', 'last_tasks']
    actions = ['clone', 'add_me_as_author', 'generate_scene_elements','generate_render', 'refresh_render']

    fieldsets = (
        ("Write",{
            "classes": ["tab"],
            "fields": ["name", "prompt"],
        }),
        ("Refine",{
            "classes": ["tab"],
            "fields": ["prompt_refine", "prompt_translations", 'action'],
        }),
        ("Settings", {
            "classes": ["tab"],
            "fields": [ "style", "theme", "group", "render_type", "config"],
        })
    )

    def changelist_view(self, request, extra_context=None):
        self.request = request
        if request.user.is_authenticated:
            self._user_author_map = dict(
                Author.objects.filter(user=request.user).values_list('story_id', 'id')
            )
        return super().changelist_view(request, extra_context)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('style', 'theme', 'group').prefetch_related('scenes')

    def add_scene(self, obj):
        author_id = getattr(self, '_user_author_map', {}).get(obj.id)
        if author_id is None and hasattr(self, 'request'):
            author = Author.objects.filter(user=self.request.user, story=obj).first()
            author_id = author.id if author else False
            if not hasattr(self, '_user_author_map'):
                self._user_author_map = {}
            self._user_author_map[obj.id] = author_id

        if author_id:
            url = reverse("admin:scene_scene_add")
            return format_html(
                '<a href="{}?story={}&author={}&next=/admin/scene/story/" class="bg-primary-600 text-white px-3 py-1.5 rounded-md text-xs font-semibold hover:bg-primary-500 transition-colors shadow-sm inline-flex items-center gap-1.5 whitespace-nowrap" style="color: white !important;">'
                '<span class="material-symbols-outlined text-[18px]">add</span>{}</a>',
                url, obj.id, author_id, _("Add Scene")
            )
        return "-"
    add_scene.short_description = _("Add Scene")

    def scenes_dropdown(self, obj):
        scenes = obj.scenes.all().order_by('order')
        return render_to_string("story/scenes_dropdown.html", {
            "instance": obj,
            "scenes": scenes,
        })
    scenes_dropdown.short_description = _("Scenes")

    def scene_links(self, obj):
        return format_html("<a href='/admin/scene/Scene/?story__id__exact={0}'>Edit ({1})</a>", obj.id, obj.scenes.count())
    scene_links.short_description = "Scenes"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and request.user.is_authenticated:
            if obj.add_author(request.user):
                self.message_user(request, f"You have been added as an author to story {obj.name}")


@admin.register(Scene)
class SceneAdmin(ModelActionsAdminMixin, ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, StoryFilterMixin, AdminActionsMixin, AdminLinker, AjaxTaskModelAdmin):
    show_full_result_count = False
    search_fields = ['name']
    ajax_shift_fields = ['prompt']
    list_refresh = ['items']
    list_display = ['__str__', 'items', 'last_tasks']
    autocomplete_fields = ['story', 'author', 'instructions', 'locations', 'cast', 'props', 'voices']
    actions = ['clone', 'extract_scene', 'generate_scene_prompt', 'generate_scene_elements', 'generate_scene_actions', 'generate_scene_voices', 'generate_scene_comics', 'generate_render', 'refresh_render']
    list_filter = ['story', 'id']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story', 'author')
    
    fieldsets = (
        ("Write",{
            "classes": ["tab"],
            "fields": [ "prompt_plot", "prompt", "prompt_elements", "instructions"],
        }),
        ("Assets", {
            "classes": ["tab"],
            "fields": ["locations", "cast", "props", "voices"],
        }),
        ("Refine",{
            "classes": ["tab"],
            "fields": ["prompt_refine", "prompt_translations", 'action'],
        }),
        ("Settings", {
            "classes": ["tab"],
            "fields": ["name", "author", "story"],
        })
    )
    list_sections = [
        MessageHistorySection,
        PlotSection,
        ScriptSection,
        RenderSection
    ]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "instructions":
            # Only show prompts that are not marked as global in the autocomplete
            kwargs["queryset"] = Prompt.objects.filter(is_global=False)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


    def save_model(self, request, obj, form, change):
        if not obj.author and obj.story:
            author = Author.objects.filter(user=request.user, story=obj.story).first()
            if author:
                obj.author = author
        super().save_model(request, obj, form, change)

    def trigger_ajax_task(self, request, obj, target_field):
        field_name = normalize_target_field(target_field)
        if field_name == 'prompt':
            # When the main prompt is saved via AJAX, do nothing.
            pass
        elif field_name == 'prompt_refine':
            agent = obj.story.get_mentor()
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_TEXT, thr=agent, owner=request.user) is None:
                obj.generate_text(request.user, agent)
        else:
            super().trigger_ajax_task(request, obj, target_field)



@admin.register(StoryGroup)
class StoryGroupAdmin(ModelAdmin):
    list_display = ('id', 'name', 'story')
    list_editable = ('name', 'story')
    list_display_links = ('id',)
    autocomplete_fields = ['story', 'users']
    search_fields = ['name']

@admin.register(StoryProfile)
class StoryProfileAdmin(ViewYourOwnMixin, StaffReadOnlyMixin, ModelAdmin):
    list_display = ('id', 'user','group', 'story', 'scene' )
    list_display_links = ('id',)
    autocomplete_fields = ['story', 'group', 'user', 'scene']
    staff_readonly_fields = ['user']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'group', 'story', 'scene')

@admin.register(Character)
class CharacterAdmin(ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, StoryFilterMixin, AdminActionsMixin, AdminLinker, PromptPreviewMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'pic', 'prompt', 'prompt_refine', 'link_story', 'last_tasks')
    list_refresh = ['pic']
    list_editable = ('prompt', 'prompt_refine')
    list_display_links = ('name',)
    autocomplete_fields = ['story']
    list_filter = ['story', 'scenes', 'id']
    actions = ['clone', 'default_generate_image', 'default_refine_image']
    search_fields = ['name']
    fieldsets = ELEMENT_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story', 'image')

@admin.register(Background)
class BackgroundAdmin(ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, StoryFilterMixin, AdminActionsMixin, AdminLinker, PromptPreviewMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'pic', 'prompt', 'prompt_refine', 'link_story', 'last_tasks')
    list_refresh = ['pic']
    list_editable = ('prompt', 'prompt_refine')
    list_display_links = ('name',)
    autocomplete_fields = ['story']
    list_filter = ['story', 'scenes', 'id']
    actions = ['clone', 'default_generate_image', 'default_refine_image']
    search_fields = ['name']
    fieldsets = ELEMENT_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story', 'image')


@admin.register(Prop)
class PropAdmin(ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, StoryFilterMixin, AdminActionsMixin, AdminLinker, PromptPreviewMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    search_fields = ['name']#
    list_refresh = ['pic']
    list_display = ('name', 'pic', 'prompt','prompt_refine', 'link_story', 'last_tasks')
    list_display_links = ('name',)
    list_editable = ('prompt','prompt_refine')
    autocomplete_fields = ['story']
    list_filter = ['story', 'scenes', 'id']
    actions = ['clone', 'default_generate_image', 'default_refine_image']
    search_fields = ['name']
    fieldsets = ELEMENT_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story', 'image')


@admin.register(Author)
class AuthorAdmin(AdminActionsMixin, ModelAdmin):
    list_display = ['user', 'email', 'story', 'scene_count']
    list_editable = ['story']
    list_display_links = ('user',)
    autocomplete_fields = ['user', 'story']
    search_fields = ['user__username', 'email']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'story')

@admin.register(Nudge)
class NudgeAdmin(AdminActionsMixin, ModelAdmin):
    list_display = ["id", 'sender', 'receiver', 'story', 'message']
    fieldsets = (
        ("Write",{
            "classes": ["tab"],
            "fields": ["message", ],
        }),
        ("Settings", {
            "classes": ["tab"],
            "fields": ["receiver", "sender", "story"],
        })
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sender', 'receiver', 'story')

@admin.register(Action)
class ActionAdmin(CurrentLanguageListMixin, TabbedTranslationAdmin, ChangelistScrollToEditedMixin, PromptMarkdownMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AdminActionsMixin, PromptPreviewMixin, StoryFilterMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    ajax_shift_fields = ['prompt', 'prompt_refine']    
    list_display = ('get_name', 'items', 'pic', 'prompt','prompt_refine', 'last_tasks')
    list_refresh = ['pic']
    list_editable = ( 'prompt', 'prompt_refine')
    list_filter = ["scene__story", "scene", "order", "id"]
    ordering_field = "order"
    hide_ordering_field = True
    list_display_links = ('get_name',)
    autocomplete_fields = ['actor', 'props', 'cast', 'background', 'consistent_with', 'scene', 'voice']
    search_fields = ['get_name']
    actions = ['clone', 'default_generate_image', 'default_refine_image']
    fieldsets = ACTION_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'scene', 'scene__story', 'voice', 'background', 'actor',
            'image', 'image_comic', 'audio_voice', 'video', 'consistent_with'
        )

# Ensure proxy models delegate history tracking to concrete model Action
for _proxy_cls in (VoiceAction, ComicAction, VideoAction):
    if _proxy_cls._meta.proxy and hasattr(Action._meta, "simple_history_manager_attribute"):
        if not hasattr(_proxy_cls._meta, "simple_history_manager_attribute"):
            _proxy_cls._meta.simple_history_manager_attribute = Action._meta.simple_history_manager_attribute


@admin.register(VideoAction)
class VideoActionAdmin(CurrentLanguageListMixin, ProxyHistoryAdminMixin, SimpleHistoryAdmin, PromptMarkdownMixin, AjaxSectionAdminMixin, AdminActionsMixin, PromptPreviewMixin, StoryFilterMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'items', 'pic', 'prompt_video', 'video_player','last_tasks')
    list_editable = ['prompt_video']
    list_filter = ["scene__story", "scene", "id"]
    list_display_links = ('name',)
    list_refresh = ['video_player']
    search_fields = ['name']
    actions = ['generate_video', 'generate_video_first_last', 'generate_omni_video']
    fieldsets = ACTION_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'scene', 'scene__story', 'video', 'image', 'image_first', 'image_last'
        )


@admin.register(ComicAction)
class ComicActionAdmin(CurrentLanguageListMixin, TabbedTranslationAdmin, ProxyHistoryAdminMixin, SimpleHistoryAdmin, PromptMarkdownMixin, AjaxSectionAdminMixin, AdminActionsMixin, PromptPreviewMixin, StoryFilterMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    ajax_shift_fields = ['prompt_comic']
    list_display = ('name', 'items', 'pic', 'pic_comic', 'prompt_comic', 'last_tasks')
    list_editable = ['prompt_comic']
    list_filter = ["scene__story", "scene", "id"]
    list_refresh = ['pic_comic']
    list_display_links = ('name',)
    search_fields = ['name']
    actions = ['generate_comic', 'comic_to_video']
    fieldsets = ACTION_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'scene', 'scene__story', 'image_comic', 'image'
        )


@admin.register(VoiceAction)
class VoiceActionAdmin(CurrentLanguageListMixin, TabbedTranslationAdmin, ProxyHistoryAdminMixin, SimpleHistoryAdmin, PromptMarkdownMixin, AjaxSectionAdminMixin, AdminActionsMixin, PromptPreviewMixin, StoryFilterMixin, AjaxTaskModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'items', 'pic', 'prompt_voice', 'voice', 'voice_player', 'last_tasks')
    list_editable = ['prompt_voice', 'voice']
    list_filter = ["scene__story", "scene", "id"]
    list_display_links = ('name',)
    autocomplete_fields = ['actor', 'props', 'cast', 'background', 'consistent_with', 'scene', 'voice']
    list_refresh = ['voice_player']
    search_fields = ['name']
    actions = ['generate_voice']
    fieldsets = ACTION_FIELDSETS
    list_sections = [MessageHistorySection]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'scene', 'scene__story', 'voice', 'audio_voice', 'image'
        )

    def audio_voice(self, obj):
        return obj.voice_player()
    audio_voice.short_description = _("Audio Player")


@admin.register(ActionOrganizer)
class ActionOrganizerAdmin(CurrentLanguageListMixin, AjaxSectionAdminMixin, AdminActionsMixin, PromptPreviewMixin, StoryFilterMixin, ModelAdmin):
    show_full_result_count = False
    list_display = ('id', 'name', 'items', 'pic', 'scene', 'is_intro', 'order')
    list_editable = ['name', 'scene', 'is_intro', 'order']
    list_filter = ["scene__story", "scene"]
    search_fields = ['name']
    fieldsets = ACTION_FIELDSETS

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('scene', 'scene__story', 'image')

@admin.register(SceneOrganizer)
class SceneOrganizerAdmin(AjaxSectionAdminMixin, AdminActionsMixin, AdminLinker, StoryFilterMixin, ModelAdmin):
    list_display = ('id', 'name', 'image_intro', 'link_actions', 'story')
    list_editable = ['name',  'story']
    list_filter = ["story"]
    search_fields = ['name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story')


@admin.register(Voice)
class VoiceAdmin(PromptMarkdownMixin, SimpleHistoryAdmin, StoryFilterMixin, AdminActionsMixin, AdminLinker, AjaxTaskModelAdmin):
    list_display = ('__str__', 'prompt', 'google_voice', 'sample_text', 'link_story' , 'voice_player', 'last_tasks')
    list_editable = ['prompt']
    list_refresh = ['voice_player']    
    
    actions = ['generate_voice']
    list_filter = (
        'story',
        'scenes',
        'global_default'
    )
    search_fields= ['name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story', 'google_voice', 'audio_voice')
    
    def trigger_ajax_task(self, request, obj, target_field):
        field_name = normalize_target_field(target_field)
        if field_name in ['prompt', 'sample_text']:
            lang = (get_language() or 'en').replace('-', '_').split('_')[0]
            if Task.createTaskIfQueueEnabled(obj, settings.TASK_TYPE_GENERATE_VOICE, owner=request.user, payload={'target_language': lang}) is None:
                obj.generate_voice(obj.PRESET_VOICE, user=request.user)


@admin.register(RenderItem)
class RenderItemAdmin(ModelAdmin):
    list_display = ('id', 'video_player', 'pic', 'params', 'config', 'order', 'render')
    list_editable = ('order', 'params', 'config')
    list_filter = ('render',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('render', 'render__scene')

@admin.register(Render)
class RenderAdmin(AjaxSectionAdminMixin, AdminActionsMixin, ModelAdmin):
    show_full_result_count = False
    list_display = ('name', 'scene', 'render_type', 'language', 'created_at', 'render_items_link', 'video_player', 'video_download', 'last_tasks')
    list_filter = ('render_type', 'language', 'scene__story')
    list_display_links = ('name',)
    actions = ['refresh_scene_video']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('scene', 'scene__story')

    def render_items_link(self, obj):
        count = obj.render_items.count()
        url = reverse("admin:scene_renderitem_changelist") + f"?render__id__exact={obj.id}"
        return format_html(
            '<a href="{}" class="text-primary-600 font-medium hover:underline">Items ({})</a>',
            url, count
        )
    render_items_link.short_description = _("Render Items")

    @admin.action(description=_("Refresh Video Render"))
    def refresh_scene_video(self, request, queryset):
        for render in queryset:
            render.refresh_render()
            Task.createTaskIfQueueEnabled(
                subject=render,
                task_type=settings.TASK_TYPE_VIDEO_RENDER,
                thr=render.scene or render.story,
                owner=request.user
            )
            self.message_user(request, _("Video task queued for render: {}").format(render.name))


@admin.register(ContactRequest)
class ContactRequestAdmin(PromptMarkdownMixin, ModelAdmin):
    pass

@admin.register(WorkShop)
class WorkShopAdmin(ModelAdmin):
    pass

@admin.register(Preset)
class PresetAdmin(ModelAdmin):
    pass

@admin.register(Sync)
class SyncAdmin(ModelAdmin):
    list_display = ('story', 'last_file_in', 'last_file_out')
    autocomplete_fields = ['story']
    search_fields = ['story__name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('story')

@admin.register(SyncItem)
class SyncItemAdmin(AjaxSectionAdminMixin, AjaxTaskModelAdmin):
    list_display = ('id', 'sync', 'type', 'zip_file', 'last_tasks')
    list_filter = ('type', 'sync__story')
    autocomplete_fields = ['sync']
    actions = ['trigger_sync']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sync', 'sync__story')

    @admin.action(description=_("Trigger Sync Task"))
    def trigger_sync(self, request, queryset):
        for obj in queryset:
            task_type = settings.TASK_TYPE_SYNC_EXPORT if obj.type == obj.TYPE_EXPORT else settings.TASK_TYPE_SYNC_IMPORT
            Task.createTaskIfQueueEnabled(obj, task_type, owner=request.user)