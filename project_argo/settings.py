import os
from pathlib import Path
from dotenv import load_dotenv
from django.utils.translation import gettext_lazy as _
from django.templatetags.static import static
from django.urls import reverse_lazy


PROJECT_DIR = Path(__file__).resolve().parent

USE_TASK_QUEUE = True
BASE_DIR = PROJECT_DIR.parent
load_dotenv(dotenv_path=os.path.join(PROJECT_DIR, '.env'), override=True)
PROMPT_ROOT = os.getenv("PROMPT_ROOT", os.path.join(PROJECT_DIR, "prompts"))

IB_HOST = os.getenv("IB_HOST", os.getenv("IB_EXAMPLE_HOST", "127.0.0.1"))
IB_PORT = int(os.getenv("IB_PORT", os.getenv("IB_EXAMPLE_PORT", "4002")))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
IB_TIMEOUT = int(os.getenv("IB_TIMEOUT", "10"))

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "your-django-secret")
DEBUG = True
ALLOWED_HOSTS = ['*']
# Application definition
INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.import_export',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'easy_thumbnails',
    'filer',
    'django_celery_beat',
    'crispy_forms',
    'agent.apps.AgentConfig',
    'task',
    'argo',
]

CRISPY_TEMPLATE_PACK = "unfold_crispy"
CRISPY_ALLOWED_TEMPLATE_PACKS = ["unfold_crispy"]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'project_argo.urls'
WSGI_APPLICATION = 'project_argo.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages'
            ],
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
            'debug': DEBUG,
        },
    }
]

UNFOLD = {
    "SITE_TITLE": _("Argo"),
    "SITE_HEADER": _("Argo"),
    "SITE_SUBHEADER": _("Quantitative Trading & Portfolio Management"),
    "STYLES": [
        lambda request: static("css/unfold_filer_custom.css"),
        lambda request: static("css/custom.css"),
    ],
    "ACCOUNT": {},
    "SIDEBAR": {
        "show_all_applications": True,
        "show_user": True,
        "navigation": [
            {
                "title": _("Research & Simulation"),
                "separator": True,
                "items": [
                    {
                        "title": _("Instruments"),
                        "icon": "show_chart",
                        "link": reverse_lazy("admin:argo_instrument_changelist"),
                    },
                    {
                        "title": _("Instrument Groups"),
                        "icon": "dataset",
                        "link": reverse_lazy("admin:argo_instrumentgroup_changelist"),
                    },
                    {
                        "title": _("Strategies"),
                        "icon": "psychology",
                        "link": reverse_lazy("admin:argo_strategy_changelist"),
                    },
                    {
                        "title": _("Strategy Instances"),
                        "icon": "candlestick_chart",
                        "link": reverse_lazy("admin:argo_strategyinstance_changelist"),
                    },
                    
                    {
                        "title": _("Backtests"),
                        "icon": "science",
                        "link": reverse_lazy("admin:argo_backtest_changelist"),
                    },
                    {
                        "title": _("Backtest Runs"),
                        "icon": "history",
                        "link": reverse_lazy("admin:argo_backtestrun_changelist"),
                    },
                    
                ],
            },
            {
                "title": _("Live Trading"),
                "separator": False,
                "items": [
                    {
                        "title": _("Portfolios"),
                        "icon": "pie_chart",
                        "link": reverse_lazy("admin:argo_portfolio_changelist"),
                    },

                    {
                        "title": _("Positions"),
                        "icon": "trending_up",
                        "link": reverse_lazy("admin:argo_position_changelist"),
                    },
                    {
                        "title": _("Broker Accounts"),
                        "icon": "account_balance",
                        "link": reverse_lazy("admin:argo_account_changelist"),
                    },
                ],
            },
            {
                "title": _("AI Agents & Tasks"),
                "separator": True,
                "items": [
                    {
                        "title": _("AI Agents"),
                        "icon": "smart_toy",
                        "link": reverse_lazy("admin:agent_agent_changelist"),
                    },
                    {
                        "title": _("Prompts"),
                        "icon": "description",
                        "link": reverse_lazy("admin:agent_prompt_changelist"),
                    },
                    {
                        "title": _("Background Tasks"),
                        "icon": "task_alt",
                        "link": reverse_lazy("admin:task_task_changelist"),
                    },
                ],
            },
        ],
    },
}

# Database
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "postgresql")
if DATABASE_TYPE == "sqlite":
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv("POSTGRES_DB", "argo2"),
            'USER': os.getenv("POSTGRES_USER", "postgres"),
            'PASSWORD': os.getenv("POSTGRES_PASSWORD", "postgres"),
            'HOST': os.getenv("POSTGRES_HOST", "localhost"),
            'PORT': os.getenv("POSTGRES_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
LANGUAGES = [
    ('en', _('English')),
    ('it', _('Italian')),
    ('es', _('Spanish')),
    ('pt', _('Portuguese')),
    ('fr', _('French')),
]
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / 'locale']

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

HISTORICAL_ROOT = os.getenv("HISTORICAL_ROOT", os.path.join(BASE_DIR, "historical_data"))

# Celery Configuration
CELERY_BROKER_TYPE = os.getenv("CELERY_BROKER_TYPE", "redis")
if CELERY_BROKER_TYPE == "sqlite":
    CELERY_BROKER_URL = f"sqla+sqlite:///{BASE_DIR / 'argo_celerydb.sqlite'}"
else:
    CELERY_BROKER_URL = os.getenv("ARGO_CELERY_BROKER_URL") or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "7200"))
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "7260"))
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))

# Queue and schedule isolation for Argo
CELERY_TASK_DEFAULT_QUEUE = 'argo'
CELERY_TASK_DEFAULT_EXCHANGE = 'argo'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'argo'
CELERY_BEAT_SCHEDULE_FILENAME = str(BASE_DIR / 'celerybeat-argo-schedule')

GENAI_REQUEST_TIMEOUT_MS = int(os.getenv("GENAI_REQUEST_TIMEOUT_MS", "300000"))

# Task Constants & Schemas
TASK_TYPE_GENERATE_TEXT = 'generate_text'
TASK_EXECUTE_FUNC = 'execute_func'
TASK_FUNC = 'func'
TASK_TYPE_CHOICES = (
    (TASK_TYPE_GENERATE_TEXT, _("Generate Text")),
    (TASK_EXECUTE_FUNC, _("Execute Function")),
)

SCHEMA_OUTPUT_WITH_MESSAGE = "outwithmsg"
SCHEMA_CREATE_INSTRUCTIONS = "create_instructions"
SCHEMA_INSTRUMENTS = "instruments"
SCHEMA_INSTANCES = "instances"
SCHEMA_OPTIMIZE = "optimize"

AGENT_SCHEMA_CHOICES = [
    (SCHEMA_OUTPUT_WITH_MESSAGE, _("Output With Message")),
    (SCHEMA_CREATE_INSTRUCTIONS, _("Create Instructions")),
    (SCHEMA_INSTRUMENTS, _("Instruments")),
    (SCHEMA_INSTANCES, _("Strategy Instances")),
    (SCHEMA_OPTIMIZE, _("Optimize Strategy Instance")),
]

AGENT_SCHEMAS = {
    SCHEMA_OUTPUT_WITH_MESSAGE: "agent.schemas.OutputWithMessageSchema",
    SCHEMA_CREATE_INSTRUCTIONS: "agent.schemas.CreateInstructionsSchema",
    SCHEMA_INSTRUMENTS: "argo.schemas.InstrumentsSchema",
}


TASK_TYPE_GENERATE_TEXT = 'generate_text'
TASK_RUN_BACKTEST = 'run_backtest'
TASK_RUN_OPTIMIZATION = 'run_optimization'
TASK_LOAD_DATA = 'load_data'
TASK_SEARCH_AND_CREATE_INSTRUMENTS = 'search_and_create_instruments'
TASK_EXECUTE_FUNC = 'execute_func'
TASK_FUNC = 'func'

TASK_DELEGATES = {
    TASK_TYPE_GENERATE_TEXT: 'agent.tasks.TaskGenerateText',
    TASK_RUN_BACKTEST: 'argo.tasks.TaskRunBacktest',
    TASK_RUN_OPTIMIZATION: 'argo.tasks.TaskRunOptimization',
    TASK_LOAD_DATA: 'argo.tasks.TaskLoadData',
    TASK_SEARCH_AND_CREATE_INSTRUMENTS: 'argo.tasks.TaskSearchAndCreateInstruments',
    TASK_EXECUTE_FUNC: 'task.tasks.TaskExecuteFunc',
    TASK_FUNC: 'task.tasks.TaskExecuteFunc',
}

PRESET_INFO = "info"
PRESET_INSTRUCTION = "instruction"

COMMON_TEXT_AGENT_PRESETS = (
    (PRESET_INFO, _("Last message")),
    (PRESET_INSTRUCTION, _("Instruction")),
)

ACTION_INFO = f"generate_text-preset-{PRESET_INFO}"
ACTION_INSTRUCTION = f"generate_text-preset-{PRESET_INSTRUCTION}-schema-{SCHEMA_OUTPUT_WITH_MESSAGE}"
ACTION_INSTRUCTION_COMMIT = f"generate_text-preset-{PRESET_INSTRUCTION}-schema-{SCHEMA_CREATE_INSTRUCTIONS}"

COMMON_TEXT_ACTION_CHOICES = (
    (ACTION_INFO, _("Info")),
    (ACTION_INSTRUCTION, _("Instruction")),
    (ACTION_INSTRUCTION_COMMIT, _("Instruction Commit")),
)

TASK_RETRY_EXCEPTIONS = [
    'RESOURCE_EXHAUSTED',
]

SYSTEM_PRESETS = [
    PRESET_INFO,
    PRESET_INSTRUCTION,
]
