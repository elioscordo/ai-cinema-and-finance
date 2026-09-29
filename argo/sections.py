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
    form_class = StrategyCodeForm
    title = _("Strategy Source Code")
    key = "strategy_code"
    use_markdown_widgets = False
    submit_label = _("Save Code to File")
