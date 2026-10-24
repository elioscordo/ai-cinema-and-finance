from django.contrib import admin
from .models import Language, Task, Audio, \
    Text, Category, Tutorial, TutorialAudio, TutorialText, \
    TaskPreset, Playlist, Speaker, AudioAnalysis

from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string

from import_export import resources
from import_export.admin import ImportExportModelAdmin


class PlaylistLinksMixin:
    def playlist_links(self, obj):
        items = obj.playlists.all()
        out = render_to_string(
            'is_core/playlist/links.html',
            {'items': items}
        )
        return format_html(out)


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    pass


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    pass


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['text']


class TextResource(resources.ModelResource):
    class Meta:
        model = Text
        import_id_fields = ('text',)
        fields = ('text', 'language')


@admin.register(Text)
class TextAdmin(ImportExportModelAdmin, PlaylistLinksMixin):
    actions = ['speak', 'create_tutorial', 'clone_object']
    resource_class = TextResource
    list_filter = ['language']
    search_fields = ['text']
    list_display = ('id', 'text', 'language', 'tutorial_count',
                    'audio_count', 'last_tasks',
                    'playlist_links'
                    )
    list_editable = ('text', 'language')

    autocomplete_fields = ['categories']

    def last_tasks(self, obj):
        out = '--'
        tasks = obj.tasks()
        if tasks.count() > 0:
            out = render_to_string(
                'is_core/tasks/dropdown.html',
                {'tasks': tasks}
            )
        return format_html(out)

    @admin.action(description=_("Speak and create tutorial"))
    def create_tutorial(self, request, queryset):
        for item in queryset:
            label = "Tutorial creation has been queue for %(text)s"
            item.speak_and_tutorial(request.user)
            msg = _(label) % {'text': item.text}
            self.message_user(
                request,
                msg
            )

    @admin.action(description=_("Speak"))
    def speak(self, request, queryset):
        for item in queryset:
            item.speak()
            msg = _("Speech synthesis has been queue for %(text)s") % \
                {'text': item.text}
            self.message_user(
                request,
                msg
            )

    @admin.action(description=_("Clone Object"))
    def clone_object(self, request, queryset):
        for item in queryset:
            new = item
            new.text = f'{item.text} cloned'
            item.id = None
            item.save()


class TutorialTextInline(admin.StackedInline):
    model = TutorialText
    autocomplete_fields = ['text']


class TutorialAudioInline(admin.StackedInline):
    model = TutorialAudio
    autocomplete_fields = ['audio']


@admin.register(Tutorial)
class TutorialAdmin(admin.ModelAdmin, PlaylistLinksMixin):
    actions = [
        'join_video',
        'upload_video',
        'create_video_tutorial',
        'update_metadata',
        'add_to_playlist',
        'playlist_item_create'
    ]
    inlines = [TutorialTextInline, TutorialAudioInline]
    autocomplete_fields = ['categories']
    list_display = [
        'id',
        'name',
        'language',
        'video_player',
        'vue_player',
        'title',
        'description',
        'keywords',
        'playlist_links'
    ]
    list_editable = [
        'title',
        'language',
        'description',
        'keywords'
    ]
    list_filter = ['title', 'language']

    def video_player(self, obj):
        out = '--'
        if obj.video:
            out = render_to_string(
                'is_core/video_player.html',
                {'items': [obj.video.url]}
            )
        return format_html(out)

    def vue_player(self, obj):
        out = render_to_string(
            'is_core/js_player.html',
            {'item': obj}
        )
        return format_html(out)
    vue_player.short_description = "Analysis"

    def create_video_tutorial(self, request, queryset):
        for item in queryset:
            Task.createTask(
                item,
                Task.TASK_TYPE_VIDEO_TUTORIAL
            )
            msg = _("Video creation/update of %(text)s has been queued") % {
                'text': item.name
            }
            self.message_user(
                request,
                msg
            )
    create_video_tutorial.short_description = "Create / Update video tutorial"

    def update_metadata(self, request, queryset):
        for item in queryset:
            item.updateVideoMeta()
            msg = _("Video metadata of %(text)s has been created/updated") % {
                'text': item.name
            }
            self.message_user(
                request,
                msg
            )
    update_metadata.short_description = "Create/Update video metadata"

    def upload_video(self, request, queryset):
        for item in queryset:
            Task.createTask(
                item,
                Task.TASK_TYPE_UPLOAD
            )
            msg = _("Video upload for %(text)s has been queued") % {
                'text': item.name
            }
            self.message_user(
                request,
                msg
            )
    upload_video.short_description = "Upload video to YouTube"

    def playlist_item_create(self, request, queryset):
        for item in queryset:
            Task.createTask(
                item,
                Task.TASK_TYPE_PLAYLIST_ITEM_CREATE
            )
            msg = _("YouTube playlist item creation \
                    for %(text)s has been queued"
                    ) % {
                            'text': item.name
                        }
            self.message_user(
                request,
                msg
            )
    playlist_item_create.short_description = "Add to YouTube playlist"

    def add_to_playlist(self, request, queryset):
        for item in queryset:
            msg = _("No language defined for %(t)s") % {'t': item.name}
            if item.language:
                p = Playlist.get_target(item.language, request.user)
                if p:
                    item.playlists.add(p)
                    msg = _("%(t)s has been added to %(p)s") % {
                        't': item.name, 'p': p.name
                    }
                else:
                    msg = _("No target playlist for %(l)s") % {
                        'l': item.language
                    }
            self.message_user(
                request,
                msg
            )

    add_to_playlist.short_description = "Add to target YouTube playlist"


@admin.register(AudioAnalysis)
class AudioAnalysisAdmin(admin.ModelAdmin):
    pass


@admin.register(Audio)
class AudioAdmin(admin.ModelAdmin):
    actions = [
        'do_analysis',
        'do_tutorial',
    ]
    list_display = [
        'name',
        'order',
        'speaker',
        'rate',
        'audio_player',
        'video_player'
    ]
    list_filter = ['text', 'language']
    search_fields = ['name']
    list_editable = ['order']

    def audio_player(self, obj):
        return format_html(
            f'<audio src="{obj.file.url}" controls="true"></audio>'
        )

    def video_player(self, obj):
        out = 'no analysis found'
        if obj.analysis and obj.analysis.video:
            out = render_to_string(
                'is_core/video_player.html',
                {'items': [obj.analysis.video.url]}
            )
        return format_html(out)

    def do_analysis(self, request, queryset):
        for item in queryset:
            Task.createTask(
                item,
                Task.TASK_TYPE_ANALYSIS
            )
            msg = _("Audio anlysis for %(text)s has been queued")
            self.message_user(
                request,
                msg
            )
    do_analysis.short_description = "Refresh analysis"

    def do_tutorial(self, request, queryset):
        tutorial = Tutorial.createTutorialFromAudios(queryset)
        Task.createTask(tutorial, Task.TASK_TYPE_VIDEO_JOINER)
        msg = _("A video tutorial has been created with the selected audios")
        self.message_user(
            request,
            msg
        )

    do_tutorial.short_description = "Create a tutorial with selection"


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    actions = [
        'youtube_create'
    ]
    list_display = ('name', 'language', 'is_target',
                    'tutorial_count', 'tutorial_to_upload_count'
                    )

    def youtube_create(self, request, queryset):
        for item in queryset:
            Task.createTask(
                item,
                Task.TASK_TYPE_PLAYLIST_CREATE
            )
            msg = _("Youtube playlist creation for %(item)s has been queued")
            self.message_user(
                request,
                msg
            )
    youtube_create.short_description = "Create YouTube Playlist"


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'created', 'modified',
                    'task_type', 'get_status', 'last_logs'
                    )
    list_filter = ('task_type', 'status', 'created', 'modified')
    actions = [
        'reprocess'
    ]

    def get_status(self, task):
        out = f'<span class="badge badge-{task.badge()}">{task.status_label()}</span>'
        return format_html(out)

    def last_logs(self, obj):
        out = '--'
        logs = obj.tasklog_set.all()
        if logs.count() > 0:
            out = logs.last().text
        return out

    def reprocess(self, request, queryset):
        for item in queryset:
            msg = _("The task %(text)s has been queued for reprocess ")
            item.process()
            self.message_user(
                request,
                msg
            )

    reprocess.short_description = "Retry"


@admin.register(TaskPreset)
class TaskPresetAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'preset_type',
        'description', 'preset', 'system_default'
    )
    list_editable = ('name', 'description', 'preset_type', 'system_default')


admin.site.site_header = "Intonation Studio"
