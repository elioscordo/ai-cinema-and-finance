from django.contrib import admin
from unfold.admin import ModelAdmin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import Task, TaskLog, TaskPreset


@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = (
        'id', 'created', 'owner', 'task_type', 'display_admin_links', 'payload', 'html_status', 
        'last_logs', 'retries', 'view_logs_link'
    )
    list_filter = ('task_type', 'status', 'created', 'modified', 'owner', 'subject_ct', 'subject_id')
    search_fields = ('id', 'owner__username', 'task_type', 'status')
    readonly_fields = ('retry_attempts', 'display_admin_links')
    actions = [
        'reprocess'
    ]

    def _build_admin_link(self, label, ct, pk, instance):
        if not ct and not instance:
            return ""
        if instance:
            try:
                url = reverse(f"admin:{instance._meta.app_label}_{instance._meta.model_name}_change", args=[instance.pk])
                name = str(instance)
                short_name = name[:36] + "..." if len(name) > 36 else name
                return format_html(
                    '<div class="text-xs leading-5">'
                    '<span class="font-semibold text-gray-500 dark:text-gray-400">{}:</span> '
                    '<a href="{}" class="font-medium text-primary-600 dark:text-primary-400 hover:underline" title="{}">{}</a>'
                    '</div>',
                    label, url, name, short_name
                )
            except Exception:
                return format_html(
                    '<div class="text-xs leading-5"><span class="font-semibold text-gray-500">{}:</span> {}</div>',
                    label, str(instance)
                )
        if ct and pk:
            return format_html(
                '<div class="text-xs leading-5 text-gray-400"><span class="font-semibold">{}:</span> {} #{} (missing)</div>',
                label, ct.model, pk
            )
        return ""

    @admin.display(description=_("Subject / Object / Thr"))
    def display_admin_links(self, obj):
        targets = [
            ("Subject", obj.subject_ct, obj.subject_id, obj.subject),
            ("Object", obj.obj_ct, obj.obj_id, obj.obj),
            ("Thr", obj.thr_ct, obj.thr_id, obj.thr),
        ]
        links = [self._build_admin_link(label, ct, pk, instance) for label, ct, pk, instance in targets]
        active = [link for link in links if link]
        if not active:
            return "-"
        return format_html('<div class="flex flex-col gap-0.5">{}</div>', mark_safe("".join(active)))

    display_subject_links = display_admin_links
    subject_admin_links = display_admin_links

    def retries(self, obj):
        return f"{obj.retry_attempts} / {obj.retry_max_attempts}"
    retries.short_description = "Retries"

    def view_logs_link(self, obj):
        count = obj.tasklog_set.count()
        url = (
            reverse("admin:task_tasklog_changelist")
            + f"?task__id__exact={obj.id}"
        )
        return format_html('<a href="{}">{} Logs</a>', url, count)
    view_logs_link.short_description = "Logs"

    def reprocess(self, request, queryset):
        for item in queryset:
            msg = f"The task {item.id} has been queued for reprocessing"
            item.process()
            self.message_user(
                request,
                msg
            )
    reprocess.short_description = "Retry"

@admin.register(TaskLog)
class TaskLogAdmin(ModelAdmin):
    list_display = ('id', 'task', 'created', 'level', 'text')
    list_filter = ('level', 'created', 'task')
    search_fields = ('text', 'task__id')


@admin.register(TaskPreset)
class TaskPresetAdmin(ModelAdmin):
    list_display = (
        'id', 'name', 'preset_type',
        'description', 'preset', 'system_default'
    )
    list_editable = ('name', 'description', 'preset_type', 'system_default')
