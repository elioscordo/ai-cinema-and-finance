import os
from celery import shared_task
from django.conf import settings
from filer.models import File
from simple_youtube_api.Channel import Channel
from simple_youtube_api.LocalVideo import LocalVideo
from celery.utils.log import get_task_logger

from audiomixer.models import Task, Tutorial, \
    Audio, AudioAnalysis, TaskPreset, Speaker
from is_lib.speakers import GoogleSpeaker
from is_lib.audio import AudioAnalyst
from is_lib.video import VideoMaker, TutorialVideoMaker
from is_lib.youtube import upload_file, \
    playlist_insert, playlist_item_insert


logger = get_task_logger(__name__)


class TaskVideoJoiner:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        tutorial = self.task.subject
        self.preset = TaskPreset.get(self.task.task_type)
        clips = []
        maker = TutorialVideoMaker(
            settings.MEDIA_ROOT
        )
        clips = [audio.analysis.video.path for audio in tutorial.audios.all()]
        video = maker.make(
            clips,
            f'tutorial_{tutorial.id}.mp4'
        )
        video_file = File(
            file=video,
            name=os.path.basename(video),
            original_filename=os.path.basename(video)
        )
        video_file.save()
        tutorial.video = video_file
        tutorial.save()
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskSpeaker:
    def __init__(self, task):
        self.task = task

    @staticmethod
    def get_lang_preset(preset, lang):
        if lang in preset:
            return preset[lang]
        return preset

    def create_text_audio(self, file_path, text, speaker, order):
        file = File(
                file=file_path,
                name=file_path,
                original_filename=file_path
            )
        file.save()
        audio = Audio(
            name=text.text,
            text=text,
            file=file,
            language=text.language,
            order=order,
            speaker=speaker
        )
        audio.save(next=self.task.next)

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        text = self.task.subject
        preset = TaskPreset.get(self.task.task_type)
        speaker = GoogleSpeaker(
            settings.GOOGLE_CREDENTIALS,
            settings.MEDIA_ROOT
        )
        lang_preset = self.get_lang_preset(preset, text.language.code)
        repetitions = speaker.repeat(
            text.get_text(),
            str(text.id),
            preset=lang_preset,
            lang=text.language.code
        )
        order = 0
        # {"dsp":["stretch":"{rate:1.1}, ]" }"
        for repetition in repetitions:
            speaker = Speaker.get_or_create(
                repetition['voice'],
                repetition['languages']
            )
            if "dsp" in lang_preset:
                from is_lib import dsp
                for item in lang_preset["dsp"]:
                    algo = item["algo"]
                    payload = item["payload"]
                    func = getattr(dsp, algo)
                    prefix = dsp.get_name(algo, payload)
                    output_name = repetition["name"]
                    output_name = f"{output_name}-{prefix}.mp3"
                    input_path = os.path.join(settings.MEDIA_ROOT, repetition["name"])
                    output_path = os.path.join(settings.MEDIA_ROOT, output_name)
                    func(
                        input_path,
                        output_path,
                        **payload
                    )
                    self.create_text_audio(output_name, text, speaker, order)
            self.create_text_audio(repetition["name"], text, speaker, order)
            order = order + 1
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskAnalyst:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        audio = self.task.subject
        analyst = AudioAnalyst(settings.TEMP_DIR)
        # set data
        data = analyst.analyse(audio.file.path)
        data['text'] = audio.get_text()
        if not audio.analysis:
            analysis = AudioAnalysis.objects.create(
                audio=audio,
                data=data
            )
            audio.analysis = analysis
            audio.save()
        else:
            audio.analysis.data = data
            audio.analysis.save()
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskVideo:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        audio = self.task.subject
        analysis = audio.analysis
        if not analysis:
            self.task.log(f'audio {audio.id} has not been analysed yet')
            self.task.set_status(Task.TASK_STATUS_ERROR)
        data = analysis.data
        data['text'] = audio.get_text()
        video_maker = VideoMaker(
             str(audio.id),
             settings.MEDIA_ROOT,
             settings.TEMP_DIR
        )
        video = video_maker.make_video(
            audio.file.path,
            data
        )
        video_file = File(
            file=video,
            name=os.path.basename(video),
            original_filename=os.path.basename(video)
        )
        video_file.save()
        analysis.video = video_file
        analysis.save()
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskManimTutorial:
    """
    Create a video for each audio and then
    join all the videos
    """
    def __init__(self, task):
        self.task = task

    def process(self):
        tutorial = self.task.subject
        from is_lib.manim import ISPlot
        from manim import tempconfig
        with tempconfig(
            {
                "output_file": f"tutorial-{tutorial.id}",
                "media_dir": settings.MEDIA_ROOT
             }):
            scene = ISPlot()
            scene.audios = tutorial.audios.all()
            scene.filename = f"tutorial-{tutorial.id}.mp4"
            try:
                scene.render()
            except Exception as e:
                self.task.log(str(e))
                self.task.set_status(Task.TASK_STATUS_ERROR)
                return
            path = str(scene.renderer.file_writer.movie_file_path)
            path = os.path.relpath(
                path, settings.MEDIA_ROOT
            )
            video_file = File(
                file=path,
                name=os.path.basename(path),
                original_filename=os.path.basename(path)
            )
            video_file.save()
            tutorial.video = video_file
            tutorial.save()
            self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskTutorial:
    """
    Create a tutorial from all the available audio of a text
    Usually created has a next task
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        text = self.task.subject
        playlist = self.task.obj
        tutorial = Tutorial.createTutorialFromAudios(text.audio_set.all())
        tutorial.updateVideoMeta()
        if playlist:
            tutorial.playlists.add(playlist)
            text.playlists.add(playlist)
        self.task.set_status(Task.TASK_STATUS_SUCCESS)


class TaskVideoTutorial:
    """
    Create a video for each audio and then
    join all the videos
    """
    def __init__(self, task):
        self.task = task

    def process(self):
        tutorial = self.task.subject
        joiner = Task.createTask(
            tutorial,
            Task.TASK_TYPE_VIDEO_JOINER
        )
        for audio in tutorial.audios.all():
            t = Task.createTask(
                audio,
                Task.TASK_TYPE_VIDEO,
                next=joiner
            )
            t.process()


class TaskPlaylistCreate:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        playlist = self.task.subject
        try:
            playlist.youtube_id = playlist_insert(
                playlist
            )
            playlist.save()
            self.task.set_status(Task.TASK_STATUS_SUCCESS)
        except Exception as e:
            self.task.log(str(e))
            self.task.set_status(Task.TASK_STATUS_ERROR)


class TaskPlaylistItemCreate:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        tutorial = self.task.subject
        playlist = tutorial.get_playlist()
        try:
            playlist_item_insert(tutorial, playlist)
            self.task.set_status(Task.TASK_STATUS_SUCCESS)
        except Exception as e:
            self.task.log(str(e))
            self.task.set_status(Task.TASK_STATUS_ERROR)


class TaskUpload:
    def __init__(self, task):
        self.task = task

    def process(self):
        self.task.set_status(Task.TASK_STATUS_STARTED)
        tutorial = self.task.subject
        # file is a transient field
        tutorial.file = tutorial.video.path
        try:
            tutorial.youtube_id = upload_file(tutorial)
            tutorial.save()
            playlist = tutorial.get_playlist()
            if playlist:
                if playlist.youtube_id is None:
                    playlist.youtube_id = playlist_insert(
                        playlist
                    )
                    playlist.save()
                playlist_item_insert(tutorial, playlist)
            self.task.set_status(Task.TASK_STATUS_SUCCESS)
        except Exception as e:
            self.task.log(str(e))
            self.task.set_status(Task.TASK_STATUS_ERROR)


class TaskSimpleUpload:
    """ Not linked yet """
    def __init__(self, task):
        self.task = task

    def process(self):
        # logging into the channel
        self.task.set_status(Task.TASK_STATUS_STARTED)
        tutorial = self.task.subject
        channel = Channel()
        channel.login(
            settings.GOOGLE_CLIENT_SECRET,
            os.path.join(settings.DATA_DIR, 'credentials.storage')
        )

        video = LocalVideo(file_path=tutorial.video.path)
        video.set_title(tutorial.title)
        video.set_description(tutorial.description)
        video.set_category("Education")
        video.set_default_language("en")
        # setting status
        video.set_embeddable(True)
        video.set_license("creativeCommon")
        video.set_privacy_status("public")
        video.set_public_stats_viewable(True)
        video = channel.upload_video(video)
        tutorial.youtube_id = video.id
        tutorial.save()


TASK_DELEGATES = {
    Task.TASK_TYPE_ANALYSIS: TaskAnalyst,
    Task.TASK_TYPE_SPEAKER: TaskSpeaker,
    Task.TASK_TYPE_VIDEO: TaskVideo,
    Task.TASK_TYPE_VIDEO_JOINER: TaskVideoJoiner,
    Task.TASK_TYPE_TUTORIAL: TaskTutorial,
    Task.TASK_TYPE_UPLOAD: TaskUpload,
    Task.TASK_TYPE_VIDEO_TUTORIAL: TaskManimTutorial,
    Task.TASK_TYPE_PLAYLIST_CREATE: TaskPlaylistCreate,
    Task.TASK_TYPE_PLAYLIST_ITEM_CREATE: TaskPlaylistItemCreate
}


@shared_task
def process_task(task_id):
    task = Task.objects.get(id=task_id)
    print(f"Processing task {task.id} ")
    if settings.WORKER_MODE:
        # In worker mode we sync pull before the task
        os.system(settings.RSYNC_CMD_PULL)
    if task.has_pending_previous():
        task.set_status(Task.TASK_STATUS_HOLDING)
    elif task.is_processable():
        Delegate = TASK_DELEGATES[task.task_type]
        print(f"Delegate the task to {Delegate}")
        delegate = Delegate(task)
        try:
            delegate.process()
        except Exception as e:
            task.log(str(e))
            task.set_status(Task.TASK_STATUS_ERROR)
        if settings.WORKER_MODE:
            # In worker mode we sync pull before the task
            os.system(settings.RSYNC_CMD_PUSH)
        if task.next \
            and task.next.is_processable() \
                and not task.next.has_pending_previous():
            process_task.delay(task.next.id)
