from django import forms
from unfold_markdown import MarkdownWidget

class DynamicMarkdownWidget(MarkdownWidget):
    @property
    def media(self):
        media = super().media
        js_list = []
        for js_file in media._js:
            if "unfold_markdown" in js_file and "easymde" not in js_file:
                js_list.append("js/dynamic_markdown.js")
            else:
                js_list.append(js_file)
        
        if "js/dynamic_markdown.js" not in js_list:
            js_list.append("js/dynamic_markdown.js")
            
        return forms.Media(
            css=media._css,
            js=js_list
        )


class CodeWidget(forms.Textarea):
    """
    Code editor widget with syntax highlighting, line numbers, and indentation.
    Configurable language mode (defaults to python) and compatible with AJAX admin contexts.
    """
    is_code = True

    def __init__(self, *args, language="python", **kwargs):
        self.language = language
        attrs = kwargs.setdefault("attrs", {})
        attrs["data-code-editor"] = "true"
        attrs["data-language"] = language
        existing_class = attrs.get("class", "")
        attrs["class"] = f"{existing_class} code-editor-textarea".strip()
        super().__init__(*args, **kwargs)

    @property
    def media(self):
        return forms.Media(
            css={
                "all": [
                    "css/code_editor.css",
                ]
            },
            js=[
                "js/code_editor.js",
            ]
        )