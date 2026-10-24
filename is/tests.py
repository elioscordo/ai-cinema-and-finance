import os
from django.test import TestCase
from audiomixer.models import Text, Tutorial, \
    Task, Language, TaskPreset, Audio, Speaker
from audiomixer.tasks import TaskSpeaker, TaskAnalyst, TaskVideo, process_task
from filer.models import File
from django.conf import settings


class FixtureCreator:
    @staticmethod
    def createAudio(filename, text, process=True):
        path = os.path.join(settings.MEDIA_ROOT, filename)
        file = File(
            file=path,
            name=filename,
            original_filename=filename,
        )
        file.save()
        audio = Audio.objects.create(
            name=text,
            file=file,
            rate="0.4"
        )
        if process:
            # the audio is preprocessed
            task = Task.createTask(
                audio,
                Task.TASK_TYPE_ANALYSIS
            )
            TaskAnalyst(task).process()
        return audio

    @staticmethod
    def createVideoTutorial(filename, text):
        path = os.path.join(settings.MEDIA_ROOT, 'tutorials/test.mp4')
        file = File(
            file=path,
            name=filename,
            original_filename=filename,
        )
        file.save()
        tutorial = Tutorial.objects.create(
            name=text,
            video=file,
        )
        return tutorial


class TaskVideoCase(TestCase):
    def setUp(self):
        a1 = FixtureCreator.createAudio('mp3/test1.mp3', 'test1')
        a2 = FixtureCreator.createAudio('mp3/test2.mp3', 'test2')

        self.tutorial1 = Tutorial.objects.create(
            name='test1',
        )
        self.tutorial1.audios.add(a1)
        self.tutorial1.audios.add(a2)
        self.task = Task.createTask(
            self.tutorial1,
            Task.TASK_TYPE_VIDEO_JOINER
        )
        TaskPreset.objects.create(
            preset={
                'color1': '0.5',
                'color2': '0.5',
                'color3': '0.5',
                'color4': '0.5'
            },
            system_default=True,
            preset_type=Task.TASK_TYPE_VIDEO_JOINER
        )

    def test_video_task(self):
        taskSpeaker = TaskVideo(self.task)
        taskSpeaker.process()


class TaskAnalysisCase(TestCase):

    def setUp(self):
        a1 = FixtureCreator.createAudio(
            'mp3/test1.mp3',
            'test1',
            process=False
        )
        self.task = Task.createTask(
            a1,
            Task.TASK_TYPE_ANALYSIS
        )

    def test_task(self):
        task = TaskAnalyst(self.task)
        task.process()


class TaskSpeakerCase(TestCase):
    def setUp(self):
        self.lang = Language.objects.create(
            name="English",
            code='en'
        )
        self.text1 = Text.objects.create(
            text='test',
            language=self.lang
        )
        self.task = Task.createTask(
            self.text1,
            Task.TASK_TYPE_SPEAKER
        )
        TaskPreset.objects.create(
            preset={
                'rates': '0.5',
                'wavenet': True
            },
            system_default=True,
            preset_type=Task.TASK_TYPE_SPEAKER
        )

    def test_get_or_create_speaker(self):
        speaker1 = Speaker.get_or_create(
            'code', ['it', 'en-gb']
        )
        speaker2 = Speaker.get_or_create(
            'code', ['it', 'en-gb']
        )

        self.assertEqual(speaker1.id, speaker2.id)
        self.assertEqual(len(speaker2.languages.all()), 2)

    def test_task(self):
        task = TaskSpeaker(self.task)
        task.process()


class TaskTutorialCase(TestCase):
    def setUp(self):
        self.lang = Language.objects.create(
            name="English",
            code='en'
        )
        self.text1 = Text.objects.create(
            text='test',
            language=self.lang
        )
        TaskPreset.objects.create(
            preset={
                'rates': '0.5',
                'wavenet': True
            },
            system_default=True,
            preset_type=Task.TASK_TYPE_SPEAKER
        )

    def test_task(self):
        t1 = Task.createTask(
            self.text1,
            Task.TASK_TYPE_TUTORIAL,
            process=False
        )
        t1.has_pending_previous()


class TaskUploadlCase(TestCase):
    def setUp(self):
        self.tutorial = FixtureCreator.createVideoTutorial(
            "test", 'test'
        )
        self.tutorial.updateVideoMeta()

    def test_task(self):
        t1 = Task.createTask(
            self.tutorial,
            Task.TASK_TYPE_UPLOAD,
            process=False
        )
        process_task(t1.id)
