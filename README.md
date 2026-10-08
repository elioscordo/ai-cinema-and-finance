# Guillermo - Tell me a story

Guillermo is an AI-powered storytelling and multimedia generation platform. It leverages Google's Vertex AI (Gemini) to generate text, images, video, and audio content based on user-defined stories, characters, and scenes.

## Live Demo

The platform is accessible at [https://guillermoai.duckdns.org/](https://guillermoai.duckdns.org/). Please request access to the platform if you wish to evaluate its capabilities.

## Core Features

- **AI Agents:** Configurable agents for different modalities (Text, Image, Video, Voice).
- **Story Management:** Organize your creative process into Stories, Scenes, and Actions.
- **Task Queue:** Asynchronous generation of high-quality assets using Celery and SQLite.
- **Asset Management:** Integrated file management with `django-filer`.
- **Modern Admin:** A sleek management interface powered by the Unfold admin theme.

## Flow Agent


## Prerequisites

- Python 3.10+
- A Google Cloud Project with Vertex AI API enabled.
- A valid Vertex AI API Key.

## Installation

1. **Clone the repository.**
2. **Set up a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
3. **Install dependencies:**
   ```bash
   make install
   ```
4. **Configure environment variables:**
   Create a `.env` file in the project root:
   ```env
   DJANGO_SECRET_KEY=your-django-secret
   GOOGLE_GENAI_VERTEX_API_KEY=your-vertex-ai-api-key
   SITE_URL=http://localhost:8000
   DATABASE_TYPE=sqlite
   CELERY_BROKER_TYPE=sqlite
   ```

## Usage

- **Initialize the database:** `make migrate`
- **Create an admin user:** `make superuser`
- **Start the server:** `make run`
- **Start the background worker:** `make worker` (Required for AI content generation)

## Project Structure

- `agent/`: Integration with Google GenAI SDK and usage tracking.
- `task/`: Generic task processing system.
- `scene/`: Storyboarding, character definitions, and asset generation logic.
- `brainstorm/`: Collaborative writing and theme discovery tools.
- `project/`: Project configuration and settings.