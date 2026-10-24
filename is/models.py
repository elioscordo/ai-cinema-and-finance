from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from filer.fields.file import FilerFileField
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.template.loader import render_to_string
from .utils import ModelDiffMixin


class Task(models.Model):
    """
        A task is executed by the queue.
    """
    TASK_STATUS_STARTED = 0
    TASK_STATUS_PENDING = 1
    TASK_STATUS_HOLDING = 2
    TASK_STATUS_ERROR = 3
    TASK_STATUS_SUCCESS = 4

    TASK_STATUS_PROCESSABLE = [
        TASK_STATUS_PENDING,
        TASK_STATUS_HOLDING,
        TASK_STATUS_ERROR
    ]
    TASK_STATUS_CHOICES = (
        (TASK_STATUS_PENDING, "Pending"),
        (TASK_STATUS_STARTED, "Started"),
        (TASK_STATUS_SUCCESS, "Success"),
        (TASK_STATUS_ERROR, "Error"),
        (TASK_STATUS_HOLDING, "Holding")
    )
    TASK_STATUS_DICT = dict(TASK_STATUS_CHOICES)

    BADGE_DICT = {
        TASK_STATUS_STARTED: 'info',
        TASK_STATUS_PENDING: 'warning',
        TASK_STATUS_HOLDING: 'dark',
        TASK_STATUS_SUCCESS: 'success',
        TASK_STATUS_ERROR: 'danger',
    }
    TASK_TYPE_ANALYSIS = 'analysis'
    TASK_TYPE_SPEAKER = 'speaker'
    TASK_TYPE_VIDEO_JOINER = 'joiner'
    TASK_TYPE_VIDEO_TUTORIAL = 'video_tutorial'
    TASK_TYPE_PLAYLIST_CREATE = 'playlist_create'
    TASK_TYPE_PLAYLIST_ITEM_CREATE = 'playlist_item_create'
    TASK_TYPE_TUTORIAL = 'tutorial_simple'
    TASK_TYPE_UPLOAD = 'video_upload'
    TASK_TYPE_VIDEO = 'video'

    TASK_TYPE_CHOICES = (
        (TASK_TYPE_ANALYSIS, "Audio Analyser"),
        (TASK_TYPE_SPEAKER, "Artificial Speaker"),
        (TASK_TYPE_VIDEO_JOINER, "Video Joiner"),
        (TASK_TYPE_VIDEO_TUTORIAL, "Video Tutorial"),
        (TASK_TYPE_VIDEO, "Video Maker"),
        (TASK_TYPE_UPLOAD, "Video Uploader"),
        (TASK_TYPE_TUTORIAL, "Tutorial Creator Simple"),
        (TASK_TYPE_PLAYLIST_CREATE, "YouTube Playlist Create"),
        (TASK_TYPE_PLAYLIST_ITEM_CREATE, "YouTube Playlist Item Create")
    )
    TASK_TYPE_DICT = dict(TASK_TYPE_CHOICES)

    QUEUE_NORMAL = 'queue.normal'
    QUEUE_HEAVY = 'queue.heavy'
    QUEUE_DICT = {
        TASK_TYPE_ANALYSIS: QUEUE_NORMAL,
        TASK_TYPE_SPEAKER: QUEUE_NORMAL,
        TASK_TYPE_VIDEO_JOINER: QUEUE_HEAVY,
        TASK_TYPE_VIDEO_TUTORIAL: QUEUE_HEAVY,
        TASK_TYPE_VIDEO: QUEUE_HEAVY,
        TASK_TYPE_UPLOAD: QUEUE_HEAVY,
        TASK_TYPE_PLAYLIST_CREATE: QUEUE_HEAVY,
        TASK_TYPE_PLAYLIST_ITEM_CREATE: QUEUE_HEAVY
    }
    subject_ct = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="subject"
    )
    subject_id = models.PositiveIntegerField()
    subject = GenericForeignKey('subject_ct', 'subject_id')

    obj_ct = models.ForeignKey(
        ContentType,
        related_name="object",
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    obj_id = models.PositiveIntegerField(
        blank=True,
        null=True
    )
    obj = GenericForeignKey('obj_ct', 'obj_id')
    thr_ct = models.ForeignKey(
        ContentType,
        related_name="thr",
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    thr_id = models.PositiveIntegerField(
        blank=True,
        null=True
    )
    thr = GenericForeignKey('thr_ct', 'thr_id')

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    status = models.IntegerField(choices=TASK_STATUS_CHOICES, default=1)
    payload = models.JSONField(blank=True, null=True)
    task_type = models.SlugField(choices=TASK_TYPE_CHOICES)

    next = models.ForeignKey(
        'is_core.Task',
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    owner = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    class Meta:
        ordering = ['status', '-modified']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def set_status(self, status):
        self.status = status
        self.save()

    def badge(self):
        return self.BADGE_DICT[self.status]

    def status_label(self):
        return self.TASK_STATUS_DICT[self.status]

    def type_label(self):
        return self.TASK_TYPE_DICT[self.task_type]

    def is_processable(self):
        return self.status in self.TASK_STATUS_PROCESSABLE

    def has_pending_previous(self):
        not_success = ~Q(status=self.TASK_STATUS_SUCCESS)
        out = self.task_set.filter(not_success).count() > 0
        return out

    def process(self):
        from .tasks import process_task
        try:
            process_task.apply_async(
                queue=self.get_queue(),
                kwargs={
                    'task_id': self.id
                }
            )
        except:
            pass

    def get_queue(self):
        queue = self.QUEUE_NORMAL
        if self.task_type in self.QUEUE_DICT:
            return Task.QUEUE_DICT[self.task_type]
        return queue

    @staticmethod
    def createTask(
            subject,
            task_type,
            next=None,
            owner=None,
            obj=None,
            thr=None,
            process=True
    ):
        task = Task.objects.create(
           subject=subject,
           task_type=task_type,
           obj=obj,
           thr=thr,
           owner=owner,
           next=next
        )
        if process:
            task.process()
        return task

    def log(self, message, level='error'):
        log = TaskLog.objects.create(
            task=self,
            level=level,
            text=message
        )
        return log

    def __str__(self):
        return self.id


class TaskLog(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    TASK_LOG_LEVEL_ERROR = 'error'
    TASK_LOG_LEVEL_WARNING = 'warning'

    TASK_LOG_LEVELS = (
        (TASK_LOG_LEVEL_ERROR, 'Error'),
        (TASK_LOG_LEVEL_WARNING, 'Warning')
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    text = models.TextField()
    level = models.SlugField(
        choices=TASK_LOG_LEVELS,
        default=TASK_LOG_LEVEL_ERROR
    )


class TaskHolder:
    """
    Mixin to add tasks functionality
    """

    def tasks(self):
        ctype = ContentType.objects.get_for_model(self.__class__)
        obj = Q(obj_ct__pk=ctype.id, obj_id=self.id)
        subject = Q(
            subject_ct__pk=ctype.id,
            subject_id=self.id
        )
        thr = Q(
            thr_ct__pk=ctype.id,
            thr_id=self.id
        )
        tasks = Task.objects.filter(
           subject | obj | thr
        )
        return tasks


class Language(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    code = models.CharField(
        max_length=10
    )
    name = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )
    variant = models.BooleanField(
        default=True
    )
    iso = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.code

    @staticmethod
    def get_or_create(code):
        variant = '-' in code
        out, created = Language.objects.get_or_create(
            code=code,
        )
        if variant:
            out.variant = True
            out.save()
        return out


class Category(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    name = models.CharField(
        max_length=1023
    )
    slug = models.SlugField(
        max_length=255
    )


class Playlist(models.Model):
    name = models.CharField(
        _("Name"), max_length=1023 ,
        null=True, blank=True
    )
    description = models.TextField(
        _("Description"),
        null=True,
        blank=True
    )
    target_users = models.ManyToManyField(
        'auth.User',
        blank=True
    )
    language = models.ForeignKey(
        Language,
        on_delete=models.CASCADE
    )
    is_target = models.BooleanField(
        _("Global Target"),
        default=False
    )
    youtube_id = models.SlugField(
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        if self.is_target:
            # only one global target per language
            playlists = Playlist.objects.filter(
                language=self.language,
                is_target=True
            ).exclude(pk=self.pk)
            playlists.update(is_target=False)

        super().save(*args, **kwargs)

    @classmethod
    def get_target(cls, language, user):
        target_playlist = None
        playlists = Playlist.objects.filter(
                language=language,
                is_target=True
        )
        if playlists.count() > 0:
            target_playlist = playlists.first()
        return target_playlist

    def tutorial_count(self):
        return self.tutorial_set.all().count()

    def tutorial_to_upload_count(self):
        return self.tutorial_set.filter(
            youtube_id__isnull=True
        ).count()

    def __str__(self):
        return self.name


class Text(models.Model, TaskHolder):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    text = models.CharField(
        max_length=1023
    )
    extended = models.TextField(
        help_text=_("Optional. Replace the title for extended texts."),
        blank=True,
        null=True
    )
    language = models.ForeignKey(
        Language,
        on_delete=models.CASCADE
    )
    categories = models.ManyToManyField(
        Category,
        blank=True
    )
    playlists = models.ManyToManyField(
        Playlist, blank=True
    )
    count_char = models.IntegerField(blank=True, null=True)
    count_vowels = models.IntegerField(blank=True, null=True)
    relevance = models.IntegerField(blank=True, null=True)

    def tutorial_count(self):
        return self.tutorial_set.count()

    def audio_count(self):
        return self.audio_set.count()

    def speak_and_tutorial(self, user):
        t = Task.createTask(
            self,
            Task.TASK_TYPE_TUTORIAL,
            process=False,
            owner=user,
            obj=Playlist.get_target(self.language, user)
        )
        self.speak(next=t)

    def speak(self, *args, **kwargs):
        Task.createTask(self, Task.TASK_TYPE_SPEAKER, **kwargs)

    def get_text(self):
        text = self.text
        if self.extended:
            text = self.extended
        return text

    def __str__(self):
        return self.text


class Speaker(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    code = models.SlugField(
        unique=True
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )
    is_human = models.BooleanField(
        default=False
    )
    languages = models.ManyToManyField(
        Language,
        blank=True
    )

    def __str__(self):
        return self.code

    @staticmethod
    def get_or_create(code, language_codes=[]):
        speaker, created = Speaker.objects.get_or_create(
            code=code
        )
        if created:
            for lang_code in language_codes:
                lang = Language.get_or_create(
                    lang_code
                )
                speaker.languages.add(lang)
        return speaker


class AudioAnalysis(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    data = models.JSONField()
    video = FilerFileField(
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.pk}"




class Audio(models.Model, ModelDiffMixin):
    diff_fields = ['id', 'file']
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=1023)
    file = FilerFileField(
        help_text="In server storage.",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    analysis = models.ForeignKey(
        AudioAnalysis,
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    speaker = models.ForeignKey(
        Speaker,
        blank=True,
        null=True,
        on_delete=models.CASCADE
    )
    rate = models.DecimalField(
        null=True,
        blank=True,
        max_digits=2,
        decimal_places=1
    )
    language = models.ForeignKey(
        Language,
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    owner = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    text = models.ForeignKey(
        Text,
        blank=True,
        null=True,
        on_delete=models.SET_NULL
    )
    order = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    def get_credits(self):
        if self.speaker:
            if self.speaker.name:
                return self.speaker.name
            elif self.speaker.code:
                return self.speaker.code
        return ""

    def save(self, *args, **kwargs):
        # recreate analysis
        next = kwargs.pop('next', None)
        super().save(*args, **kwargs)
        if 'file' in self.changed_fields or 'id' in self.changed_fields:
            Task.createTask(
                self,
                Task.TASK_TYPE_ANALYSIS,
                next=next
            )

    def get_text(self):
        t = self.name
        if self.text:
            t = self.text.text
        return t

    def url(self):
        return self.file.url

    class Meta:
        ordering = ['order']


class AudioTrasformation(models.Model, ModelDiffMixin):
    input = models.ForeignKey(
        Audio,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="input"
    )
    output = models.ForeignKey(
        Audio,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="output"
    )
    code = models.CharField(null=True, max_length=1024)
    payload = models.JSONField(null=True)


class TutorialAudio(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    tutorial = models.ForeignKey("Tutorial", on_delete=models.CASCADE)
    audio = models.ForeignKey(Audio, on_delete=models.CASCADE)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']


class TutorialText(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    tutorial = models.ForeignKey("Tutorial", on_delete=models.CASCADE)
    text = models.ForeignKey(Text, on_delete=models.CASCADE)
    order = models.IntegerField(default=0)


class TaskPreset(models.Model):
    PRESET_TYPE_CHOICES = Task.TASK_TYPE_CHOICES
    name = models.CharField(
        max_length=1024,
        unique=True
    )
    description = models.TextField()
    preset_type = models.SlugField(choices=PRESET_TYPE_CHOICES)
    system_default = models.BooleanField(_("Default"), default=False)
    preset = models.JSONField()

    @staticmethod
    def get(preset_type):
        presets = TaskPreset.objects.filter(
            system_default=True,
            preset_type=preset_type
        )
        preset = None
        if presets.exists():
            preset = presets.first().preset

        return preset

    def __str__(self):
        return f'{self.name}'


class Tutorial(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    PRIVACY_CHOICE_PUBLIC = 'public'
    PRIVACY_CHOICE_PRIVATE = 'private'

    PRIVACY_CHOICES = (
        (PRIVACY_CHOICE_PUBLIC, _('public')),
        (PRIVACY_CHOICE_PRIVATE, _('private'))
    )
    # this is the title in youtube
    title = models.CharField(
        _("Youtube Title"), max_length=1023,
        null=True, blank=True
    )
    # name our system name
    name = models.CharField(
        _("Tutorial Name"),
        max_length=1023
    )
    description = models.TextField(_("Description"), null=True, blank=True)
    category = models.CharField(
        _("Category"), max_length=1023,
        null=True, blank=True
    )
    keywords = models.CharField(
        _("Keywords"), help_text=_("Comma separated"),
        max_length=1023, null=True, blank=True
    )
    privacyStatus = models.CharField(
        _("PrivacyStatus"),
        choices=PRIVACY_CHOICES,
        default=PRIVACY_CHOICE_PUBLIC,
        max_length=1023
    )
    youtube_id = models.SlugField(
        null=True,
        blank=True
    )
    url = models.URLField(
        _("Video Url"),
        max_length=200,
        null=True,
        blank=True
    )
    categories = models.ManyToManyField(
        Category,
        blank=True
    )
    texts = models.ManyToManyField("Text", through='TutorialText')
    audios = models.ManyToManyField("Audio", through='TutorialAudio')
    playlists = models.ManyToManyField(
        Playlist, blank=True
    )

    video = FilerFileField(
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    owner = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    language = models.ForeignKey(
        Language,
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return f'{self.name}'

    @staticmethod
    def createTutorialFromAudios(audios, language=None):
        tutorial = Tutorial.objects.create(
            name='Audiogeneratated',
        )
        texts = []
        for audio in audios:
            TutorialAudio.objects.create(
                tutorial=tutorial,
                audio=audio,
                order=audio.order
            )
            if audio.text and audio.text not in texts:
                texts.append(audio.text)
        for i, text in enumerate(texts):
            TutorialText.objects.create(
                tutorial=tutorial,
                text=text,
                order=i
            )
        tutorial.name = ' - '.join([text.text for text in texts])
        if language is not None:
            tutorial.language = language
        elif len(texts) > 0:
            tutorial.language = texts[0].language
        tutorial.save()
        return tutorial

    def updateVideoMeta(self):
        payload = {
            'name': self.name,
            'id': self.id,
            'language': self.language.name
        }
        self.title = render_to_string(
            'video/title.txt', payload
        )
        self.description = render_to_string(
            'video/desc.txt', payload
        )
        self.keywords = render_to_string("video/keywords.txt", payload)
        self.save()

    def get_playlist(self):
        # one playlist is allowed per tutorial
        # TODO allow more!
        playlist = None
        if self.playlists.all().count() > 0:
            playlist = self.playlists.all().first()
        return playlist

    class Meta:
        ordering = ['-created']
