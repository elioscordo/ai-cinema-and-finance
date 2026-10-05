from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from agent.sections import GenericFormSection
from agent.widgets import CodeWidget
from .models import Strategy


class StrategyCodeForm(forms.ModelForm):
    code = forms.CharField(
        label=_("Source Code"),
        widget=CodeWidget(language="python", attrs={"rows": 28}),
        required=False,
    )
    code.is_code = True

    class Meta:
        model = Strategy
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if "code" not in self.initial:
                self.initial["code"] = self.instance._get_strategy_source()
            file_path = self.instance.get_source_file_path()
            if file_path:
                self.fields["code"].help_text = format_html(
                    _("Source file: <code class='text-xs font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-primary-600 dark:text-primary-400'>{}</code>"),
                    file_path
                )
            else:
                self.fields["code"].help_text = _("Could not determine source file location.")

    def clean_code(self):
        code = self.cleaned_data.get("code", "")
        try:
            compile(code, "<strategy_code>", "exec")
        except SyntaxError as e:
            raise forms.ValidationError(
                _("Python syntax error at line %(line)d: %(error)s") % {
                    "line": e.lineno or 1,
                    "error": e.msg,
                }
            )
        return code

    def save(self, commit=True):
        instance = super().save(commit=commit)
        code = self.cleaned_data.get("code")
        if code is not None:
            instance.save_strategy_source(code)
        return instance


class StrategyCodeSection(GenericFormSection):
    do_not_call_in_templates = True
    form_class = StrategyCodeForm
    title = _("Strategy Source Code")
    key = "strategy_code"
    use_markdown_widgets = False
    submit_label = _("Save Code to File")


import json
from html import escape
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import path
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.clickjacking import xframe_options_exempt
from agent.sections import AjaxSection
from .models import BacktestRun


class BacktestRunSection(AjaxSection):
    do_not_call_in_templates = True
    verbose_name = _("Execution Runs")
    title = _("Execution Runs")
    key = "runs"
    collapsible = True
    template_name = "sections/backtest_runs_section.html"

    @classmethod
    def get_section_urls(cls, model_admin):
        return [
            path(
                f'refresh-section/{cls.key}/<int:content_type_id>/<int:object_id>/',
                model_admin.admin_site.admin_view(cls.refresh_view),
                name=cls.get_url_name('refresh_section'),
            ),
            path(
                f'run-content/<int:run_id>/<str:content_type>/',
                model_admin.admin_site.admin_view(cls.run_content_view),
                name=cls.get_url_name('run_content'),
            ),
        ]

    @classmethod
    def refresh_view(cls, request, content_type_id, object_id):
        content_type = get_object_or_404(ContentType, pk=content_type_id)
        model_class = content_type.model_class()
        instance = get_object_or_404(model_class, pk=object_id)

        if hasattr(instance, "runs"):
            runs = instance.runs.all().order_by("-created_at")
        elif hasattr(instance, "backtest_runs"):
            runs = instance.backtest_runs.all().order_by("-created_at")
        else:
            runs = BacktestRun.objects.filter(backtest_id=object_id).order_by("-created_at")

        context = {
            "instance": instance,
            "runs": runs,
            "section_key": cls.key,
            "content_type_id": content_type_id,
            "request": request,
        }
        html = render_to_string("sections/backtest_runs_section_content.html", context, request=request)
        return JsonResponse({"html": html, "count": runs.count()})

    @classmethod
    @xframe_options_exempt
    def run_content_view(cls, request, run_id, content_type):
        run = get_object_or_404(BacktestRun, pk=run_id)
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json"

        if content_type == "html":
            if is_ajax:
                return JsonResponse({
                    "title": f"Run #{run.id} - HTML Tearsheet",
                    "html": run.html_report or "<h1>No Tearsheet Report Generated</h1>",
                })
            return HttpResponse(
                run.html_report or "<h1>No Tearsheet Report Generated</h1>",
                content_type="text/html",
            )

        if content_type == "code":
            title = f"Run #{run.id} - Executed Strategy Code"
            content = run.code or "No code snapshot recorded."
            if is_ajax:
                return JsonResponse({"title": title, "content": content})
            return HttpResponse(cls._render_standalone_code(title, content), content_type="text/html")

        if content_type == "config":
            title = f"Run #{run.id} - Execution Configuration"
            content = json.dumps(run.config or {}, indent=2)
            if is_ajax:
                return JsonResponse({"title": title, "content": content})
            return HttpResponse(cls._render_standalone_code(title, content), content_type="text/html")

        # Default to log
        title = f"Run #{run.id} - Execution Log"
        content = run.log or "No execution log recorded."
        if is_ajax:
            return JsonResponse({"title": title, "content": content})
        return HttpResponse(cls._render_standalone_code(title, content), content_type="text/html")

    @staticmethod
    def _render_standalone_code(title: str, content: str) -> str:
        escaped_title = escape(title)
        escaped_content = escape(content)
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escaped_title}</title>
    <style>
        body {{ margin: 0; padding: 24px; background: #0f172a; color: #f8fafc; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; line-height: 1.6; }}
        pre {{ margin: 0; white-space: pre-wrap; word-break: break-all; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 16px; }}
        button {{ background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; }}
        button:hover {{ background: #334155; }}
    </style>
</head>
<body>
    <div class="header">
        <strong>{escaped_title}</strong>
        <button onclick="navigator.clipboard.writeText(document.getElementById('code-body').innerText); this.innerText='Copied!';">Copy</button>
    </div>
    <pre id="code-body"><code>{escaped_content}</code></pre>
</body>
</html>"""

    def get_context_data(self, request, instance) -> dict:
        content_type = ContentType.objects.get_for_model(instance)
        refresh_url = f"refresh-section/{self.key}/{content_type.id}/{instance.pk}/"
        context = super().get_context_data(request, instance)
        context.update({
            "request": request,
            "title": self.title,
            "instance": instance,
            "section_key": self.key,
            "is_loaded": False,
            "collapsible": self.collapsible,
            "content_type_id": content_type.id,
            "refresh_url": refresh_url,
        })
        return context


RunSection = BacktestRunSection

